"""Mock generator (Module 9): CppUTest mock expectations for the calls executed in ONE scenario.

Only calls that the execution model actually performed on the scenario's path are emitted - never
expectations for calls that do not happen. Return values come from the scenario model. Parameter
checks and strict call ordering are optional.
"""
from __future__ import annotations

from .config import ProjectConfig
from .ir import FunctionIR, TypeInfo
from .render import access_expr, c_value


class MockGenError(Exception):
    pass


def mock_plan(ir: FunctionIR, cfg: ProjectConfig, events: list) -> tuple:
    """Returns (declaration_lines, expectation_lines) for the scenario's call events."""
    decls: list = []
    lines: list = []
    seen: dict = {}
    if cfg.strict_order and len(events) > 1:
        lines.append("mock().strictOrder();")
    for ev in events:
        info = ir.calls[ev.name]
        chain = [f'mock().expectOneCall("{ev.name}")']
        if cfg.verify_params:
            for pname, ptype, value in ev.args:
                ti = info.params[[p[0] for p in info.params].index(pname)][1] if pname in [p[0] for p in info.params] else None
                if ti is not None and ti.kind == "pointer":
                    acc = access_expr(ir.variables[value], cfg)
                    if acc is None:
                        raise MockGenError(f"address of '{value}' is inaccessible from the test file")
                    chain.append(f'.withConstPointerParameter("{pname}", static_cast<const void*>(&({acc})))')
                    continue
                lit = c_value(value, ti, cfg)
                if ti is not None and ti.spelling in cfg.boolean_types and cfg.bool_param_cast:
                    lit = f"({cfg.bool_param_cast}){lit}"     # TRUE=(!0) is bool, FALSE=0 is int in C++
                chain.append(f'.withParameter("{pname}", {lit})')
        rt: TypeInfo = info.return_type
        if rt.kind == "struct":
            seen[ev.name] = seen.get(ev.name, 0) + 1
            var = f"{ev.name}_ret" + (f"_{seen[ev.name]}" if seen[ev.name] > 1 else "")
            inits = []
            for fname, fti in rt.fields:
                if fti.kind == "struct":
                    raise MockGenError(f"nested struct member '{fname}' in {rt.spelling} is not supported")
                inits.append(c_value(ev.members.get(fname, 0.0 if fti.kind == "float" else 0), fti, cfg))
            decls.append(f"{rt.spelling} {var} = {{{', '.join(inits)}}};")
            if cfg.struct_return == "pointer":
                chain.append(f".andReturnValue(&{var})")
            else:
                raise MockGenError(f"struct_return convention '{cfg.struct_return}' not supported")
        elif rt.is_numeric:
            lit = c_value(ev.ret_value, rt, cfg)
            if rt.kind == "bool" or rt.spelling in cfg.boolean_types:
                # The harness reads integral returns as long; CppUTest does not coerce stored bools.
                lit = f"static_cast<long>({lit})"
            chain.append(f".andReturnValue({lit})")
        elif rt.kind != "void":
            raise MockGenError(f"return type {rt.spelling} of {ev.name} is not supported")
        separator = "\n      " if cfg.verify_params else ""
        lines.append(separator.join(chain) + ";")
    return decls, lines
