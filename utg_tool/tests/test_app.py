import os, shutil
import pytest
from streamlit.testing.v1 import AppTest
from utg.config import ProjectConfig
from utg.validate import _find_cpputest

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def _go(at, page):
    at.sidebar.radio[0].set_value(page).run(timeout=120)
    assert not at.exception, [e.value for e in at.exception]


def test_full_ui_flow():
    at = AppTest.from_file(APP, default_timeout=120).run()
    assert not at.exception
    at.button[0].click().run(timeout=120)                          # load benchmark
    assert "Benchmark project loaded." in [s.value for s in at.success]
    _go(at, "2 Function selection")
    next(b for b in at.button if b.label == "Analyse").click().run(timeout=120)
    _go(at, "3 Function analysis")
    assert any("rc_lsout11_out_250us" in c.value for c in at.code)
    _go(at, "4 Scenario generation")
    next(b for b in at.button if b.label == "Generate scenarios").click().run(timeout=180)
    assert not at.exception
    _go(at, "5 Code generation")
    assert "TEST(rc_lsout11_out_250us, Testcase_1_1)" in at.text_area[0].value
    _go(at, "6 Validation and coverage")
    if _find_cpputest(ProjectConfig()) and shutil.which("g++"):
        next(b for b in at.button if b.label.startswith("Run static")).click().run(timeout=300)
        assert not at.exception
        assert any("Executed: 12 tests, 0 failed" in s.value for s in at.success)
