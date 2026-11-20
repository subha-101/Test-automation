"""Data-flow analysis (Module 5).

Fills, in the IR:
  * per-variable read / written / read-before-write / conditionally-written flags and the role
    (input | output | state | internal)
  * the variable dependency database (data and control dependencies)
  * ``cond_uses``: for every condition and every variable it reads, which definitions can reach it.
    This is the record that makes "C2 uses the counter *after* C1 updated it" explicit.
"""
from __future__ import annotations

from .ir import CondUse, Expr, FunctionIR, Stmt, VarDependency


class _State:
    def __init__(self) -> None:
        self.defs: dict = {}          # var -> set(labels) of reaching definitions
        self.definite: set = set()    # written on every path so far
        self.maybe: set = set()       # written on at least one path

    def copy(self) -> "_State":
        n = _State()
        n.defs = {k: set(v) for k, v in self.defs.items()}
        n.definite, n.maybe = set(self.definite), set(self.maybe)
        return n


def _vars_in(e: Expr, acc: list) -> list:
    if e is None:
        return acc
    if e.kind == "var_ref" and e.name not in acc:
        acc.append(e.name)
    if e.kind == "call":
        tok = f"{e.name}()"
        if tok not in acc:
            acc.append(tok)
    for c in e.children:
        _vars_in(c, acc)
    return acc


def analyze(ir: FunctionIR) -> FunctionIR:
    ir.var_dependencies, ir.cond_uses = [], []
    for v in ir.variables.values():
        v.read = v.written = v.read_before_write = v.conditionally_written = False

    def read(name: str, st: _State) -> None:
        v = ir.variables.get(name)
        if v is None:
            return
        v.read = True
        if name not in st.definite and v.scope in ("global", "static", "param"):
            v.read_before_write = True

    def write(name: str, st: _State, label: str) -> None:
        v = ir.variables.get(name)
        if v is None:
            return
        v.written = True
        st.defs[name] = {label}
        st.definite.add(name)
        st.maybe.add(name)

    def label_of(s: Stmt) -> str:
        return f"{s.text} @{s.loc}"

    def effects(e: Expr, st: _State, s: Stmt, ctrl: list) -> None:
        if e is None:
            return
        if e.kind == "var_ref":
            read(e.name, st)
            return
        if e.kind == "assign":
            lhs, rhs = e.children
            effects(rhs, st, s, ctrl)
            srcs = _vars_in(rhs, [])
            if e.op != "=":
                effects(lhs, st, s, ctrl)
                srcs = _vars_in(lhs, []) + [x for x in srcs if x not in _vars_in(lhs, [])]
            if lhs.kind == "var_ref":
                ir.var_dependencies.append(VarDependency(lhs.name, srcs, "data", s.text, s.loc))
                if ctrl:
                    ir.var_dependencies.append(VarDependency(lhs.name, list(ctrl), "control", s.text, s.loc))
                write(lhs.name, st, label_of(s))
            return
        if e.kind == "incdec":
            tgt = e.children[0]
            effects(tgt, st, s, ctrl)
            if tgt.kind == "var_ref":
                ir.var_dependencies.append(VarDependency(tgt.name, [tgt.name], "data", s.text, s.loc))
                if ctrl:
                    ir.var_dependencies.append(VarDependency(tgt.name, list(ctrl), "control", s.text, s.loc))
                write(tgt.name, st, label_of(s))
            return
        for c in e.children:
            effects(c, st, s, ctrl)

    def walk(stmts: list, st: _State, ctrl: list) -> _State:
        for s in stmts:
            if s.kind == "decl":
                if s.expr is not None:
                    effects(s.expr, st, s, ctrl)
                    ir.var_dependencies.append(VarDependency(s.var, _vars_in(s.expr, []), "data", s.text, s.loc))
                write(s.var, st, label_of(s))
            elif s.kind in ("expr", "return"):
                effects(s.expr, st, s, ctrl)
            elif s.kind == "if":
                cond = ir.condition(s.cond_id)
                for v in cond.vars:
                    defs = sorted(st.defs.get(v, {"entry"}))
                    ir.cond_uses.append(CondUse(cond.id, v, defs, modified_before=any(d != "entry" for d in defs)))
                effects(s.expr, st, s, ctrl)
                inner = ctrl + [v for v in cond.vars if v not in ctrl]
                a = walk(s.then, st.copy(), inner)
                b = walk(s.els, st.copy(), inner) if s.els else st.copy()
                st.definite = a.definite & b.definite
                st.maybe = a.maybe | b.maybe
                keys = set(a.defs) | set(b.defs)
                st.defs = {k: a.defs.get(k, {"entry"}) | b.defs.get(k, {"entry"}) for k in keys}
        return st

    final = walk(ir.body, _State(), [])
    for name, v in ir.variables.items():
        v.conditionally_written = v.written and name not in final.definite
        if v.scope == "param":
            v.role = "input"
        elif v.scope == "local":
            v.role = "internal"
        elif v.read_before_write and v.written:
            v.role = "state"
        elif v.read_before_write:
            v.role = "input"
        elif v.written:
            v.role = "output"
        else:
            v.role = "internal"
    return ir
