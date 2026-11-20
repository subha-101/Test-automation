"""
main.py
--------
Entry point for the TESSY PDF Test Specification Extraction Engine.

Usage
-----
  # Parse a single PDF
  python main.py path/to/report.pdf

  # Parse all PDFs in a directory
  python main.py path/to/test_details/

  # Parse and export to Excel as well
  python main.py path/to/test_details/ --excel

  # Enable verbose debug logging
  python main.py path/to/report.pdf --debug

  # Specify custom output directory
  python main.py path/to/report.pdf --output my_output/
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Allow running from the project root directly
sys.path.insert(0, str(Path(__file__).parent))

from parser.exporter import Exporter
from parser.json_builder import JSONBuilder
from parser.pdf_reader import PDFReader
from models.testcase_models import FunctionReport
from utils import configure_logging, collect_pdfs

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "TESSY PDF Test Specification Extraction Engine\n"
            "Extracts structured unit test data from TESSY PDF reports\n"
            "and outputs JSON (and optionally CSV/Excel)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "input",
        help="Path to a single TESSY PDF or a directory containing PDFs.",
    )
    p.add_argument(
        "--output", "-o",
        default="output",
        help="Directory for generated output files (default: ./output).",
    )
    p.add_argument(
        "--excel", "-e",
        action="store_true",
        help="Also export an Excel .xlsx workbook.",
    )
    p.add_argument(
        "--csv", "-c",
        action="store_true",
        help="Also export a CSV summary.",
    )
    p.add_argument(
        "--debug", "-d",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    p.add_argument(
        "--log-file",
        default=None,
        help="Optional path to write log output (in addition to stdout).",
    )
    return p


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def run(
    input_path: str | Path,
    output_dir: str | Path = "output",
    export_excel: bool = False,
    export_csv: bool = False,
) -> list[FunctionReport]:
    """
    Main pipeline:
      1. Collect PDFs
      2. Read each PDF
      3. Extract and classify
      4. Build JSON
      5. Export

    Returns the list of :class:`FunctionReport` objects produced.
    """
    pdf_paths = collect_pdfs(input_path)

    if not pdf_paths:
        logger.error("No PDF files found at: %s", input_path)
        return []

    logger.info("Processing %d PDF(s) …", len(pdf_paths))

    reader   = PDFReader()
    builder  = JSONBuilder()
    exporter = Exporter(output_dir=output_dir)

    reports: list[FunctionReport] = []
    json_strings: list[str] = []

    for pdf_path in pdf_paths:
        logger.info("─── %s ───", pdf_path.name)
        try:
            doc     = reader.read(pdf_path)
            report  = builder.build(doc)
            js      = builder.to_json(report)

            # Save individual JSON
            exporter.export_json(report, js)

            reports.append(report)
            json_strings.append(js)

            # Print to console for immediate feedback
            print(f"\n{'='*60}")
            print(f"Function: {report.function_under_test}")
            print(f"Test cases extracted: {len(report.testcases)}")
            print(js)

        except Exception as exc:
            logger.error("Failed to process %s: %s", pdf_path.name, exc, exc_info=True)

    # if reports:
    #     # Combined JSON
    #     exporter.export_all_json(reports, json_strings)

    #     if export_csv:
    #         exporter.export_csv(reports)

    #     if export_excel:
    #         exporter.export_excel(reports)

    logger.info("Done. Output written to: %s", Path(output_dir).resolve())
    return reports


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = build_arg_parser()
    args   = parser.parse_args()

    configure_logging(
        level=logging.DEBUG if args.debug else logging.INFO,
        log_file=args.log_file,
    )

    run(
        input_path=args.input,
        output_dir=args.output,
        export_excel=args.excel,
        export_csv=args.csv,
    )


if __name__ == "__main__":
    main()
