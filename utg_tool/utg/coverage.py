"""Coverage and traceability (Module 11).

PLANNED coverage is derived from the solver models of the generated scenarios (what the execution model says
each scenario exercises).  MEASURED coverage only exists after real execution (see validate.py / gcov).
The two are always reported under separate names.
"""
from __future__ import annotations

from .ir import FunctionIR
from .scenarios import GenerationResult


def decision_matrix(ir: FunctionIR, res: GenerationResult) -> list:
    rows = []
    for sc in res.scenarios:
        taken = dict(sc.decisions)
        rows.append({"test": sc.name, **{c.id: ("TRUE" if taken[c.id] else "FALSE") if c.id in taken else "-"
                                         for c in ir.conditions}})
    return rows


def atom_matrix(ir: FunctionIR, res: GenerationResult) -> list:
    rows = []
    for sc in res.scenarios:
        row = {"test": sc.name}
        for c in ir.conditions:
            for a in c.atoms:
                row[a.id] = ("T" if ("O", a.id, "true") in sc.covers else
                             "F" if ("O", a.id, "false") in sc.covers else "-")
        rows.append(row)
    return rows


def boundary_table(res: GenerationResult) -> list:
    out = []
    for t in res.targets:
        if t.key[0] in ("R", "W"):
            who = [sc.name for sc in res.scenarios if t.key in sc.covers]
            out.append({"target": t.text, "covered_by": ", ".join(who) or "NOT COVERED"})
    return out


def summary(res: GenerationResult) -> dict:
    cov = set().union(*[sc.covers for sc in res.scenarios]) if res.scenarios else set()
    by_kind: dict = {}
    for t in res.targets:
        k = by_kind.setdefault(t.kind, [0, 0])
        k[1] += 1
        k[0] += t.key in cov
    return {"basis": "PLANNED (derived from solver models, not from execution)",
            "targets": {k: f"{a}/{b}" for k, (a, b) in by_kind.items()},
            "uncovered": [(t.text, why) for t, why in res.uncovered],
            "scenarios": len(res.scenarios), "feasible_paths": res.path_count, "truncated": res.truncated}
