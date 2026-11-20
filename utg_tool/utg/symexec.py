"""Deterministic symbolic execution of the supported C subset (Modules 7 and 8).

* Values are Z3 bit-vectors (integers, with the exact width / signedness resolved by Clang) or IEEE-754
  floating-point terms (so C float semantics are respected, not real-number arithmetic).
* Statements execute strictly in source order; every later condition sees the state produced by the earlier
  statements (counter incremented / reset, values copied from mocks, ...).
* Each `if` forks the state; infeasible branches are pruned with Z3.  The result is the list of feasible
  execution paths with their path constraints, mock-call events, final state and return value.
* Unsupported constructs raise ``Unsupported`` - they are reported, never silently skipped.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Optional

import z3

from .config import ProjectConfig
from .ir import Expr, FunctionIR, Stmt, TypeInfo

z3.set_param("smt.random_seed", 0)
z3.set_param("sat.random_seed", 0)
INT_BITS = 32          # width of `int` on the configured target (ARM Cortex-M)


class Unsupported(Exception):
    loc = ""


# ---------------------------------------------------------------------------------------------------------
# values
# ---------------------------------------------------------------------------------------------------------
@dataclass
class Val:
    z: object                        # z3 BitVec / FP term  (None for void)
    ti: TypeInfo
    b: object = None                 # z3 Bool for comparison / logical results (kept to avoid If wrapping)
    struct_of: Optional[tuple] = None  # (callee, call_no) when the value is a struct returned by a mock
    address: Optional[str] = None


def fp_sort(ti: TypeInfo, ctx: z3.Context):
    return z3.Float32(ctx) if ti.bits == 32 else z3.Float64(ctx)


def mk_symbol(name: str, ti: TypeInfo, ctx: z3.Context):
    if ti.kind == "float":
        return z3.FP(name, fp_sort(ti, ctx))
    return z3.BitVec(name, ti.bits, ctx)


def bv_const(value: int, bits: int, ctx: z3.Context):
    return z3.BitVecVal(value & ((1 << bits) - 1), bits, ctx)


INT_TI = TypeInfo(spelling="int", canonical="int", kind="int", bits=INT_BITS, signed=True)


def truth(v: Val):
    if v.ti.kind == "pointer":
        raise Unsupported("pointer used as a condition")
    if v.b is not None:
        return v.b
    if v.ti.kind == "float":
        ctx = v.z.ctx
        return z3.Not(z3.fpEQ(v.z, z3.FPVal(0.0, fp_sort(v.ti, ctx), ctx=ctx), ctx=ctx))
    return v.z != bv_const(0, v.ti.bits, v.z.ctx)


def from_bool(b, ti: TypeInfo = INT_TI) -> Val:
    return Val(z3.If(b, bv_const(1, ti.bits, b.ctx), bv_const(0, ti.bits, b.ctx)), ti, b=b)


def convert(v: Val, to: TypeInfo, st=None) -> Val:
    if v.address is not None:
        if to.kind == "pointer":
            return Val(None, to, address=v.address)
        raise Unsupported(f"address converted to {to.spelling}")
    if v.struct_of is not None:
        raise Unsupported("struct value used as a whole")
    if to.kind == "void":
        return Val(None, to)
    if to.kind == "bool":
        return from_bool(truth(v), to)
    if to.kind in ("int", "enum"):
        if v.ti.kind == "float":
            if st is None or to.kind != "int" or v.ti.bits not in (32, 64) or to.bits > 32:
                raise Unsupported(f"float -> {to.spelling} conversion")
            # Truncation toward zero is defined only when the truncated value fits.
            lo = -(1 << (to.bits - 1)) if to.signed else 0
            hi = (1 << (to.bits - int(bool(to.signed))))
            ctx = v.z.ctx
            double = z3.Float64(ctx)
            wide = v.z if v.ti.bits == 64 else z3.fpToFP(z3.RNE(ctx), v.z, double, ctx=ctx)
            st.defined.extend([z3.fpGT(wide, z3.FPVal(lo - 1, double, ctx=ctx), ctx=ctx),
                               z3.fpLT(wide, z3.FPVal(hi, double, ctx=ctx), ctx=ctx)])
            st.assumptions.append(f"float -> {to.spelling} is representable after truncation")
            conv = z3.fpToSBV if to.signed else z3.fpToUBV
            return Val(conv(z3.RTZ(ctx), v.z, z3.BitVecSort(to.bits, ctx), ctx=ctx), to)
        m, n = v.z.size(), to.bits
        if n == m:
            z = v.z
        elif n > m:
            z = z3.SignExt(n - m, v.z) if v.ti.signed else z3.ZeroExt(n - m, v.z)
        else:
            z = z3.Extract(n - 1, 0, v.z)
        return Val(z, to)
    if to.kind == "float":
        ctx = v.z.ctx
        s = fp_sort(to, ctx)
        if v.ti.kind == "float":
            return v if v.ti.bits == to.bits else Val(z3.fpToFP(z3.RNE(ctx), v.z, s, ctx=ctx), to)
        if v.ti.signed:
            return Val(z3.fpSignedToFP(z3.RNE(ctx), v.z, s, ctx=ctx), to)
        return Val(z3.fpToFPUnsigned(z3.RNE(ctx), v.z, s, ctx=ctx), to)
    raise Unsupported(f"conversion to {to.spelling}")


def common_type(a: TypeInfo, b: TypeInfo) -> TypeInfo:
    """C usual arithmetic conversions (used only where Clang left operands un-cast, e.g. compound assignment)."""
    if a.kind == "float" or b.kind == "float":
        if a.kind == "float" and b.kind == "float":
            return a if a.bits >= b.bits else b
        return a if a.kind == "float" else b

    def promote(t: TypeInfo) -> TypeInfo:
        if t.bits < INT_BITS or t.kind in ("bool", "enum"):
            return INT_TI if t.bits < INT_BITS else TypeInfo(spelling="int", canonical="int", kind="int",
                                                              bits=t.bits, signed=t.signed)
        return t
    a, b = promote(a), promote(b)
    if a.bits != b.bits:
        return a if a.bits > b.bits else b
    if a.signed == b.signed:
        return a
    return a if not a.signed else b


# ---------------------------------------------------------------------------------------------------------
# state / path records
# ---------------------------------------------------------------------------------------------------------
@dataclass
class Event:
    name: str
    index: int                       # n-th call of this callee on the path
    args: list                       # [Val]
    ret: Optional[Val] = None        # symbolic return value (numeric)
    members: dict = field(default_factory=dict)   # struct member -> symbolic Val
    order: int = 0                   # global order on the path


@dataclass
class AtomRec:
    atom_id: str
    cond_id: str
    guard: object                    # z3 Bool: the atom is evaluated on this path iff guard holds
    lhs: Optional[Val]
    rhs: Optional[Val]
    op: Optional[str]
    truth: object                    # z3 Bool: value of the atom


@dataclass
class WrapRec:
    wrap_id: str                     # "W@<line>:<col>" - stable id of the ++/-- statement
    text: str
    cond: object                     # z3 Bool: the operand is at its type limit (next ++ / -- wraps)


@dataclass
class Path:
    id: int
    decisions: list                  # [(cond_id, bool)]
    pc: list                         # path constraints (z3 Bool)
    domain: list                     # domain constraints on symbols (finite floats ...)
    events: list
    atoms: list
    final: dict                      # name -> Val
    written: list                    # file-scope variables written, in first-write order
    symbols: dict                    # symbol name -> (Val, origin)  origin: "var:<name>" | "mock:<callee>#<n>[.member]"
    inputs: dict                     # var name -> Val (initial value read before write)
    ret: Optional[Val] = None
    assumptions: list = field(default_factory=list)
    wraps: list = field(default_factory=list)
    witness: list = field(default_factory=list)     # variables written but not read first: free initial value
    defined: list = field(default_factory=list)     # preconditions for operations with undefined behavior


class _State:
    def __init__(self) -> None:
        self.vars: dict = {}
        self.inputs: dict = {}
        self.symbols: dict = {}
        self.written: list = []
        self.events: list = []
        self.atoms: list = []
        self.pc: list = []
        self.domain: list = []
        self.decisions: list = []
        self.call_no: dict = {}
        self.ret: Optional[Val] = None
        self.todo: list = []
        self.assumptions: list = []
        self.wraps: list = []
        self.defined: list = []

    def fork(self) -> "_State":
        n = _State()
        n.vars, n.inputs, n.symbols = dict(self.vars), dict(self.inputs), dict(self.symbols)
        n.written, n.events, n.atoms = list(self.written), list(self.events), list(self.atoms)
        n.pc, n.domain, n.decisions = list(self.pc), list(self.domain), list(self.decisions)
        n.call_no, n.ret, n.todo = dict(self.call_no), self.ret, list(self.todo)
        n.assumptions = list(self.assumptions)
        n.wraps = list(self.wraps)
        n.defined = list(self.defined)
        return n


def has_side_effects(e: Expr) -> bool:
    if e.kind in ("assign", "incdec", "call", "mock_hook"):
        return True
    return any(has_side_effects(c) for c in e.children)


# ---------------------------------------------------------------------------------------------------------
# executor
# ---------------------------------------------------------------------------------------------------------
class SymbolicExecutor:
    def __init__(self, ir: FunctionIR, cfg: ProjectConfig) -> None:
        self.ir, self.cfg = ir, cfg
        # Concurrent Streamlit sessions must not share Z3's default native context.
        self.ctx = z3.Context()
        self.atom_ids = {id(a.expr): a.id for c in ir.conditions for a in c.atoms}
        self.truncated = False
        self.errors: list = []

    # ------------------------------------------------------------- symbols
    def _new_symbol(self, st: _State, name: str, ti: TypeInfo, origin: str) -> Val:
        v = Val(mk_symbol(name, ti, self.ctx), ti)
        st.symbols[name] = (v, origin)
        if ti.kind == "float" and self.cfg.assume_finite_floats:
            st.domain += [z3.Not(z3.fpIsNaN(v.z, ctx=self.ctx)), z3.Not(z3.fpIsInf(v.z, ctx=self.ctx))]
        if ti.kind == "bool":
            st.domain.append(z3.ULE(v.z, bv_const(1, 8, self.ctx)))
        if ti.kind == "enum" and ti.enumerators:
            st.domain.append(z3.Or(*[v.z == bv_const(x, ti.bits, self.ctx) for x in sorted(set(ti.enumerators.values()))]))
        return v

    def _read_var(self, name: str, st: _State) -> Val:
        if name in st.vars:
            return st.vars[name]
        vi = self.ir.variables[name]
        if vi.type.kind not in ("int", "bool", "float", "enum"):
            raise Unsupported(f"variable '{name}' has unsupported type {vi.type.spelling}")
        if vi.scope in ("local", "static_local"):
            raise Unsupported(f"local variable '{name}' read before initialisation")
        if vi.is_const and vi.initial_value is not None:          # compile-time constant: fold
            v = self._literal(vi.initial_value, vi.type)
        else:
            v = self._new_symbol(st, f"in__{name}", vi.type, f"var:{name}")
            st.inputs[name] = v
        st.vars[name] = v
        return v

    def _literal(self, value, ti: TypeInfo) -> Val:
        if ti.kind == "float":
            return Val(z3.FPVal(float(value), fp_sort(ti, self.ctx), ctx=self.ctx), ti)
        return Val(bv_const(int(value), ti.bits, self.ctx), ti)

    # ------------------------------------------------------------- expressions
    def ev(self, e: Expr, st: _State) -> Val:
        try:
            return self._ev(e, st)
        except Unsupported as exc:
            if not exc.loc:
                exc.loc = str(e.loc)
            raise

    def _ev(self, e: Expr, st: _State) -> Val:
        k = e.kind
        if k == "int_lit" or k == "float_lit":
            return self._literal(e.value, e.type)
        if k == "enum_const":
            return self._literal(e.value, e.type)
        if k == "var_ref":
            return self._read_var(e.name, st)
        if k == "cast":
            return convert(self.ev(e.children[0], st), e.type, st)
        if k == "binary":
            return self._binary(e, st)
        if k == "unary":
            return self._unary(e, st)
        if k == "incdec":
            tgt = e.children[0]
            if tgt.kind != "var_ref":
                raise Unsupported("increment of a non-variable lvalue")
            old = self._read_var(tgt.name, st)
            one = self._literal(1, old.ti)
            if old.ti.kind in ("int", "enum"):
                if old.ti.signed:       # signed overflow is undefined behaviour in C: excluded, and reported
                    lim = (1 << (old.ti.bits - 1)) - 1 if e.op == "++" else -(1 << (old.ti.bits - 1))
                    st.pc.append(old.z != bv_const(lim, old.ti.bits, self.ctx))
                    st.assumptions.append(f"signed '{e.text}' does not overflow (undefined behaviour in C)")
                else:                   # unsigned wrap-around is defined: recorded so it can be targeted explicitly
                    lim = (1 << old.ti.bits) - 1 if e.op == "++" else 0
                    st.wraps.append(WrapRec(f"W@{e.loc.line}:{e.loc.col}", e.text, old.z == bv_const(lim, old.ti.bits, self.ctx)))
            if old.ti.kind == "float":
                op = z3.fpAdd if e.op == "++" else z3.fpSub
                new = Val(op(z3.RNE(self.ctx), old.z, one.z, ctx=self.ctx), old.ti)
            else:
                new = Val(old.z + one.z if e.op == "++" else old.z - one.z, old.ti)
            self._assign(tgt.name, new, st)
            return new if e.prefix else old
        if k == "assign":
            return self._assign_expr(e, st)
        if k == "call":
            return self._call(e, st)
        if k == "mock_hook":
            if has_side_effects(e.children[0]):
                raise Unsupported("side effects in the CppUTest default argument")
            self.ev(e.children[0], st)  # C evaluates the default even when the mock returns an override.
            return self._call(e, st, args=[])
        if k == "member":
            base = e.children[0]
            if base.kind != "call":
                raise Unsupported("member access on a non-call expression")
            v = self._call(base, st)
            callee, n = v.struct_of
            ev = next(x for x in st.events if x.name == callee and x.index == n)
            if e.name not in ev.members:
                ev.members[e.name] = self._new_symbol(st, f"ret__{callee}_{n}__{e.name}", e.type,
                                                       f"mock:{callee}#{n}.{e.name}")
            return ev.members[e.name]
        if k == "cond":
            if any(has_side_effects(c) for c in e.children):
                raise Unsupported("conditional operator with side effects")
            c, a, b = (self.ev(x, st) for x in e.children)
            return Val(z3.If(truth(c), a.z, b.z), a.ti)
        raise Unsupported(f"expression kind '{k}' ({e.text})")

    def _assign(self, name: str, v: Val, st: _State) -> None:
        vi = self.ir.variables[name]
        if vi.type.kind not in ("int", "bool", "float", "enum"):
            raise Unsupported(f"assignment to '{name}' of type {vi.type.spelling}")
        st.vars[name] = convert(v, vi.type) if v.ti.canonical != vi.type.canonical else v
        if vi.scope in ("global", "static") and name not in st.written:
            st.written.append(name)

    def _assign_expr(self, e: Expr, st: _State) -> Val:
        lhs, rhs = e.children
        if lhs.kind != "var_ref":
            raise Unsupported(f"assignment to non-variable lvalue ({lhs.text})")
        if e.op == "=":
            v = self.ev(rhs, st)
        else:
            cur = self._read_var(lhs.name, st)
            r = self.ev(rhs, st)
            t = common_type(cur.ti, r.ti)
            v = self._arith(e.op[:-1], convert(cur, t), convert(r, t), t, st)
        self._assign(lhs.name, v, st)
        return st.vars[lhs.name]

    def _unary(self, e: Expr, st: _State) -> Val:
        if e.op == "&":
            obj = e.children[0]
            if obj.kind != "var_ref" or self.ir.variables[obj.name].scope not in ("static", "global"):
                raise Unsupported("only addresses of accessible file-scope objects are supported as mock arguments")
            return Val(None, e.type, address=obj.name)
        v = self.ev(e.children[0], st)
        if e.op == "!":
            return from_bool(z3.Not(truth(v)))
        if e.op == "+":
            return v
        if e.op == "-":
            return Val(z3.fpNeg(v.z, ctx=self.ctx) if v.ti.kind == "float" else -v.z, e.type)
        if e.op == "~":
            return Val(~v.z, e.type)
        raise Unsupported(f"unary operator '{e.op}' (pointers are not modelled yet)")

    def _arith(self, op: str, a: Val, b: Val, t: TypeInfo, st: _State) -> Val:
        if t.kind == "float":
            f = {"+": z3.fpAdd, "-": z3.fpSub, "*": z3.fpMul, "/": z3.fpDiv}.get(op)
            if f is None:
                raise Unsupported(f"float operator '{op}'")
            return Val(f(z3.RNE(self.ctx), a.z, b.z, ctx=self.ctx), t)
        x, y = a.z, b.z
        if op == "+": z = x + y
        elif op == "-": z = x - y
        elif op == "*": z = x * y
        elif op in ("/", "%"):
            st.pc.append(y != 0)
            st.assumptions.append(f"divisor of '{op}' is non-zero")
            z = (x / y if t.signed else z3.UDiv(x, y)) if op == "/" else (z3.SRem(x, y) if t.signed else z3.URem(x, y))
        elif op == "&": z = x & y
        elif op == "|": z = x | y
        elif op == "^": z = x ^ y
        elif op in ("<<", ">>"):
            st.pc.append(z3.ULT(y, bv_const(t.bits, t.bits, self.ctx)))
            st.assumptions.append(f"shift amount of '{op}' is smaller than the operand width")
            z = x << y if op == "<<" else (x >> y if t.signed else z3.LShR(x, y))
        else:
            raise Unsupported(f"operator '{op}'")
        return Val(z, t)

    def _binary(self, e: Expr, st: _State) -> Val:
        op = e.op
        if op in ("&&", "||"):
            if has_side_effects(e.children[1]):
                raise Unsupported(f"side effect in the right operand of '{op}' (short-circuit)")
            a, b = self.ev(e.children[0], st), self.ev(e.children[1], st)
            return from_bool(z3.And(truth(a), truth(b)) if op == "&&" else z3.Or(truth(a), truth(b)), e.type)
        a, b = self.ev(e.children[0], st), self.ev(e.children[1], st)
        if op in ("<", "<=", ">", ">=", "==", "!="):
            t = a.ti if a.ti.canonical == b.ti.canonical else common_type(a.ti, b.ti)
            a, b = convert(a, t), convert(b, t)
            return from_bool(self.relation(op, a, b), e.type)
        t = e.type if e.type.is_numeric else common_type(a.ti, b.ti)
        return self._arith(op, convert(a, t), convert(b, t), t, st)

    @staticmethod
    def relation(op: str, a: Val, b: Val):
        if a.ti.kind == "float":
            return {"<": z3.fpLT, "<=": z3.fpLEQ, ">": z3.fpGT, ">=": z3.fpGEQ, "==": z3.fpEQ,
                    "!=": z3.fpNEQ}[op](a.z, b.z, ctx=a.z.ctx)
        s = bool(a.ti.signed)
        x, y = a.z, b.z
        return {"<": (x < y) if s else z3.ULT(x, y), "<=": (x <= y) if s else z3.ULE(x, y),
                ">": (x > y) if s else z3.UGT(x, y), ">=": (x >= y) if s else z3.UGE(x, y),
                "==": x == y, "!=": x != y}[op]

    # ------------------------------------------------------------- calls (mocked)
    def _call(self, e: Expr, st: _State, args=None) -> Val:
        info = self.ir.calls.get(e.name)
        if info is None or not info.requires_mock:
            raise Unsupported(f"call to '{e.name}', which is defined in the analysed file (stubbing/inlining not supported yet)")
        if args is None:
            args = [self.ev(a, st) for a in e.children]
        if any(a.address is not None for a in args):
            st.assumptions.append(f"mock '{e.name}' does not modify objects through pointer arguments")
        n = st.call_no.get(e.name, 0) + 1
        st.call_no[e.name] = n
        ev = Event(name=e.name, index=n, args=args, order=len(st.events) + 1)
        st.events.append(ev)
        rt = info.return_type
        if rt.kind == "void":
            return Val(None, rt)
        if rt.kind == "struct":
            return Val(None, rt, struct_of=(e.name, n))
        if rt.is_numeric:
            ev.ret = self._new_symbol(st, f"ret__{e.name}_{n}", rt, f"mock:{e.name}#{n}")
            return ev.ret
        raise Unsupported(f"return type {rt.spelling} of '{e.name}'")

    # ------------------------------------------------------------- conditions (atom recording)
    def eval_cond(self, e: Expr, st: _State, guard) -> object:
        if e.kind == "cast" and e.implicit:
            return self.eval_cond(e.children[0], st, guard)
        if e.kind == "binary" and e.op in ("&&", "||"):
            if has_side_effects(e.children[1]):
                raise Unsupported(f"side effect in the right operand of '{e.op}' (short-circuit)")
            a = self.eval_cond(e.children[0], st, guard)
            g2 = z3.And(guard, a) if e.op == "&&" else z3.And(guard, z3.Not(a))
            mark = len(st.defined)
            b = self.eval_cond(e.children[1], st, g2)
            st.defined[mark:] = [z3.Implies(g2, c) for c in st.defined[mark:]]
            return z3.And(a, b) if e.op == "&&" else z3.Or(a, b)
        if e.kind == "unary" and e.op == "!":
            return z3.Not(self.eval_cond(e.children[0], st, guard))
        aid = self.atom_ids.get(id(e))
        if e.kind == "binary" and e.op in ("<", "<=", ">", ">=", "==", "!="):
            a, b = self.ev(e.children[0], st), self.ev(e.children[1], st)
            t = a.ti if a.ti.canonical == b.ti.canonical else common_type(a.ti, b.ti)
            a, b = convert(a, t), convert(b, t)
            tv = self.relation(e.op, a, b)
            if aid:
                st.atoms.append(AtomRec(aid, aid.split(".")[0], guard, a, b, e.op, tv))
            return tv
        v = self.ev(e, st)
        tv = truth(v)
        if aid:
            st.atoms.append(AtomRec(aid, aid.split(".")[0], guard, v, None, None, tv))
        return tv

    def _condition_states(self, e: Expr, st: _State):
        """Split only at short-circuit points that change the call trace."""
        if e.kind == "cast" and e.implicit:
            yield from self._condition_states(e.children[0], st)
        elif e.kind == "unary" and e.op == "!":
            for state, cond in self._condition_states(e.children[0], st):
                yield state, z3.Not(cond)
        elif e.kind == "binary" and e.op in ("&&", "||") and has_side_effects(e):
            lhs, rhs = e.children
            for state, test in self._condition_states(lhs, st):
                run_rhs = test if e.op == "&&" else z3.Not(test)
                if self.feasible(state.pc + [z3.Not(run_rhs)], state.domain):
                    skip = state.fork()
                    skip.pc.append(z3.Not(run_rhs))
                    yield skip, z3.BoolVal(e.op == "||", self.ctx)
                if self.feasible(state.pc + [run_rhs], state.domain):
                    run = state.fork()
                    run.pc.append(run_rhs)
                    yield from self._condition_states(rhs, run)
        else:
            yield st, self.eval_cond(e, st, z3.BoolVal(True, self.ctx))

    # ------------------------------------------------------------- path exploration
    def feasible(self, pc: list, domain: list) -> bool:
        s = z3.Solver(ctx=self.ctx)
        s.add(*pc, *domain)
        return s.check() == z3.sat

    def explore(self) -> list:
        paths: list = []
        init = _State()
        init.todo = list(self.ir.body)
        stack = [init]
        while stack:
            st = stack.pop()
            while True:
                if not st.todo:
                    if self.feasible(st.pc, st.domain):
                        paths.append(self._finish(st, len(paths) + 1))
                    break
                s: Stmt = st.todo.pop(0)
                if s.kind == "decl":
                    vi = self.ir.variables[s.var]
                    if vi.scope == "static_local":
                        if not vi.type.is_numeric or (s.expr is not None and vi.initial_value is None):
                            exc = Unsupported(f"non-scalar or non-constant local static '{s.var}'")
                            exc.loc = str(s.loc)
                            raise exc
                        st.assumptions.append(f"fresh process: local static '{s.var}' starts at its C initializer")
                        st.vars[s.var] = self._literal(vi.initial_value or 0, vi.type)
                        continue
                    if s.expr is not None:
                        v = self.ev(s.expr, st)                       # evaluate exactly once
                        st.vars[s.var] = v if v.ti.canonical == vi.type.canonical else convert(v, vi.type)
                elif s.kind == "expr":
                    self.ev(s.expr, st)
                elif s.kind == "return":
                    st.ret = self.ev(s.expr, st) if s.expr is not None else None
                    st.todo = []
                elif s.kind == "if":
                    forks = []
                    for state, cond in self._condition_states(s.expr, st):
                        for outcome in (True, False):
                            c = cond if outcome else z3.Not(cond)
                            pc = state.pc + [c]
                            if self.feasible(pc, state.domain):
                                f = state.fork()
                                f.pc = pc
                                f.decisions.append((s.cond_id, outcome))
                                f.todo = list(s.then if outcome else s.els) + f.todo
                                forks.append(f)
                    for f in reversed(forks):          # depth-first, TRUE branch first
                        stack.append(f)
                    break
                else:
                    exc = Unsupported(f"statement '{s.text}' ({s.note or s.kind})")
                    exc.loc = str(s.loc)
                    raise exc
            if len(paths) >= self.cfg.max_paths:
                self.truncated = True
                break
        return paths

    def _finish(self, st: _State, pid: int) -> Path:
        witness = []
        for name in st.written:                     # written-only state: give it a free initial value so the
            if name not in st.inputs:               # test can prove the function really overwrote it
                vi = self.ir.variables[name]
                st.inputs[name] = self._new_symbol(st, f"init__{name}", vi.type, f"var:{name}")
                witness.append(name)
        return Path(id=pid, decisions=st.decisions, pc=st.pc, domain=st.domain, events=st.events,
                    atoms=st.atoms, final=st.vars, written=st.written, symbols=st.symbols,
                    inputs=st.inputs, ret=st.ret, assumptions=sorted(set(st.assumptions)),
                    wraps=st.wraps, witness=witness, defined=st.defined)


# ---------------------------------------------------------------------------------------------------------
# model evaluation helpers
# ---------------------------------------------------------------------------------------------------------
def model_value(model: z3.ModelRef, v: Val):
    """Concrete python value of a Val under a model (int, float or bool-as-int)."""
    if v is None or v.z is None:
        return None
    if v.ti.kind == "float":
        bits = model.eval(z3.fpToIEEEBV(v.z, ctx=v.z.ctx), model_completion=True).as_long()
        if v.ti.bits == 32:
            return struct.unpack(">f", bits.to_bytes(4, "big"))[0]
        return struct.unpack(">d", bits.to_bytes(8, "big"))[0]
    n = model.eval(v.z, model_completion=True).as_long()
    if v.ti.signed and v.ti.kind != "bool" and n >= 1 << (v.ti.bits - 1):
        n -= 1 << v.ti.bits
    return n
