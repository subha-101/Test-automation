"""
parser/exporter.py
-------------------
Handles serialisation of :class:`FunctionReport` objects to:
  - JSON files
  - CSV files  (one row per test case)
  - Excel .xlsx files (formatted, one sheet per function)

All output goes to a configurable output directory.
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import List

from models.testcase_models import FunctionReport

logger = logging.getLogger(__name__)


class Exporter:
    """
    Exports :class:`FunctionReport` objects to JSON, CSV, and/or Excel.

    Usage::

        exporter = Exporter(output_dir="output/")
        exporter.export_json(report)
        exporter.export_csv([report1, report2])
        exporter.export_excel([report1, report2])
    """

    def __init__(self, output_dir: str | Path = "output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # JSON
    # ------------------------------------------------------------------

    def export_json(self, report: FunctionReport, json_str: str) -> Path:
        """Write *json_str* to a file named after the function."""
        safe_name = self._safe_filename(report.function_under_test)
        out_path = self.output_dir / f"{safe_name}.json"
        out_path.write_text(json_str, encoding="utf-8")
        logger.info("JSON written: %s", out_path)
        return out_path

    def export_all_json(
        self, reports: List[FunctionReport], json_strings: List[str]
    ) -> Path:
        """Write all reports into a single combined JSON array."""
        combined = []
        for js in json_strings:
            combined.append(json.loads(js))

        out_path = self.output_dir / "all_functions.json"
        out_path.write_text(
            json.dumps(combined, indent=2),
            encoding="utf-8",
        )
        logger.info("Combined JSON written: %s", out_path)
        return out_path

    # ------------------------------------------------------------------
    # CSV
    # ------------------------------------------------------------------

    def export_csv(self, reports: List[FunctionReport]) -> Path:
        """
        Export a summary CSV with one row per test case.

        Columns:
          function_under_test | testcase_id | description |
          input_count | output_count | call_trace_count | has_mock
        """
        out_path = self.output_dir / "testcase_summary.csv"
        fieldnames = [
            "function_under_test",
            "testcase_id",
            "description",
            "input_count",
            "output_count",
            "call_trace_count",
            "has_mock_return",
            "has_struct_mock",
        ]

        with out_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()

            for report in reports:
                for tc in report.testcases:
                    writer.writerow({
                        "function_under_test": report.function_under_test,
                        "testcase_id":         tc.testcase_id,
                        "description":         tc.description,
                        "input_count":         len(tc.inputs),
                        "output_count":        len(tc.outputs),
                        "call_trace_count":    len(tc.call_trace),
                        "has_mock_return": any(
                            getattr(i, "type", "") == "mock_return"
                            for i in tc.inputs
                        ),
                        "has_struct_mock": any(
                            getattr(i, "type", "") == "mock_struct_return"
                            for i in tc.inputs
                        ),
                    })

        logger.info("CSV written: %s", out_path)
        return out_path

    # ------------------------------------------------------------------
    # Excel
    # ------------------------------------------------------------------

    def export_excel(self, reports: List[FunctionReport]) -> Path:
        """
        Export a formatted Excel workbook.

        Sheet layout:
          - "Summary"      — one row per function
          - Per-function   — one sheet per function, one row per test case
        """
        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment
        except ImportError:
            logger.error("openpyxl not installed — Excel export skipped.")
            return Path()

        wb = openpyxl.Workbook()

        # ---- Summary sheet ----
        ws_summary = wb.active
        ws_summary.title = "Summary"
        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill("solid", fgColor="1F4E79")

        summary_headers = [
            "Function", "Total TCs", "Successful", "Failed", "Source PDF"
        ]
        for col, h in enumerate(summary_headers, 1):
            cell = ws_summary.cell(row=1, column=col, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")

        for row_idx, report in enumerate(reports, 2):
            ws_summary.cell(row=row_idx, column=1, value=report.function_under_test)
            ws_summary.cell(row=row_idx, column=2, value=report.total_testcases)
            ws_summary.cell(row=row_idx, column=3, value=report.successful)
            ws_summary.cell(row=row_idx, column=4, value=report.failed)
            ws_summary.cell(row=row_idx, column=5, value=Path(report.source_pdf).name)

        self._auto_width(ws_summary)

        # ---- Per-function sheets ----
        for report in reports:
            sheet_name = report.function_under_test[-31:]  # Excel max 31 chars
            ws = wb.create_sheet(title=sheet_name)

            tc_headers = [
                "TC ID", "Description",
                "Input Name/Function", "Input Type", "Input Value",
                "Output Function", "Expected Value",
                "Call Trace Function", "Call Count",
            ]
            for col, h in enumerate(tc_headers, 1):
                cell = ws.cell(row=1, column=col, value=h)
                cell.font = Font(bold=True)
                cell.fill = PatternFill("solid", fgColor="BDD7EE")

            row_idx = 2
            for tc in report.testcases:
                max_rows = max(
                    len(tc.inputs), len(tc.outputs), len(tc.call_trace), 1
                )
                for i in range(max_rows):
                    inp = tc.inputs[i] if i < len(tc.inputs) else None
                    out = tc.outputs[i] if i < len(tc.outputs) else None
                    ctr = tc.call_trace[i] if i < len(tc.call_trace) else None

                    ws.cell(row=row_idx, column=1, value=tc.testcase_id if i == 0 else "")
                    ws.cell(row=row_idx, column=2, value=tc.description if i == 0 else "")

                    if inp:
                        d = asdict(inp)
                        ws.cell(row=row_idx, column=3, value=d.get("name") or d.get("function", ""))
                        ws.cell(row=row_idx, column=4, value=d.get("type", ""))
                        ws.cell(row=row_idx, column=5, value=str(d.get("value") or d.get("return_value", "")))

                    if out:
                        d = asdict(out)
                        ws.cell(row=row_idx, column=6, value=d.get("function") or d.get("name", ""))
                        ws.cell(row=row_idx, column=7, value=str(d.get("expected_value", "")))

                    if ctr:
                        ws.cell(row=row_idx, column=8, value=ctr.function)
                        ws.cell(row=row_idx, column=9, value=ctr.count)

                    row_idx += 1

            self._auto_width(ws)

        out_path = self.output_dir / "tessy_report.xlsx"
        wb.save(out_path)
        logger.info("Excel written: %s", out_path)
        return out_path

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_filename(name: str) -> str:
        """Convert a function name to a safe filesystem name."""
        return re.sub(r"[^\w]", "_", name)

    @staticmethod
    def _auto_width(ws) -> None:
        """Auto-size columns based on content."""
        for col in ws.columns:
            max_len = 0
            col_letter = col[0].column_letter
            for cell in col:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
            ws.column_dimensions[col_letter].width = min(max_len + 4, 50)


import re  # noqa: E402  (placed here to avoid circular at module level)
