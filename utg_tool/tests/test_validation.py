import os, re, shutil
import pytest
from conftest import FN
from utg.config import ProjectConfig
from utg.pipeline import analyse_function, generate
from utg.validate import compile_and_run, static_validate, _find_cpputest, overall_level

pytestmark = pytest.mark.skipif(not (_find_cpputest(ProjectConfig()) and shutil.which("g++")),
                                reason="CppUTest/g++ not available: compile+run validation cannot be performed")


def test_generated_tests_compile_and_pass_on_real_source(cfg, analysis, generated, tmp_path):
    rep = compile_and_run(analysis.ir, cfg, generated.code, str(tmp_path))
    assert rep.compiled, rep.compile_log
    assert rep.executed and rep.tests_run == len(generated.result.scenarios) and rep.tests_failed == 0, rep.run_log
    assert rep.measured["lines_hit"] == rep.measured["lines_total"]
    assert rep.measured["branches_taken"] == rep.measured["branches_total"]


MUTANTS = [
    ("C1 boundary", "if ( f32_LSOut11Short <= f32_CuLSOut11 )", "if ( f32_LSOut11Short < f32_CuLSOut11 )"),
    ("C3 boundary", "if ( f32_LSOut11CurrH <= f32_CuLSOut11 )", "if ( f32_LSOut11CurrH < f32_CuLSOut11 )"),
    ("short counter step", "u8_time_LSOut11Short ++;", "u8_time_LSOut11Short += 2;"),
    ("reset removed", "u8_time_LSOut11CurrH = 0;", "u8_time_LSOut11CurrH = u8_time_LSOut11CurrH;"),
    ("timer cmp", "( u8_MaxTime_LSOut11Short <= u8_time_LSOut11Short )", "( u8_MaxTime_LSOut11Short < u8_time_LSOut11Short )"),
    ("latch condition", "( 0.0f == f32_CuLSOut11Short )", "( 0.0f != f32_CuLSOut11Short )"),
    ("or->and", "|| ( 0.0f != f32_CuLSOut11Short )", "&& ( 0.0f != f32_CuLSOut11Short )"),
    ("enable inverted", "b_LSOut11_250us =  TRUE;", "b_LSOut11_250us =  FALSE;"),
    ("flush removed", "(VO) sig_hwc_tx_LS11_flush ();", ""),
]


# Known survivor: needs MC/DC (a vector where ONE operand alone decides C5).  Planned for phase 3 - strict xfail
# so this flips to a failure (and must be un-marked) the moment MC/DC is implemented.
KNOWN_SURVIVORS = {"or->and"}


def _param(m):
    return pytest.param(*m, id=m[0], marks=[pytest.mark.xfail(strict=True, reason="needs MC/DC (phase 3)")]
                        if m[0] in KNOWN_SURVIVORS else [])


@pytest.mark.parametrize("label,old,new", [_param(m) for m in MUTANTS])
def test_mutants_are_killed(label, old, new, cfg, analysis, generated, bench_copy, tmp_path):
    src = bench_copy / "test/mock/lsout11/source.c"
    text = src.read_bytes().decode().replace("\r\n", "\n")
    assert old in text, f"mutation anchor not found: {old}"
    src.write_text(text.replace(old, new, 1))
    mcfg = ProjectConfig.load(str(bench_copy / "project.json"))
    rep = compile_and_run(analysis.ir, mcfg, generated.code, str(tmp_path), measure_coverage=False)
    assert rep.compiled, rep.compile_log
    assert rep.executed is False and rep.tests_failed >= 1, f"mutant '{label}' survived"


def test_static_findings_do_not_claim_more_than_done(cfg, analysis, generated):
    f = static_validate(analysis.ir, cfg, generated.result, generated.code)
    assert not [x for x in f if x.severity == "error"]
    assert any("assumed" in x.message for x in f)


def test_relative_workdir_is_supported(cfg, analysis, generated, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rep = compile_and_run(analysis.ir, cfg, generated.code, "rel_build", measure_coverage=False)
    assert rep.compiled and rep.executed, rep.compile_log
