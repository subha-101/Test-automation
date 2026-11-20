"""Streamlit GUI - run with:  streamlit run app.py"""
import os
import tempfile

import pandas as pd
import streamlit as st

from utg.config import ProjectConfig
from utg.coverage import atom_matrix, boundary_table, decision_matrix, summary
from utg.parser import CParser
from utg.pipeline import analyse_function, generate
from utg.scenarios import STRATEGIES
from utg.validate import compile_and_run, overall_level, static_validate

ROOT = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.join(ROOT, "examples", "benchmark", "project.json")

st.set_page_config(page_title="Deterministic C unit-test generator", layout="wide")
S = st.session_state
PAGES = ["1 File upload", "2 Function selection", "3 Function analysis", "4 Scenario generation",
         "5 Code generation", "6 Validation and coverage"]
page = st.sidebar.radio("Page", PAGES)
st.sidebar.caption("Deterministic: Clang AST + Z3 + Jinja2. No AI / LLM / external API.")


def _cfg() -> ProjectConfig:
    if "cfg" not in S:
        st.warning("Load a project on page 1 first.")
        st.stop()
    return S.cfg


# ------------------------------------------------------------------------------------------------ page 1
if page == PAGES[0]:
    st.header("File upload")
    if st.button("Load the benchmark example (rc_lsout11_out_250us)"):
        S.cfg = ProjectConfig.load(BENCH)
        for k in ("parser", "analysis", "generated", "validation", "fn"):
            S.pop(k, None)
        st.success("Benchmark project loaded.")
    st.subheader("Or upload your own files")
    c = st.file_uploader("C source file", type=["c"])
    hs = st.file_uploader("Header files (in include order)", type=["h"], accept_multiple_files=True)
    prelude = st.file_uploader("Optional prelude header (declarations the source relies on but does not declare)", type=["h"])
    ref = st.file_uploader("Optional existing CppUTest file (formatting reference - shown only, Phase 1)", type=["cpp", "cc", "c"])
    incs = st.text_input("Include directories (comma separated)")
    defs = st.text_input("Definitions (comma separated, e.g. UNIT_TESTING)")
    flags = st.text_input("Extra compiler flags")
    target = st.text_input("Clang --target (empty = host ABI)", "armv7m-none-eabi")
    if st.button("Create project from uploads") and c:
        d = tempfile.mkdtemp(prefix="utg_")
        def save(f):
            p = os.path.join(d, f.name); open(p, "wb").write(f.getvalue()); return p
        cfg = ProjectConfig(source_file=save(c), headers=[save(h) for h in hs],
                            prelude_file=save(prelude) if prelude else "",
                            include_dirs=[x.strip() for x in incs.split(",") if x.strip()] + [d],
                            defines=[x.strip() for x in defs.split(",") if x.strip()],
                            extra_flags=flags.split(), target=target,
                            includes=['#include "CppUTest/TestHarness.h"', '#include "CppUTestExt/MockSupport.h"'])
        S.cfg = cfg
        for k in ("parser", "analysis", "generated", "validation", "fn"):
            S.pop(k, None)
        st.success("Project created.")
    if "cfg" in S:
        st.subheader("Current project configuration")
        st.json(S.cfg.__dict__, expanded=False)
        for name, path in [("source", S.cfg.source_file)] + [("header", h) for h in S.cfg.headers]:
            with st.expander(f"{name}: {os.path.basename(path)}"):
                st.code(open(path, errors="replace").read(), language="c")
        if ref:
            with st.expander("reference test file"):
                st.code(ref.getvalue().decode(errors="replace"), language="cpp")

# ------------------------------------------------------------------------------------------------ page 2
elif page == PAGES[1]:
    st.header("Function selection")
    cfg = _cfg()
    if "parser" not in S:
        S.parser = CParser(cfg)
        S.parser.parse()
    funcs = S.parser.list_functions()
    for d in S.parser.diagnostics:
        (st.error if d["severity"] in ("error", "fatal") else st.warning)(f"{d['severity']}: {d['message']} ({d['loc']})")
    st.dataframe(pd.DataFrame(funcs), use_container_width=True)
    if funcs:
        S.fn = st.selectbox("Function to test", [f["name"] for f in funcs])
        if st.button("Analyse"):
            S.analysis = analyse_function(cfg, S.fn, S.parser)
            S.pop("generated", None); S.pop("validation", None)
            st.success("Analysed - see page 3.")

