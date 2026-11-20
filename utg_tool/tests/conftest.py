import os, shutil, sys
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from utg.config import ProjectConfig
from utg.pipeline import analyse_function, generate

BENCH = os.path.join(ROOT, "examples", "benchmark")
FN = "rc_lsout11_out_250us"


@pytest.fixture(scope="session")
def cfg():
    return ProjectConfig.load(os.path.join(BENCH, "project.json"))


@pytest.fixture(scope="session")
def analysis(cfg):
    return analyse_function(cfg, FN)


@pytest.fixture(scope="session")
def generated(cfg, analysis):
    return generate(cfg, analysis)


@pytest.fixture
def bench_copy(tmp_path):
    dst = tmp_path / "bench"
    shutil.copytree(BENCH, dst, ignore=shutil.ignore_patterns("expected", "__pycache__", "*.cpp", "build"))
    return dst
