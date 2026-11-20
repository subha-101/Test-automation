"""Control-flow graph (Module 4): basic blocks, branch nodes, decision edges, early returns, path count."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

from .ir import FunctionIR


@dataclass
class CFGNode:
    id: int
    kind: str                        # entry | block | branch | exit
    label: str = ""
    stmts: list = field(default_factory=list)
    cond_id: str = ""


@dataclass
class CFG:
    nodes: list = field(default_factory=list)
    edges: list = field(default_factory=list)       # (src, dst, label)

    def to_dict(self) -> dict:
        return asdict(self)

    def successors(self, nid: int) -> list:
        return [(d, l) for s, d, l in self.edges if s == nid]

    def syntactic_paths(self, limit: int = 100000) -> int:
        """Number of entry->exit paths ignoring feasibility."""
        memo: dict = {}

        def count(n: int) -> int:
            if n in memo:
                return memo[n]
            node = self.nodes[n]
            if node.kind == "exit":
                return 1
            memo[n] = min(limit, sum(count(d) for d, _ in self.successors(n)))
            return memo[n]

        return count(0)

    def to_dot(self) -> str:
        out = ["digraph cfg {", "  node [shape=box, fontname=Courier];"]
        for n in self.nodes:
            shape = {"branch": "diamond", "entry": "oval", "exit": "oval"}.get(n.kind, "box")
            text = (n.label or n.kind) + ("\\n" + "\\n".join(n.stmts) if n.stmts else "")
            out.append(f'  n{n.id} [shape={shape}, label="{text.replace(chr(34), chr(39))}"];')
        for s, d, l in self.edges:
            out.append(f'  n{s} -> n{d}' + (f' [label="{l}"];' if l else ";"))
        out.append("}")
        return "\n".join(out)


def build_cfg(ir: FunctionIR) -> CFG:
    g = CFG()

    def new(kind: str, label: str = "", cond: str = "") -> CFGNode:
        n = CFGNode(id=len(g.nodes), kind=kind, label=label, cond_id=cond)
        g.nodes.append(n)
        return n

    entry = new("entry", "entry")
    exit_ = new("exit", "exit")

    def build(stmts: list, frontier: list) -> list:
        blk = None
        for s in stmts:
            if s.kind == "if":
                blk = None
                br = new("branch", f"{s.cond_id}: {s.text}", s.cond_id)
                for n, l in frontier:
                    g.edges.append((n, br.id, l))
                t_front = build(s.then, [(br.id, "T")])
                f_front = build(s.els, [(br.id, "F")]) if s.els else [(br.id, "F")]
                frontier = t_front + f_front
                continue
            if blk is None:
                blk = new("block", f"B{len(g.nodes)}")
                for n, l in frontier:
                    g.edges.append((n, blk.id, l))
                frontier = [(blk.id, "")]
            blk.stmts.append(s.text)
            if s.kind == "return":
                g.edges.append((blk.id, exit_.id, "return"))
                frontier = []
                blk = None
        return frontier

    tail = build(ir.body, [(entry.id, "")])
    for n, l in tail:
        g.edges.append((n, exit_.id, l))
    return g