# ------------------------------------------------------------------------------------------------ page 3
elif page == PAGES[2]:
    st.header("Function analysis")
    cfg = _cfg()
    if "analysis" not in S:
        st.info("Select and analyse a function on page 2."); st.stop()
    a = S.analysis; ir = a.ir
    st.code(ir.signature)
    for u in ir.unsupported:
        st.error(f"UNSUPPORTED at {u['loc']}: {u['reason']} - {u['effect']}")
    for i in a.access_issues:
        st.warning(i)
    st.subheader("Variables")
    st.dataframe(pd.DataFrame([{"name": v.name, "type": v.type.spelling, "resolved": v.type.canonical,
                                "bits": v.type.bits, "scope": v.scope, "role": v.role, "read": v.read, "written": v.written,
                                "read before write": v.read_before_write, "conditionally written": v.conditionally_written,
                                "test access": v.test_access} for v in ir.variables.values()]), use_container_width=True)
    st.subheader("Internal function calls")
    st.dataframe(pd.DataFrame([{"name": c.name, "returns": c.return_type.spelling,
                                "params": ", ".join(f"{t.spelling} {n}" for n, t in c.params), "call sites": ", ".join(map(str, c.call_sites)),
                                "conditional": c.conditional, "needs mock": c.requires_mock, "return used": c.return_used,
                                "members used": ", ".join(c.result_members)} for c in ir.calls.values()]), use_container_width=True)
    st.subheader("Conditions")
    st.dataframe(pd.DataFrame([{"id": c.id, "expression": c.text, "line": c.loc.line, "logical ops": " ".join(c.logical_ops),
                                "atoms": " | ".join(f"{x.id}: {x.text}" for x in c.atoms),
                                "TRUE branch": "; ".join(c.true_branch), "FALSE branch": "; ".join(c.false_branch)} for c in ir.conditions]),
                 use_container_width=True)
    st.subheader("Sequential dependencies (definitions reaching each condition)")
    st.dataframe(pd.DataFrame([{"condition": u.cond_id, "variable": u.var, "modified earlier": u.modified_before,
                                "reaching definitions": " | ".join(u.defs)} for u in ir.cond_uses]), use_container_width=True)
    st.subheader("Variable dependencies")
    st.dataframe(pd.DataFrame([{"target": d.target, "depends on": ", ".join(d.sources), "kind": d.kind, "statement": d.stmt}
                               for d in ir.var_dependencies]), use_container_width=True)
    st.subheader("Control flow")
    st.caption(f"{len(a.cfg_graph.nodes)} nodes, {a.cfg_graph.syntactic_paths()} syntactic paths (feasibility is decided later by Z3)")
    st.graphviz_chart(a.cfg_graph.to_dot())
    with st.expander("Function IR (JSON)"):
        st.code(ir.to_json(), language="json")

