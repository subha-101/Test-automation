"""CppUTest code generation (Module 10), template based (Jinja2)."""
from __future__ import annotations

import os
import textwrap
from dataclasses import dataclass, field

import jinja2

from .config import ProjectConfig
from .ir import FunctionIR
from .mockgen import mock_plan
from .render import access_expr, c_value
from .scenarios import GenerationResult, Scenario

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")


@dataclass
class CodegenReport:
    notes: list = field(default_factory=list)      # assumptions shown by the UI
    blocked: list = field(default_factory=list)    # scenarios that could not be generated, with reason


def classify_access(ir: FunctionIR, cfg: ProjectConfig) -> list:
    """Sets VarInfo.test_access and returns issues for variables the test file cannot reach."""
    issues = []
    for v in ir.variables.values():
        if v.scope not in ("global", "static"):
            if v.scope == "static_local":
                v.test_access = "fresh process (initializer only)"
            continue
        a = access_expr(v, cfg)
        if a is None:
            v.test_access = "inaccessible"
            issues.append(f"'{v.name}' ({v.scope}) is not accessible from the test file: configure an accessor "
                          f"(access_overrides) or a test hook; scenarios that need it cannot be generated")
        else:
            v.test_access = "pointer" if a.startswith(("*", "(*")) else "direct"
    return issues


def _wrap(prefix: str, text: str, width: int = 112) -> list:
    return textwrap.wrap(text.replace("*/", "* /"), width=width - len(prefix), subsequent_indent="  ") or [""]


def build_scenario_ctx(ir: FunctionIR, cfg: ProjectConfig, sc: Scenario) -> dict:
    var = ir.variables
    inputs_txt, init_lines = [], []
    for name, value in sc.inputs.items():
        v = var[name]
        lit = c_value(value, v.type, cfg)
        if v.scope == "param":
            continue
        acc = access_expr(v, cfg)
        if acc is None:
            raise ValueError(f"variable '{name}' is inaccessible from the test file")
        init_lines.append(f"{acc} = {lit};")
        inputs_txt.append(f"{name} = {lit}")
    arg_names = []
    for pname, pti in ir.args:
        lit = c_value(sc.inputs.get(pname, 0), pti, cfg)
        init_lines.insert(0, f"{pti.spelling} {pname} = {lit};")
        arg_names.append(pname)
        inputs_txt.append(f"{pname} = {lit}")

    decls, mock_lines = mock_plan(ir, cfg, sc.events)
    mock_flat = list(decls) + ([""] if decls and mock_lines else [])
    for ln in mock_lines:
        mock_flat += ln.split("\n")

    call = f"{ir.name}({', '.join(arg_names)});"
    ret_checks = []
    rt = ir.return_type
    if rt.kind == "void":
        call_line = call
    else:
        call_line = f"{rt.spelling} ret = {call}"
        exp = c_value(sc.expected_ret, rt, cfg)
        ret_checks.append(f"CHECK_EQUAL({exp}, ret);" if rt.kind != "float"
                          else f"DOUBLES_EQUAL({exp}, ret, {cfg.float_tolerance});")

    var_checks, post_txt = [], []
    for name, value in sc.expected_vars.items():
        v = var[name]
        lit = c_value(value, v.type, cfg)
        acc = access_expr(v, cfg)
        if acc is None:
            raise ValueError(f"output '{name}' is inaccessible from the test file")
        var_checks.append(f"DOUBLES_EQUAL({lit}, {acc}, {cfg.float_tolerance});" if v.type.kind == "float"
                          else f"CHECK_EQUAL({lit}, {acc});")
        post_txt.append(f"{name} == {lit}")

    mock_txt = []
    for ev in sc.events:
        info = ir.calls[ev.name]
        bits = [f"{p} = {c_value(val, info.params[i][1] if i < len(info.params) else None, cfg)}"
                for i, (p, _t, val) in enumerate(ev.args)]
        if ev.members:
            bits += [f"returns .{m} = {c_value(x, next((ft for fn, ft in info.return_type.fields if fn == m), None), cfg)}"
                     for m, x in ev.members.items()]
        elif ev.ret_value is not None:
            bits.append(f"returns {c_value(ev.ret_value, info.return_type, cfg)}")
        mock_txt.append(f"{ev.name}({', '.join(bits)})")

    pre = _wrap(" * \\pre ", "Inputs: " + ("; ".join(inputs_txt) if inputs_txt else "none") + ".")
    if mock_txt:
        pre += _wrap(" * \\pre ", "Mocks (in call order): " + "; ".join(mock_txt) + ".")
    post = _wrap(" * \\post ", f"Return value {c_value(sc.expected_ret, rt, cfg) if rt.kind != 'void' else '(void)'}"
                 + ("; " + "; ".join(post_txt) if post_txt else "") + ".")
    brief = textwrap.wrap(sc.description.replace("*/", "* /"), width=100)
    return {
        "name": sc.name, "brief": ("\n * ".join(brief)), "pre": pre, "post": post, "init_lines": init_lines,
        "mock_lines": mock_flat, "call_line": call_line, "ret_checks": ret_checks, "var_checks": var_checks,
    }


def generate_test_file(ir: FunctionIR, cfg: ProjectConfig, result: GenerationResult) -> tuple:
    """Returns (cpp_source, CodegenReport)."""
    report = CodegenReport()
    if any(v.scope == "static_local" for v in ir.variables.values()):
        report.notes.append("function-local statics start at their C initializers; run each case in a fresh "
                            "process (CppUTest -st <group>.<test>)")
    report.notes += [f"access to file-scope variables follows the configured convention "
                     f"(static: {cfg.static_access}, pattern '{cfg.pointer_pattern}'); the accessors were NOT verified "
                     f"against your project"] if any(v.test_access == "pointer" for v in ir.variables.values()) else []
    if cfg.verify_params:
        report.notes.append("mock parameters are verified with the declared parameter names (verify_params=true)")
    if cfg.struct_return == "pointer":
        report.notes.append("struct return values use the project convention .andReturnValue(&local)")
    ctxs = []
    for sc in result.scenarios:
        try:
            ctxs.append(build_scenario_ctx(ir, cfg, sc))
        except Exception as exc:   # report, never silently drop
            report.blocked.append((sc.name, str(exc)))
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(TEMPLATE_DIR), trim_blocks=True, lstrip_blocks=True,
                             keep_trailing_newline=True, undefined=jinja2.StrictUndefined)
    text = env.get_template("cpputest_test.cpp.j2").render(
        function=ir.name, group=cfg.test_group or ir.name, includes=cfg.includes, strategies=", ".join(x for x in ("branch", "condition", "boundary") if x in result.strategies),
        scenarios=ctxs, emit_group=cfg.emit_test_group)
    # collapse the blank lines the template leaves when a section is empty
    out, blank = [], 0
    for ln in text.split("\n"):
        blank = blank + 1 if not ln.strip() else 0
        if blank <= 1:
            out.append(ln.rstrip())
    return "\n".join(out).rstrip() + "\n", report
