"""
parser/json_builder.py
-----------------------
Assembles classified data into FunctionReport model objects and serialises
them to JSON.

Changes from original:
  1. Uses TableExtractor.promote() so both Pattern A and Pattern B produce
     normalised PromotedTestCase objects before classification.
  2. The 'actual_return_value' field is now captured in return_value_check
     outputs (Pattern B: the function's actual return value is the Actual
     Value column when the name matches the function under test).
  3. Pattern B test cases get an auto-generated description from the
     function name stored in the report.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, List

import pdfplumber

from models.testcase_models import (
    FunctionReport,
    TestCase,
    TestStep,
)
from parser.classifier import (
    CallTraceClassifier,
    InputClassifier,
    OutputClassifier,
)
from parser.pdf_reader import PDFDocument
from parser.table_extractor import (
    PromotedTestCase,
    RawPageExtraction,
    RawTestCase,
    TableExtractor,
)

logger = logging.getLogger(__name__)

RE_TEST_OBJECT = re.compile(r"Test\s+Object\s+(\S+)")
RE_PROJECT     = re.compile(r"^Project\s+(.+)$", re.MULTILINE)
RE_MODULE      = re.compile(r"^Module\s+(\S+)", re.MULTILINE)
RE_TOTAL_TC    = re.compile(r"Total\s+Testcases\s+(\d+)")
RE_SUCCESSFUL  = re.compile(r"Successful\s+(\d+)")
RE_FAILED      = re.compile(r"Failed\s+(\d+)")


class JSONBuilder:
    """
    Orchestrates:
      PDF pages → TableExtractor (extract + promote) → classify → FunctionReport → JSON
    """

    def __init__(self):
        self._extractor      = TableExtractor()
        self._input_cls      = InputClassifier()
        self._output_cls     = OutputClassifier()
        self._call_trace_cls = CallTraceClassifier()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self, doc: PDFDocument) -> FunctionReport:
        report = FunctionReport(source_pdf=str(doc.pdf_path))

        # Page 1: metadata only
        if doc.pages:
            self._extract_metadata(doc.pages[0].text, report)

        # Pages 2+: all content pages parsed as ONE continuous stream.
        # This is critical for PDFs where a test step's data spans a page
        # boundary — the extractor must carry state across page breaks.
        content_pages = doc.pages[1:]
        if content_pages:
            raw = self._extractor.extract_all(content_pages)
            all_promoted = self._extractor.promote(raw)
        else:
            all_promoted = []

        # Build typed TestCase objects
        for ptc in all_promoted:
            tc = self._build_test_case(ptc, report.function_under_test)
            report.testcases.append(tc)

        logger.info(
            "Built report for '%s': %d test case(s)",
            report.function_under_test,
            len(report.testcases),
        )
        return report

    def to_json(self, report: FunctionReport, indent: int = 2) -> str:
        data = self._report_to_dict(report)
        return json.dumps(data, indent=indent, default=str)

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def _extract_metadata(self, page1_text: str, report: FunctionReport) -> None:
        m = RE_TEST_OBJECT.search(page1_text)
        if m:
            report.function_under_test = m.group(1).strip()
        m = RE_PROJECT.search(page1_text)
        if m:
            report.project = m.group(1).strip()
        m = RE_MODULE.search(page1_text)
        if m:
            report.module = m.group(1).strip()
        m = RE_TOTAL_TC.search(page1_text)
        if m:
            report.total_testcases = int(m.group(1))
        m = RE_SUCCESSFUL.search(page1_text)
        if m:
            report.successful = int(m.group(1))
        m = RE_FAILED.search(page1_text)
        if m:
            report.failed = int(m.group(1))

    # ------------------------------------------------------------------
    # Test case building from a PromotedTestCase
    # ------------------------------------------------------------------

    def _build_test_case(
        self, ptc: PromotedTestCase, function_under_test: str
    ) -> TestCase:
        """Classify all rows in a promoted test case into a typed TestCase."""

        # Auto-generate description for Pattern B cases (no description in PDF)
        description = ptc.description
        if not description and function_under_test:
            description = f"Testing for {function_under_test}"

        tc = TestCase(
            testcase_id=ptc.testcase_id,
            description=description,
        )

        # Inputs
        for row in ptc.input_rows:
            try:
                classified = self._input_cls.classify(row)
                tc.inputs.append(classified)
            except Exception as exc:
                logger.warning("Input classification failed for '%s': %s", row.name, exc)

        # Outputs — pass function_under_test so actual_return_value can be set
        for row in ptc.output_rows:
            try:
                classified = self._output_cls.classify(row, function_under_test)
                tc.outputs.append(classified)
            except Exception as exc:
                logger.warning("Output classification failed for '%s': %s", row.name, exc)

        # Call trace
        for row in ptc.call_trace_rows:
            try:
                classified = self._call_trace_cls.classify(row)
                tc.call_trace.append(classified)
            except Exception as exc:
                logger.warning(
                    "Call-trace classification failed for '%s': %s",
                    row.actual_function, exc,
                )

        return tc

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def _report_to_dict(self, report: FunctionReport) -> dict:
        testcases = []
        for tc in report.testcases:
            testcases.append({
                "testcase_id": tc.testcase_id,
                "description": tc.description,
                "inputs":      [asdict(inp) for inp in tc.inputs],
                "call_trace":  [asdict(ct)  for ct  in tc.call_trace],
                "outputs":     [asdict(out) for out in tc.outputs],
            })

        return {
            "function_under_test": report.function_under_test,
            "source_pdf":          report.source_pdf,
            "project":             report.project,
            "module":              report.module,
            "statistics": {
                "total_testcases": report.total_testcases,
                "successful":      report.successful,
                "failed":          report.failed,
            },
            "testcases": testcases,
        }
