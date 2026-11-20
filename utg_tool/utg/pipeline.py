"""End-to-end orchestration used by the CLI, the Streamlit UI and the tests."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .cfg import CFG, build_cfg
from .codegen import CodegenReport, classify_access, generate_test_file
from .config import ProjectConfig
from .dataflow import analyze
from .ir import FunctionIR
from .parser import CParser
from .scenarios import GenerationResult, ScenarioGenerator


@dataclass
class Analysis:
    ir: FunctionIR
    cfg_graph: CFG
    access_issues: list


@dataclass
class Generated:
    result: GenerationResult
    code: str
    report: CodegenReport


def analyse_function(cfg: ProjectConfig, function: str, parser: Optional[CParser] = None) -> Analysis:
    parser = parser or CParser(cfg)
    ir = parser.build_ir(function)
    analyze(ir)
    return Analysis(ir=ir, cfg_graph=build_cfg(ir), access_issues=classify_access(ir, cfg))


def generate(cfg: ProjectConfig, analysis: Analysis, strategies=("branch", "condition", "boundary")) -> Generated:
    res = ScenarioGenerator(analysis.ir, cfg).generate(strategies)
    code, rep = generate_test_file(analysis.ir, cfg, res)
    return Generated(res, code, rep)
