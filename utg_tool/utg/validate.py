"""Validation engine (Module 12).

Four *distinct* levels, never conflated:   generated -> statically validated -> compiled -> executed.
Coverage is reported separately as  PLANNED (derived from the solver models)  vs  MEASURED (gcov of the real
source executing the generated tests).

The CppUTest *harness* built here (accessor pointers + mock implementations + main) is a tool-owned
validation aid derived from the IR and the configuration; it is NOT part of the generated test file and does
not replace the project's own test infrastructure.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from .config import ProjectConfig
from .ir import FunctionIR
from .render import access_expr
from .scenarios import GenerationResult

LEVELS = ["generated", "statically validated", "compiled", "executed"]


@dataclass
class StaticFinding:
    severity: str          # error | warning
    message: str


@dataclass
class ValidationReport:
    level: str = "generated"                      # highest level reached
    static: list = field(default_factory=list)    # [StaticFinding]
    compile_log: str = ""
    compiled: Optional[bool] = None               # None = not attempted
    run_log: str = ""
    executed: Optional[bool] = None
    tests_run: int = 0
    tests_failed: int = 0
    failed_tests: list = field(default_factory=list)
    measured: Optional[dict] = None               # gcov results
    skipped_reason: str = ""


# ---------------------------------------------------------------------------------------------------------
# static validation
# ---------------------------------------------------------------------------------------------------------
def static_validate(ir: FunctionIR, cfg: ProjectConfig, result: GenerationResult, code: str) -> list:
    f: list = []
    names = re.findall(r"^TEST\(\s*\w+\s*,\s*(\w+)\s*\)", code, flags=re.M)
    for n in sorted({n for n in names if names.count(n) > 1}):
        f.append(StaticFinding("error", f"duplicate test name '{n}'"))
    if len(names) != len(result.scenarios):
        f.append(StaticFinding("error", f"{len(result.scenarios)} scenarios but {len(names)} TEST() blocks "
                                        "(some scenarios were blocked)"))
    for sc in result.scenarios:
        for ev in sc.events:
            info = ir.calls.get(ev.name)
            if info is None:
                f.append(StaticFinding("error", f"{sc.name}: mock '{ev.name}' is not a dependency of {ir.name}"))
                continue
            if len(ev.args) != len(info.params):
                f.append(StaticFinding("error", f"{sc.name}: {ev.name} expects {len(info.params)} parameters"))
        for n in sc.inputs:
            v = ir.variables[n]
            if v.scope in ("global", "static") and access_expr(v, cfg) is None:
                f.append(StaticFinding("error", f"{sc.name}: '{n}' is not accessible from the test file"))
        if "mock().checkExpectations();" not in code:
            f.append(StaticFinding("error", "mock().checkExpectations() missing"))
    for n, v in ir.variables.items():
        if v.scope == "static" and cfg.static_access == "direct":
            f.append(StaticFinding("warning", f"'{n}' is static: direct access is only valid if the test file "
                                              "#includes the C file"))
    pointer_vars = [v.name for v in ir.variables.values() if v.test_access == "pointer"]
    if pointer_vars:
        f.append(StaticFinding("warning", f"{len(pointer_vars)} accessor pointer(s) ({cfg.pointer_pattern}) are assumed, "
                                          "not verified against the project"))
    for u in ir.unsupported:
        f.append(StaticFinding("warning", f"unsupported construct at {u['loc']}: {u['reason']}"))
    return f


# ---------------------------------------------------------------------------------------------------------
# harness / compile / run
# ---------------------------------------------------------------------------------------------------------
def _find_cpputest(cfg: ProjectConfig) -> Optional[str]:
    for cand in (getattr(cfg, "cpputest_home", ""), os.environ.get("CPPUTEST_HOME", ""),
                 "/home/claude/third_party/cpputest_install", "/usr", "/usr/local"):
        if cand and os.path.isfile(os.path.join(cand, "include", "CppUTest", "TestHarness.h")):
            return cand
    return None


def _lib_dir(home: str) -> Optional[str]:
    for d in ("lib", "lib64", "lib/x86_64-linux-gnu"):
        p = os.path.join(home, d)
        if os.path.isfile(os.path.join(p, "libCppUTest.a")) or os.path.isfile(os.path.join(p, "libCppUTest.so")):
            return p
    return None


def build_harness(ir: FunctionIR, cfg: ProjectConfig, test_file: str) -> str:
    L = ['#include "CppUTest/CommandLineTestRunner.h"', '#include "CppUTest/TestHarness.h"',
         '#include "CppUTestExt/MockSupport.h"', 'extern "C" {']
    L += [f'#include "{os.path.abspath(h)}"' for h in cfg.headers]
    if cfg.prelude_file:
        L.append(f'#include "{os.path.abspath(cfg.prelude_file)}"')
    L += [f'#include "{os.path.abspath(cfg.source_file)}"', "}", ""]
    L.append("/* accessor pointers (convention from the project configuration) */")
    for v in ir.variables.values():
        if v.scope in ("global", "static") and v.test_access == "pointer":
            ident = access_expr(v, cfg).lstrip("*")
            L.append(f"static {v.type.spelling} * const {ident} = &{v.name};")
    L += ["", "/* mock implementations derived from the declarations */"]
    for c in ir.calls.values():
        if not c.requires_mock:
            continue
        params = ", ".join(f"{t.spelling} {n}" for n, t in c.params) or "void"
        L.append(f"{c.return_type.spelling} {c.name}({params})")
        L.append("{")
        chain = f'mock().actualCall("{c.name}")'
        if cfg.verify_params:
            for n, t in c.params:
                cast = f"({cfg.bool_param_cast})" if t.spelling in cfg.boolean_types and cfg.bool_param_cast else "(int)" if t.bits <= 16 else ""
                chain += f'.withParameter("{n}", {cast}{n})'
        if c.return_type.kind == "void":
            L.append(f"    {chain};")
        elif c.return_type.kind == "struct":
            L.append(f"    return *static_cast<{c.return_type.spelling}*>({chain}.returnPointerValue());")
        elif c.return_type.kind == "float":
            L.append(f"    return ({c.return_type.spelling}){chain}.returnDoubleValue();")
        else:
            L.append(f"    return ({c.return_type.spelling}){chain}.returnLongIntValue();")
        L += ["}", ""]
    L += [f'#include "{os.path.abspath(test_file)}"', "",
          "int main(int argc, char** argv)", "{", "    return CommandLineTestRunner::RunAllTests(argc, argv);", "}", ""]
    return "\n".join(L)


def compile_and_run(ir: FunctionIR, cfg: ProjectConfig, code: str, workdir: str,
                    measure_coverage: bool = True) -> ValidationReport:
    rep = ValidationReport()
    workdir = os.path.abspath(workdir)          # subprocesses run with cwd=workdir: never pass relative paths
    os.makedirs(workdir, exist_ok=True)
    test_file = os.path.join(workdir, f"test_{ir.name}.cpp")
    with open(test_file, "w") as fh:
        fh.write(code)
    home = _find_cpputest(cfg)
    gxx = shutil.which("g++")
    if not home or not gxx or not _lib_dir(home):
        rep.skipped_reason = ("CppUTest or g++ not found (set CPPUTEST_HOME / cpputest_home): "
                              "compilation and execution were NOT performed")
        return rep
    harness = os.path.join(workdir, "harness.cpp")
    with open(harness, "w") as fh:
        fh.write(build_harness(ir, cfg, test_file))
    exe = os.path.join(workdir, "run_tests")
    cmd = [gxx, "-std=c++14", "-O0", "-g", "-fno-inline", "-w", "-I" + os.path.join(home, "include")]
    cmd += [f"-I{os.path.abspath(d)}" for d in cfg.include_dirs] + [f"-D{d}" for d in cfg.defines]
    if measure_coverage:
        cmd += ["--coverage"]
    cmd += [harness, "-L" + _lib_dir(home), "-lCppUTestExt", "-lCppUTest", "-o", exe]
    for fn in os.listdir(workdir):
        if fn.endswith((".gcda", ".gcno")):
            os.remove(os.path.join(workdir, fn))
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=workdir)
    rep.compile_log = (p.stdout + p.stderr).strip()
    rep.compiled = p.returncode == 0
    if not rep.compiled:
        return rep
    r = subprocess.run([exe, "-v"], capture_output=True, text=True, cwd=workdir, timeout=120)
    rep.run_log = (r.stdout + r.stderr).strip()
    m = re.search(r"OK \((\d+) tests", rep.run_log)
    if m:
        rep.tests_run, rep.tests_failed, rep.executed = int(m.group(1)), 0, True
    else:
        m = re.search(r"Errors \((\d+) failures, (\d+) tests", rep.run_log)
        rep.executed = False
        if m:
            rep.tests_failed, rep.tests_run = int(m.group(1)), int(m.group(2))
        rep.failed_tests = sorted(set(re.findall(r"^TEST\((\w+), (\w+)\)\s*-", rep.run_log, flags=re.M)))
        rep.failed_tests = re.findall(r"(Testcase_\w+)", "\n".join(
            l for l in rep.run_log.splitlines() if "Failure in" in l))
    if measure_coverage and rep.compiled:
        rep.measured = _gcov(ir, cfg, workdir)
    return rep


def _gcov(ir: FunctionIR, cfg: ProjectConfig, workdir: str) -> Optional[dict]:
    """Measured line/branch coverage of the function under test (GCC gcov on the real C source)."""
    if not shutil.which("gcov"):
        return None
    gcda = next((f for f in os.listdir(workdir) if f.endswith(".gcda")), None)
    if gcda is None:
        return None
    subprocess.run(["gcov", "-b", "-c", gcda], capture_output=True, text=True, cwd=workdir)
    gc = os.path.join(workdir, os.path.basename(cfg.source_file) + ".gcov")
    if not os.path.isfile(gc):
        return None
    first, last = ir.loc.line, ir.loc.line
    # function extent: from its first line to the last statement line recorded in the IR
    def max_line(stmts):
        m = 0
        for s in stmts:
            m = max(m, s.loc.line, max_line(s.then), max_line(s.els))
        return m
    last = max_line(ir.body) + 1
    lines_total = lines_hit = br_total = br_taken = 0
    cur = None
    for raw in open(gc, errors="replace"):
        m = re.match(r"\s*([\d#=\-*]+)\*?:\s*(\d+):", raw)
        if m:
            cnt, ln = m.group(1), int(m.group(2))
            cur = ln if first <= ln <= last and cnt not in ("-",) else None
            if cur is not None and ln > 0:
                lines_total += 1
                if cnt.rstrip("*") not in ("#####", "====="):
                    lines_hit += 1
            continue
        b = re.match(r"branch\s+\d+ (taken (\d+)|never executed)", raw)
        if b and cur is not None:
            br_total += 1
            if b.group(2) and int(b.group(2)) > 0:
                br_taken += 1
    return {"lines_total": lines_total, "lines_hit": lines_hit, "branches_total": br_total,
            "branches_taken": br_taken, "tool": "gcov (GCC), -O0, whole source function range",
            "gcov_file": gc}


def overall_level(rep: ValidationReport) -> str:
    if rep.executed:
        return "executed"
    if rep.compiled:
        return "compiled"
    if not any(f.severity == "error" for f in rep.static):
        return "statically validated"
    return "generated"
