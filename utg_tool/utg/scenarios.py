"""Test scenario generation (Module 6).

Targets
  decision  ('D', cond, True|False)            branch coverage
  outcome   ('O', atom, 'true'|'false')        condition coverage
  boundary  ('R', atom, lt|eq|gt|ne)           boundary-value analysis, operator rules of the specification

A scenario is created per still-uncovered target by picking the best feasible path and solving
(path constraints AND target relation) with Z3.  What a scenario actually covers is *evaluated from its
model* (not assumed).  A redundancy pass then removes scenarios whose coverage is fully provided by others.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import z3

from .config import ProjectConfig
from .ir import FunctionIR
from .solver import solve
from .symexec import AtomRec, Path, SymbolicExecutor, Unsupported, model_value

STRATEGIES = ("branch", "condition", "boundary")
REL_WORDS = {"lt": "less than", "eq": "equal to", "gt": "greater than", "ne": "not equal to",
             "true": "TRUE", "false": "FALSE"}
_ORDER_REL = {"<": ("<", "lt"), "<=": ("<", "lt"), ">": (">", "gt"), ">=": (">", "gt")}


@dataclass(frozen=True)
class Target:
    key: tuple
    text: str

    @property
    def kind(self) -> str:
        return {"D": "decision", "O": "outcome", "R": "boundary", "W": "wrap"}[self.key[0]]


@dataclass
class EventValue:
    name: str
    order: int
    args: list                       # [(param_name, type_spelling, value)]
    ret_value: object = None
    members: dict = field(default_factory=dict)
    ret_type: object = None


@dataclass
class Scenario:
    idx: int
    name: str
    goals: list                      # keys of targets it was created for
    path_id: int
    decisions: list
    inputs: dict                     # var -> value
    events: list                     # [EventValue]
    expected_vars: dict              # var -> value
    expected_ret: object
    covers: set                      # achieved target keys
    description: str = ""
    assumptions: list = field(default_factory=list)


@dataclass
class GenerationResult:
    scenarios: list
    targets: list
    uncovered: list                  # [(Target, reason)]
    path_count: int
    truncated: bool
    strategies: list
    unsupported: list = field(default_factory=list)
    blocked: Optional[dict] = None


# ---------------------------------------------------------------------------------------------------------
def ctx_map(ir: FunctionIR) -> dict:
    """atom id -> earlier condition ids whose branches (re)define a variable the atom reads.

    A boundary of such an atom is only meaningful *together with* those earlier decisions (e.g. the timer
    comparison must be exercised both after the counter was incremented and after it was reset)."""
    writes: dict = {}
    order = {c.id: i for i, c in enumerate(ir.conditions)}

    def assigned(stmts, acc) -> None:
        def ex(e) -> None:
            if e.kind == "assign" and e.children[0].kind == "var_ref":
                acc.add(e.children[0].name)
            if e.kind == "incdec" and e.children[0].kind == "var_ref":
                acc.add(e.children[0].name)
            for c in e.children:
                ex(c)
        for st in stmts:
            if st.expr is not None and st.kind != "if":
                ex(st.expr)
            assigned(st.then, acc)
            assigned(st.els, acc)

    def collect(stmts) -> None:
        for st in stmts:
            if st.kind == "if":
                acc: set = set()
                assigned(st.then + st.els, acc)
                writes[st.cond_id] = acc
                collect(st.then)
                collect(st.els)

    collect(ir.body)
    out: dict = {}
    for c in ir.conditions:
        for a in c.atoms:
            out[a.id] = [e.id for e in ir.conditions
                         if order[e.id] < order[c.id] and writes.get(e.id, set()) & set(a.vars)]
    return out


def _ctx_text(ctx: tuple) -> str:
    return "" if not ctx else " after " + ", ".join(f"{c}={'TRUE' if o else 'FALSE'}" for c, o in ctx)


def _contexts(cids: list) -> list:
    import itertools
    return [tuple(zip(cids, vals)) for vals in itertools.product((True, False), repeat=len(cids))] if cids else [()]


def build_targets(ir: FunctionIR, strategies: set) -> list:
    t: list = []
    cmap = ctx_map(ir)
    if "branch" in strategies:
        for c in ir.conditions:
            for o in (True, False):
                t.append(Target(("D", c.id, o), f"{c.id} decision {'TRUE' if o else 'FALSE'}: {c.text}"))
    for c in ir.conditions:
        for a in c.atoms:
            if "boundary" in strategies:
                rels = ["lt", "eq", "gt"] if a.op in ("<", "<=", ">", ">=") else \
                       ["eq", "ne"] if a.op in ("==", "!=") else ["true", "false"]
                for ctx in _contexts(cmap[a.id]):
                    for r in rels:
                        base = (f"{a.id} [{a.text}]: lhs {REL_WORDS[r]} rhs" if a.op
                                else f"{a.id} [{a.text}]: {REL_WORDS[r]}")
                        t.append(Target(("R", a.id, r, ctx), base + _ctx_text(ctx)))
            elif "condition" in strategies:
                for r in ("true", "false"):
                    t.append(Target(("O", a.id, r), f"{a.id} [{a.text}] outcome {REL_WORDS[r]}"))
    if "boundary" in strategies:
        for wid, text in _wrap_sites(ir):
            t.append(Target(("W", wid, "wrap"), f"{text} executed at the unsigned type limit (wrap-around)"))
    return t


def _wrap_sites(ir: FunctionIR) -> list:
    """Unsigned ++/-- statements (source order): their wrap-around is a boundary of the operand type."""
    out: list = []

    def walk_e(e) -> None:
        if e.kind == "incdec" and e.children and e.children[0].type.kind in ("int", "enum") \
                and not e.children[0].type.signed:
            out.append((f"W@{e.loc.line}:{e.loc.col}", e.text))
        for c in e.children:
            walk_e(c)

    def walk(stmts) -> None:
        for s in stmts:
            if s.expr is not None:
                walk_e(s.expr)
            walk(s.then)
            walk(s.els)

    walk(ir.body)
    return out


def _rel_constraint(rec: AtomRec, rel: str):
    ex = SymbolicExecutor.relation
    if rel in ("lt", "gt", "eq"):
        return ex({"lt": "<", "gt": ">", "eq": "=="}[rel], rec.lhs, rec.rhs)
    if rel == "ne":
        return ex("!=", rec.lhs, rec.rhs)
    return rec.truth if rel == "true" else z3.Not(rec.truth)


def _achieved(path: Path, model: z3.ModelRef, cmap: dict) -> set:
    out = set()
    taken = dict(path.decisions)
    for cid, o in path.decisions:
        out.add(("D", cid, o))
    wrapped = False
    for w in path.wraps:
        if z3.is_true(model.eval(w.cond, model_completion=True)):
            out.add(("W", w.wrap_id, "wrap"))
            wrapped = True
    if wrapped:
        # values downstream of a wrap-around are artefacts: such a scenario only earns its decisions and its
        # explicit wrap target, never ordinary boundary / condition credit (that would make the natural
        # boundary scenario look redundant)
        return out
    for r in path.atoms:
        if not z3.is_true(model.eval(r.guard, model_completion=True)):
            continue
        t = z3.is_true(model.eval(r.truth, model_completion=True))
        out.add(("O", r.atom_id, "true" if t else "false"))
        if r.op is None:
            out.add(("R", r.atom_id, "true" if t else "false", tuple((c, taken[c]) for c in cmap.get(r.atom_id, []) if c in taken)))
            continue
        ctx = tuple((c, taken[c]) for c in cmap.get(r.atom_id, []) if c in taken)
        rel = lambda op: z3.is_true(model.eval(SymbolicExecutor.relation(op, r.lhs, r.rhs), model_completion=True))
        if r.op in _ORDER_REL:
            out.add(("R", r.atom_id, "eq" if rel("==") else "lt" if rel("<") else "gt", ctx))
        else:
            out.add(("R", r.atom_id, "eq" if rel("==") else "ne", ctx))
    return out


class ScenarioGenerator:
    def __init__(self, ir: FunctionIR, cfg: ProjectConfig) -> None:
        self.ir, self.cfg = ir, cfg

    def generate(self, strategies=("branch", "condition", "boundary")) -> GenerationResult:
        strategies = set(strategies)
        unknown = strategies - set(STRATEGIES)
        if unknown:
            raise ValueError(f"unsupported strategy {sorted(unknown)}; implemented: {STRATEGIES} (MC/DC is planned for phase 3)")
        diagnostic = next((u for u in self.ir.unsupported if u["kind"] == "diagnostic"), None)
        if diagnostic:
            return GenerationResult([], [], [], 0, False, sorted(strategies), list(self.ir.unsupported), diagnostic)
        self.cmap = ctx_map(self.ir)
        ex = SymbolicExecutor(self.ir, self.cfg)
        self.ctx = ex.ctx
        try:
            paths = ex.explore()
        except Unsupported as exc:
            blocked = {"kind": "execution", "loc": exc.loc, "reason": str(exc),
                       "effect": "No scenarios can be generated for this function."}
            return GenerationResult([], [], [], 0, False, sorted(strategies), [*self.ir.unsupported, blocked], blocked)
        paths = [p for p in paths if not p.defined or self._solve_path(p, [], []) is not None]
        targets = build_targets(self.ir, strategies)
        covered: set = set()
        raw: list = []          # (goal_key, path, model, achieved)
        uncovered: list = []

        for tg in targets:
            if tg.key in covered:
                continue
            cands = self._candidates(tg, paths, covered)
            done = False
            for path, extra in cands:
                model = self._solve_path(path, extra, self._soft(path, tg))
                if model is None:
                    continue
                ach = _achieved(path, model, self.cmap)
                if tg.key not in ach:          # defensive: model must realise the goal
                    continue
                raw.append((tg.key, path, model, ach))
                covered |= ach
                done = True
                break
            if not done:
                uncovered.append((tg, "proven infeasible by Z3 (no input satisfies the path constraints): not a coverage gap"
                                  if cands else "no execution path evaluates this condition"))

        keep = self._drop_redundant(raw)
        if not targets:
            for path in paths:
                model = self._solve_path(path, [], self._soft(path, None))
                if model is not None:
                    keep = [(("smoke",), path, model, set())]
                    break
        scenarios = [self._materialise(i + 1, *r) for i, r in enumerate(keep)]
        return GenerationResult(scenarios, targets, uncovered, len(paths), ex.truncated, sorted(strategies),
                                list(self.ir.unsupported))

    # ------------------------------------------------------------------
    def _solve_path(self, path: Path, extra: list, soft: list) -> Optional[z3.ModelRef]:
        constraints = path.pc + path.domain + extra
        # A concrete model can check costly FP conversion ranges without bit-blasting them.
        model = solve(constraints, path.symbols, self.cfg, self.ctx, soft)
        if model is not None and not all(z3.is_true(model.eval(c, model_completion=True)) for c in path.defined):
            return solve(constraints + path.defined, path.symbols, self.cfg, self.ctx, soft)
        return model

    def _candidates(self, tg: Target, paths: list, covered: set) -> list:
        out = []
        kind = tg.key[0]
        for p in paths:
            if kind == "D":
                if (tg.key[1], tg.key[2]) in p.decisions:
                    out.append((p, []))
                continue
            if kind == "W":
                for w in p.wraps:
                    if w.wrap_id == tg.key[1]:
                        out.append((p, [w.cond]))
                        break
                continue
            ctx = tg.key[3] if len(tg.key) > 3 else ()
            if not all(d in p.decisions for d in ctx):
                continue
            for r in p.atoms:
                if r.atom_id == tg.key[1]:
                    out.append((p, [r.guard, _rel_constraint(r, tg.key[2])]))
                    break
        # prefer paths that cover many still-open targets (deterministic: ties keep exploration order)
        def score(item):
            p = item[0]
            s = sum(1 for d in p.decisions if ("D", d[0], d[1]) not in covered)
            s += sum(1 for r in p.atoms if ("O", r.atom_id, "true") not in covered or ("O", r.atom_id, "false") not in covered)
            return -s
        return sorted(out, key=score)          # sorted() is stable

    def _soft(self, path: Path, tg: Optional[Target]) -> list:
        """Preferences: (1) no incidental wrap-around, (2) written-only state starts different from its result."""
        soft = [z3.Not(w.cond) for w in path.wraps if not (tg and tg.key[0] == "W" and tg.key[1] == w.wrap_id)]
        for name in path.witness:
            init, fin = path.inputs[name], path.final[name]
            soft.append(z3.Not(z3.fpEQ(init.z, fin.z, ctx=self.ctx)) if init.ti.kind == "float" else init.z != fin.z)
        return soft

    @staticmethod
    def _drop_redundant(raw: list) -> list:
        keep = list(range(len(raw)))
        for i in reversed(range(len(raw))):
            others = set().union(*[raw[j][3] for j in keep if j != i]) if len(keep) > 1 else set()
            if raw[i][3] <= others:
                keep.remove(i)
        return [raw[i] for i in keep]

    def _materialise(self, idx: int, goal: tuple, path: Path, model: z3.ModelRef, ach: set) -> Scenario:
        inputs = {n: model_value(model, path.inputs[n]) for n in self.ir.variables if n in path.inputs}
        events = []
        for e in path.events:
            info = self.ir.calls[e.name]
            args = [(info.params[i][0] if i < len(info.params) else f"arg{i}",
                     info.params[i][1].spelling if i < len(info.params) else "",
                     a.address if a.address is not None else model_value(model, a)) for i, a in enumerate(e.args)]
            events.append(EventValue(
                name=e.name, order=e.order, args=args,
                ret_value=model_value(model, e.ret) if e.ret is not None else None,
                members={m: model_value(model, v) for m, v in sorted(e.members.items())},
                ret_type=info.return_type))
        expected_vars = {n: model_value(model, path.final[n]) for n in path.written}
        ret = model_value(model, path.ret) if path.ret is not None else None
        name = f"{self.cfg.testcase_prefix}_{self.cfg.function_index}_{idx}"
        sc = Scenario(idx=idx, name=name, goals=[goal], path_id=path.id, decisions=list(path.decisions),
                      inputs=inputs, events=events, expected_vars=expected_vars, expected_ret=ret,
                      covers=ach, assumptions=list(path.assumptions))
        sc.description = self._describe(sc)
        return sc

    def _describe(self, sc: Scenario) -> str:
        if sc.goals[0] == ("smoke",):
            return "Straight-line execution: verify the observable effects."
        text = {t.key: t.text for t in build_targets(self.ir, set(STRATEGIES))}
        goal = text.get(sc.goals[0], str(sc.goals[0]))
        path = ", ".join(f"{c}={'TRUE' if o else 'FALSE'}" for c, o in sc.decisions)
        return f"Target: {goal}. Decisions taken: {path}."
