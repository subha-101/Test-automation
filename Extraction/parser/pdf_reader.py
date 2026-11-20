"""
parser/pdf_reader.py
---------------------
Responsible for opening PDF files and providing raw page-level
text and word-position data to downstream extractors.

Design principles:
  - Single responsibility: open files, yield pages, nothing else.
  - Expose both flat text and word objects for flexible downstream use.
  - Robust error handling so a bad PDF does not abort a batch run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional

import pdfplumber

logger = logging.getLogger(__name__)


@dataclass
class PageData:
    """All raw extraction results for a single PDF page."""
    page_number: int
    text: str = ""
    words: List[dict] = field(default_factory=list)
    tables: List[List[List[Optional[str]]]] = field(default_factory=list)


@dataclass
class PDFDocument:
    """Container for all pages extracted from one PDF file."""
    pdf_path: Path
    pages: List[PageData] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.pdf_path.name


class PDFReader:
    """
    Opens a TESSY PDF and extracts per-page text, words, and tables
    using pdfplumber.

    Usage::

        reader = PDFReader()
        doc = reader.read("path/to/report.pdf")
        for page in doc.pages:
            print(page.text)
    """

    def __init__(self, table_settings: Optional[dict] = None):
        """
        Parameters
        ----------
        table_settings:
            Optional pdfplumber table extraction settings override.
            Useful if TESSY table borders change in future versions.
        """
        self._table_settings = table_settings or {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read(self, pdf_path: str | Path) -> PDFDocument:
        """
        Read all pages from *pdf_path* and return a :class:`PDFDocument`.

        Raises
        ------
        FileNotFoundError
            If *pdf_path* does not exist.
        RuntimeError
            If the PDF cannot be opened or parsed.
        """
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {path}")

        logger.info("Opening PDF: %s", path)

        try:
            doc = PDFDocument(pdf_path=path)
            with pdfplumber.open(path) as pdf:
                for page_obj in pdf.pages:
                    page_data = self._extract_page(page_obj)
                    doc.pages.append(page_data)
            logger.info("Extracted %d page(s) from %s", len(doc.pages), path.name)
            return doc

        except Exception as exc:
            logger.error("Failed to read PDF %s: %s", path, exc)
            raise RuntimeError(f"Cannot parse PDF {path}: {exc}") from exc

    def read_directory(self, directory: str | Path) -> Iterator[PDFDocument]:
        """
        Yield :class:`PDFDocument` objects for every PDF in *directory*.
        Errors on individual files are logged and skipped.
        """
        directory = Path(directory)
        pdf_files = sorted(directory.glob("*.pdf"))
        logger.info("Found %d PDF(s) in %s", len(pdf_files), directory)

        for pdf_path in pdf_files:
            try:
                yield self.read(pdf_path)
            except (FileNotFoundError, RuntimeError) as exc:
                logger.warning("Skipping %s — %s", pdf_path.name, exc)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_page(self, page_obj) -> PageData:
        page_number = page_obj.page_number  # 1-based in pdfplumber

        text = page_obj.extract_text() or ""

        words = page_obj.extract_words(
            x_tolerance=3,
            y_tolerance=3,
            keep_blank_chars=False,
        )

        tables = []
        try:
            raw_tables = page_obj.extract_tables(self._table_settings)
            for table in raw_tables:
                # Normalise cells: convert None → ""
                normalised = [
                    [cell if cell is not None else "" for cell in row]
                    for row in table
                    if any(cell for cell in row)   # drop fully empty rows
                ]
                if normalised:
                    tables.append(normalised)
        except Exception as exc:
            logger.warning("Table extraction failed on page %d: %s", page_number, exc)

        return PageData(
            page_number=page_number,
            text=text,
            words=words,
            tables=tables,
        )
