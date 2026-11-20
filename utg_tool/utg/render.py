"""Rendering of concrete values as C literals and of variable access expressions for the test file."""
from __future__ import annotations

import math
from typing import Optional

from .config import ProjectConfig
from .ir import TypeInfo, VarInfo


def float_literal(x: float, bits: int = 32) -> str:
    if math.isnan(x) or math.isinf(x):
        raise ValueError("non-finite float literal")
    if x == 0.0:
        return "-0.0f" if math.copysign(1.0, x) < 0 else "0.0f"
    s = format(x, ".9g" if bits == 32 else ".17g")
    if not any(ch in s for ch in ".eE"):
        s += ".0"
    return s + ("f" if bits == 32 else "")


def c_value(value, ti: Optional[TypeInfo], cfg: ProjectConfig) -> str:
    """Render `value` for type `ti`: enumerator name, TRUE/FALSE for boolean typedefs, float / int literal."""
    if ti is None:
        return float_literal(value) if isinstance(value, float) else str(value)
    if ti.kind == "float":
        return float_literal(float(value), ti.bits)
    if ti.kind == "enum":
        for name, v in ti.enumerators.items():
            if v == value:
                return name
        return str(value)
    if ti.spelling in cfg.boolean_types and value in (0, 1):
        return "TRUE" if value == 1 else "FALSE"
    return str(int(value))


def access_expr(var: VarInfo, cfg: ProjectConfig) -> Optional[str]:
    """How the generated test reads/writes a file-scope variable; None -> inaccessible."""
    rule = cfg.access_overrides.get(var.name)
    if rule == "inaccessible":
        return None
    if rule:
        return rule.format(name=var.name)
    mode = cfg.static_access if var.scope == "static" else cfg.global_access
    if mode == "pointer":
        return cfg.pointer_pattern.format(name=var.name)
    if mode == "direct":
        return var.name
    return None