# ------------------------------------------------------------------------------------------------ page 4
elif page == PAGES[3]:
    st.header("Test scenario generation")
    cfg = _cfg()
    if "analysis" not in S:
        st.info("Analyse a function first."); st.stop()
    chosen = st.multiselect("Coverage strategies", list(STRATEGIES), default=list(STRATEGIES))
    st.caption("MC/DC, switch, loops and state-transition testing are planned for phase 3 and are not offered yet.")
    if st.button("Generate scenarios") and chosen:
        S.generated = generate(cfg, S.analysis, chosen)
        S.pop("validation", None)
    if "generated" in S:
        g = S.generated; res = g.result
        keep = []
        st.write(f"**{len(res.scenarios)} scenarios** from {res.path_count} feasible paths")
        for sc in res.scenarios:
            with st.expander(f"{sc.name} - {sc.description}"):
                st.write("Inputs", sc.inputs)
                st.write("Mock calls (order)", [{"call": e.name, "args": {p: v for p, _t, v in e.args},
                                                 "returns": e.members or e.ret_value} for e in sc.events])
                st.write("Expected variables", sc.expected_vars, "Expected return", sc.expected_ret)
                st.write("Conditions covered", sorted(f"{k[0]}:{k[1]}:{k[2]}" for k in sc.covers))
                if sc.assumptions:
                    st.caption("Assumptions: " + "; ".join(sc.assumptions))
                if not st.checkbox("remove this scenario", key=f"rm_{sc.name}"):
                    keep.append(sc)
        if len(keep) != len(res.scenarios) and st.button("Apply removals"):
            res.scenarios = keep
            from utg.codegen import generate_test_file
            g.code, g.report = generate_test_file(S.analysis.ir, cfg, res)
            st.success("Removed. Coverage tables on page 6 now reflect the reduced set.")
        st.caption("Editing/adding scenarios needs concrete re-execution of the model and is planned for phase 2; "
                   "the generated code on page 5 is fully editable meanwhile.")
        for t, why in res.uncovered:
            st.info(f"Not covered: {t.text} - {why}")

# ------------------------------------------------------------------------------------------------ page 5
elif page == PAGES[4]:
    st.header("Code generation")
    if "generated" not in S:
        st.info("Generate scenarios on page 4."); st.stop()
    g = S.generated
    for n in g.report.notes:
        st.warning(n)
    for name, why in g.report.blocked:
        st.error(f"{name} was not generated: {why}")
    S.edited_code = st.text_area("Generated CppUTest (editable)", value=S.get("edited_code") if S.get("edited_code") and S.get("edited_for") == g.code else g.code, height=600)
    S.edited_for = g.code
    st.download_button("Download test file", S.edited_code, file_name=f"test_{S.analysis.ir.name}.cpp")

# ------------------------------------------------------------------------------------------------ page 6
else:
    st.header("Validation and coverage")
    cfg = _cfg()
    if "generated" not in S:
        st.info("Generate scenarios first."); st.stop()
    g = S.generated; ir = S.analysis.ir
    code = S.get("edited_code") or g.code
    if st.button("Run static validation + compile + execute (CppUTest, gcov)"):
        rep = compile_and_run(ir, cfg, code, tempfile.mkdtemp(prefix="utg_run_"))
        rep.static = static_validate(ir, cfg, g.result, code)
        S.validation = rep
    st.subheader("Status")
    levels = ["generated", "statically validated", "compiled", "executed"]
    cur = overall_level(S.validation) if "validation" in S else "generated"
    st.write(" -> ".join(f"**{x}**" if levels.index(x) <= levels.index(cur) else x for x in levels))
    if "validation" in S:
        v = S.validation
        if v.skipped_reason:
            st.warning(v.skipped_reason)
        for f in v.static:
            (st.error if f.severity == "error" else st.info)(f.message)
        if v.compiled is False:
            st.error("Compilation failed"); st.code(v.compile_log)
        if v.compiled:
            (st.success if v.executed else st.error)(f"Executed: {v.tests_run} tests, {v.tests_failed} failed")
            with st.expander("run log"):
                st.code(v.run_log)
        if v.measured:
            m = v.measured
            st.subheader("MEASURED coverage (gcov on the real source)")
            st.write(f"lines {m['lines_hit']}/{m['lines_total']}, branches {m['branches_taken']}/{m['branches_total']}")
    st.subheader("PLANNED coverage (derived from solver models - not from execution)")
    st.json(summary(g.result))
    st.write("Decision matrix"); st.dataframe(pd.DataFrame(decision_matrix(ir, g.result)), use_container_width=True)
    st.write("Atomic condition matrix"); st.dataframe(pd.DataFrame(atom_matrix(ir, g.result)), use_container_width=True)
    st.write("Boundary / wrap-around scenarios"); st.dataframe(pd.DataFrame(boundary_table(g.result)), use_container_width=True)
    if ir.unsupported:
        st.write("Unsupported constructs"); st.dataframe(pd.DataFrame(ir.unsupported))
