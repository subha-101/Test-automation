"""Deterministic Z3 solving (Module 7).

A scenario needs *concrete, readable and reproducible* inputs, not whatever model Z3 happens to return
(Z3's arbitrary models differ between calls in one process).  After the path constraints are known to be
satisfiable, every free symbol (sorted by name) is pinned to a value chosen by a fixed procedure:

  1. soft preferences (no incidental wrap-around, written-only state starts different from its result)
  2. the first value of the configurable pool (0, 1, 2, ... / 0.0, 1.0, ...) that keeps the problem satisfiable
  3. values relative to already pinned ones: p+1, p-1 and the adjacent representable float ("epsilon")
  4. last resort: the unique minimiser of the value's bit pattern (z3.Optimize) - still deterministic

Every symbol therefore ends up explicitly pinned: same IR + config -> same values, run after run.
"""
from __future__ import annotations

import struct
from typing import Optional

import z3

from .config import ProjectConfig
from .ir import TypeInfo
from .symexec import Val, bv_const, fp_sort


def next_f32(x: float, up: bool) -> float:
    if x == 0.0:
        return 1.401298464324817e-45 if up else -1.401298464324817e-45
    b = struct.unpack(">I", struct.pack(">f", x))[0]
    b += 1 if (x > 0) == up else -1
    return struct.unpack(">f", struct.pack(">I", b))[0]


def _range(ti: TypeInfo) -> tuple:
    return (-(1 << (ti.bits - 1)), (1 << (ti.bits - 1)) - 1) if ti.signed else (0, (1 << ti.bits) - 1)


def _candidates(ti: TypeInfo, cfg: ProjectConfig, pinned: list) -> list:
    """Ordered python candidate values for a symbol of type `ti`."""
    seen, out = set(), []

    def add(x) -> None:
        key = (float(x).hex() if ti.kind == "float" else int(x))
        if key not in seen:
            seen.add(key)
            out.append(x)

    if ti.kind == "float":
        for x in cfg.float_pool:
            add(float(x))
        ps = sorted(set(pinned))
        for p in ps:
            add(p + 1.0)
            add(p - 1.0)
        for i, a in enumerate(ps):                       # readable values inside open intervals
            for b in ps[i + 1:]:
                add((a + b) / 2.0)
        for p in ps:
            add(p / 2.0)
        for p in ps:                                     # epsilon neighbours: last, they are rarely good test values
            add(next_f32(p, True))
            add(next_f32(p, False))
        return out
    if ti.kind == "enum" and ti.enumerators:
        return sorted(set(ti.enumerators.values()))
    lo, hi = _range(ti)
    pool = list(cfg.int_pool) + ([-1] if ti.signed else [])
    for x in pool:
        if lo <= x <= hi:
            add(x)
    for p in sorted(set(pinned)):
        for x in (p + 1, p - 1):
            if lo <= x <= hi:
                add(x)
    return out


def _const(v: Val, x):
    ctx = v.z.ctx
    return z3.FPVal(float(x), fp_sort(v.ti, ctx), ctx=ctx) if v.ti.kind == "float" else bv_const(int(x), v.ti.bits, ctx)


def _pin(v: Val, x):
    c = _const(v, x)
    # exact bit pattern: fpEQ would accept -0.0 for 0.0
    return z3.fpToIEEEBV(v.z, ctx=v.z.ctx) == z3.fpToIEEEBV(c, ctx=v.z.ctx) if v.ti.kind == "float" else v.z == c


def solve(constraints: list, symbols: dict, cfg: ProjectConfig, ctx: z3.Context,
          soft: Optional[list] = None) -> Optional[z3.ModelRef]:
    """Return a fully pinned, deterministic model satisfying `constraints`; None if unsatisfiable."""
    base = z3.Solver(ctx=ctx)
    base.add(*constraints)
    if base.check() != z3.sat:
        return None
    fixed: list = []
    for c in (soft or []):                       # preferences, kept in order while they stay satisfiable
        t = z3.Solver(ctx=ctx)
        t.add(*constraints, *fixed, c)
        if t.check() == z3.sat:
            fixed.append(c)
    pinned = {"float": [], "int": []}
    for name in sorted(symbols):
        val: Val = symbols[name][0] if isinstance(symbols[name], tuple) else symbols[name]
        bucket = pinned["float" if val.ti.kind == "float" else "int"]
        chosen = None
        for x in _candidates(val.ti, cfg, bucket):
            s = z3.Solver(ctx=ctx)
            s.add(*constraints, *fixed, _pin(val, x))
            if s.check() == z3.sat:
                chosen = x
                break
        if chosen is not None:
            fixed.append(_pin(val, chosen))
            bucket.append(chosen)
            continue
        o = z3.Optimize(ctx=ctx)                 # deterministic last resort: unique minimal bit pattern
        o.add(*constraints, *fixed)
        bits_expr = z3.fpToIEEEBV(val.z, ctx=ctx) if val.ti.kind == "float" else val.z
        o.minimize(bits_expr)
        assert o.check() == z3.sat
        m = o.model()
        fixed.append(bits_expr == m.eval(bits_expr, model_completion=True))
    final = z3.Solver(ctx=ctx)
    final.add(*constraints, *fixed)
    assert final.check() == z3.sat
    return final.model()
