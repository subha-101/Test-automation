"""CLI:  python -m utg <project.json> [--function NAME] [--strategy branch condition boundary] [--out DIR] [--validate]"""
import argparse, json, os, sys

from .config import ProjectConfig
from .coverage import summary
from .parser import CParser
from .pipeline import analyse_function, generate
from .validate import compile_and_run, overall_level, static_validate


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="utg", description="Deterministic CppUTest generator for C functions (no AI)")
    ap.add_argument("project")
    ap.add_argument("--function")
    ap.add_argument("--strategy", nargs="+", default=["branch", "condition", "boundary"])
    ap.add_argument("--out", default="utg_out")
    ap.add_argument("--validate", action="store_true", help="compile and run the tests against the real source")
    a = ap.parse_args(argv)
    cfg = ProjectConfig.load(a.project)
    parser = CParser(cfg)
    parser.parse()
    funcs = parser.list_functions()
    name = a.function or (funcs[0]["name"] if len(funcs) == 1 else None)
    if not name:
        print("functions:", ", ".join(f["name"] for f in funcs)); return 2
    an = analyse_function(cfg, name, parser)
    os.makedirs(a.out, exist_ok=True)
    open(os.path.join(a.out, f"{name}.ir.json"), "w").write(an.ir.to_json())
    blocking = [u for u in an.ir.unsupported]
    if blocking:
        print("UNSUPPORTED / UNRESOLVED:"); [print(" -", u["loc"], u["reason"]) for u in blocking]
    g = generate(cfg, an, a.strategy)
    path = os.path.join(a.out, f"test_{name}.cpp")
    open(path, "w").write(g.code)
    print(f"{len(g.result.scenarios)} scenarios -> {path}")
    print(json.dumps(summary(g.result), indent=2))
    st = static_validate(an.ir, cfg, g.result, g.code)
    for f in st: print(f"[{f.severity}] {f.message}")
    if a.validate:
        rep = compile_and_run(an.ir, cfg, g.code, os.path.join(a.out, "build")); rep.static = st
        print("validation level:", overall_level(rep), rep.skipped_reason or "")
        print("compiled:", rep.compiled, "executed:", rep.executed, f"tests {rep.tests_run}, failed {rep.tests_failed}")
        print("MEASURED coverage (gcov):", rep.measured)
        if rep.compiled is False: print(rep.compile_log)
        return 0 if rep.executed else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
