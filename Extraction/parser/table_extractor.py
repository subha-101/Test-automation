"""
parser/table_extractor.py
--------------------------
Extracts structured raw table data from TESSY PDF page content.

Supports two distinct TESSY report layouts:

  PATTERN A — "Stepped" (old format, e.g. mcal_master_io)
  ---------------------------------------------------------
  Page layout:
    Test Case 1
      Description  <text>
      Test Step 1.1 (Repeat Count = 1)
        Name | Input Value          ← mock function calls as inputs
        Name | Actual | Expected    ← function-under-test output
        Test Step Call Trace        ← call-trace table
  Behaviour:
    • All test steps under one Test Case are MERGED into a single TC_01.
    • Call-trace section is parsed.
    • Input names contain "()" → mock_return / mock_struct_return.

  PATTERN B — "Flat" (new format, e.g. max2_s8)
  -----------------------------------------------
  Page layout:
    Test Case 1
      Test Step 1.1 (Repeat Count = 1)
        Name | Input Value          ← plain C identifiers as inputs
        Name | Actual | Expected    ← function-under-test output
      Test Step 1.2 (Repeat Count = 1)
        ...
  Behaviour:
    • Each test step becomes its OWN top-level test case: TC_1_1, TC_1_2 …
    • No call-trace section.
    • Input names are plain C identifiers → function_argument.
    • Actual Value is captured as actual_return_value on the output row.

PATTERN DETECTION
-----------------
Detected automatically per RawTestCase after all lines are parsed:
  • Description line present            → Pattern A
  • Call-trace section present          → Pattern A
  • Exactly one test step               → Pattern A (backward compat)
  • No description + no call-trace
    + multiple steps                    → Pattern B

COLUMN RECOVERY STRATEGY
-------------------------
pdfplumber text collapses columns to a single space for short names ("a",
"b"), making 2+-space splits unreliable.  The extractor anchors every data
row to its y-coordinate, then classifies each word by its x-position:
  Name:     x0 <  200
  Value / Actual:  200 ≤ x0 < 400
  Expected: 400 ≤ x0 < 530
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from parser.pdf_reader import PageData

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

RE_TEST_CASE = re.compile(r"^Test\s+Case\s+(\d+)", re.IGNORECASE)

# Captures:  group(1)=parent, group(2)=step, group(3)=repeat_count
RE_TEST_STEP = re.compile(
    r"Test\s+Step\s+(\d+)\.(\d+)\s*\(Repeat\s+Count\s*=\s*(\d+)\)",
    re.IGNORECASE,
)

RE_CALL_TRACE     = re.compile(r"Test\s+Step\s+Call\s+Trace", re.IGNORECASE)
RE_INPUT_HEADER   = re.compile(r"^Name\s+Input\s+Value", re.IGNORECASE)
RE_OUTPUT_HEADER  = re.compile(r"^Name\s+Actual\s+Value\s+Expected\s+Value", re.IGNORECASE)
RE_CALL_TRACE_HDR = re.compile(r"Actual\s+Function\s+Count\s+Expected\s+Function", re.IGNORECASE)
RE_FOOTER_LINE    = re.compile(
    r"(?:^\s*©\s*|Report\s+created\s+by\s+TESSY|report\s+template)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Raw data-classes
# ---------------------------------------------------------------------------

@dataclass
class RawInputRow:
    """One row from the input table, before semantic classification."""
    name: str
    value: str


@dataclass
class RawOutputRow:
    """One row from the output table."""
    name: str
    actual_value: str
    expected_value: str
    result: str = ""


@dataclass
class RawCallTraceRow:
    """One row from the call-trace table."""
    actual_function: str
    count: str


@dataclass
class RawTestStep:
    """Raw data for one Test Step block, exactly as it appears in the PDF."""
    parent_case_num: int = 0
    step_num: int = 0
    repeat_count: int = 1
    input_rows:      List[RawInputRow]      = field(default_factory=list)
    output_rows:     List[RawOutputRow]     = field(default_factory=list)
    call_trace_rows: List[RawCallTraceRow]  = field(default_factory=list)

    @property
    def step_id(self) -> str:
        return f"{self.parent_case_num}.{self.step_num}"


@dataclass
class RawTestCase:
    """Raw data for one 'Test Case N' block as written in the PDF."""
    case_number: int
    description: str = ""
    has_call_trace: bool = False          # True if any step had a call-trace section
    test_steps: List[RawTestStep] = field(default_factory=list)


@dataclass
class RawPageExtraction:
    """All raw test data extracted from a single report page."""
    page_number: int
    test_cases: List[RawTestCase] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Promoted (normalised) test case — output of pattern promotion
# ---------------------------------------------------------------------------

@dataclass
class PromotedTestCase:
    """
    A test case after pattern-level normalisation.

    Both Pattern A and B ultimately produce a list of these, so downstream
    code (json_builder) is completely pattern-agnostic.

    testcase_id
        Pattern A:  "TC_01"
        Pattern B:  "TC_1_1", "TC_1_2" …
    """
    testcase_id: str
    description: str = ""
    input_rows:      List[RawInputRow]     = field(default_factory=list)
    output_rows:     List[RawOutputRow]    = field(default_factory=list)
    call_trace_rows: List[RawCallTraceRow] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------

class TableExtractor:
    """
    Transforms :class:`PageData` objects into :class:`PromotedTestCase` lists.

    Two-phase operation:
      1. :meth:`extract` — line-by-line parse into :class:`RawPageExtraction`.
      2. :meth:`promote` — pattern detection + normalisation into
         :class:`PromotedTestCase` objects.
    """

    # ------------------------------------------------------------------
    # Phase 1: raw extraction — SINGLE PAGE
    # ------------------------------------------------------------------

    def extract(self, page: PageData) -> RawPageExtraction:
        """
        Parse one page and return raw, un-promoted test data.

        .. note::
            For multi-page PDFs where a test step spans a page boundary,
            use :meth:`extract_all` instead.  This method resets parser
            state at every call, so any step that starts on one page and
            continues on the next will be truncated.
        """
        result = RawPageExtraction(page_number=page.page_number)
        self._reset_parse_state()
        self._build_y_index(page)
        self._parse_lines(self._clean_lines(page.text), result)
        return result

    # ------------------------------------------------------------------
    # Phase 1B: raw extraction — ALL PAGES (cross-page continuity)
    # ------------------------------------------------------------------

    def extract_all(self, pages: List[PageData]) -> RawPageExtraction:
        """
        Parse *all* content pages as a single continuous line stream.

        This is the correct method to use for multi-page PDFs where a
        test step's input table, output table, or call-trace section can
        be split across a page boundary.

        The y-index is rebuilt for each page (word positions are always
        local to a page), but the parser's state (current_case,
        current_step, parse_state) is preserved across page transitions.

        Parameters
        ----------
        pages:
            Ordered list of :class:`PageData` objects representing all
            content pages (i.e. skip the cover page before calling).

        Returns
        -------
        RawPageExtraction
            A single aggregated extraction whose ``test_cases`` list
            contains raw cases assembled from all pages.
        """
        # Use page_number=0 to signal "multi-page aggregate"
        result = RawPageExtraction(page_number=0)
        self._reset_parse_state()

        for page in pages:
            # Rebuild the word-position index for this page's coordinates.
            # Parser state (current_case, current_step, parse_state) is
            # intentionally NOT reset between pages.
            self._build_y_index(page)
            self._parse_lines(self._clean_lines(page.text), result)

        return result

    # ------------------------------------------------------------------
    # Internal parse helpers shared by extract() and extract_all()
    # ------------------------------------------------------------------

    def _reset_parse_state(self) -> None:
        """Reset per-document parser state variables."""
        self._current_case: Optional[RawTestCase]  = None
        self._current_step: Optional[RawTestStep]  = None
        self._parse_state: str = "IDLE"   # IDLE | INPUT | OUTPUT | CALLTRACE

    def _build_y_index(self, page: PageData) -> None:
        """Build y → word-list lookup for the given page."""
        self._y_index: Dict[int, List[dict]] = {}
        for word in page.words:
            y = round(word["top"])
            self._y_index.setdefault(y, []).append(word)

    def _parse_lines(
        self, lines: List[str], result: RawPageExtraction
    ) -> None:
        """
        Process *lines* in order, updating *result* and internal state.

        This is the single authoritative parsing loop used by both
        :meth:`extract` (single page) and :meth:`extract_all` (all pages).
        """
        i = 0
        while i < len(lines):
            line = lines[i]

            # ── Ignore page header / footer lines ─────────────────────
            if self._is_page_header(line) or self._is_footer_line(line):
                i += 1
                continue

            # ── Test Case header ──────────────────────────────────────
            m = RE_TEST_CASE.match(line)
            if m:
                case_number = int(m.group(1))
                self._current_case = RawTestCase(case_number=case_number)
                result.test_cases.append(self._current_case)
                self._current_step = None
                self._parse_state  = "IDLE"
                i += 1
                continue

            # ── Description line (Pattern A indicator) ────────────────
            if (
                self._current_case is not None
                and not self._current_case.description
                and line.lower().startswith("description")
            ):
                self._current_case.description = line[len("description"):].strip()
                i += 1
                continue

            # ── Test Step header ──────────────────────────────────────
            m = RE_TEST_STEP.search(line)
            if m:
                parent_num = int(m.group(1))
                step_num   = int(m.group(2))
                repeat     = int(m.group(3))

                if self._current_case is None:   # defensive guard
                    self._current_case = RawTestCase(case_number=parent_num)
                    result.test_cases.append(self._current_case)

                self._current_step = RawTestStep(
                    parent_case_num=parent_num,
                    step_num=step_num,
                    repeat_count=repeat,
                )
                self._current_case.test_steps.append(self._current_step)
                self._parse_state = "IDLE"
                i += 1
                continue

            # ── Call Trace section header ─────────────────────────────
            if RE_CALL_TRACE.search(line):
                self._parse_state = "CALLTRACE"
                if self._current_case is not None:
                    self._current_case.has_call_trace = True
                i += 1
                continue

            # ── Table section headers ─────────────────────────────────
            if RE_INPUT_HEADER.match(line):
                self._parse_state = "INPUT"
                i += 1
                continue

            if RE_OUTPUT_HEADER.match(line):
                self._parse_state = "OUTPUT"
                i += 1
                continue

            if RE_CALL_TRACE_HDR.search(line):
                i += 1
                continue

            # ── Data rows (context-dependent) ────────────────────────
            if self._current_step is not None and self._parse_state != "IDLE":

                if self._parse_state == "INPUT":
                    row = self._parse_input_row(line)
                    if row:
                        self._current_step.input_rows.append(row)

                elif self._parse_state == "OUTPUT":
                    row = self._parse_output_row(line)
                    if row:
                        if not row.name and self._current_step.output_rows:
                            # Continuation line: long name wrapped → values land on next y.
                            # Merge into the last incomplete output row.
                            last = self._current_step.output_rows[-1]
                            if not last.actual_value:
                                last.actual_value = row.actual_value
                            if not last.expected_value:
                                last.expected_value = row.expected_value
                        else:
                            self._current_step.output_rows.append(row)

                elif self._parse_state == "CALLTRACE":
                    row = self._parse_call_trace_row(line)
                    if row:
                        self._current_step.call_trace_rows.append(row)

            i += 1

    # ------------------------------------------------------------------
    # Phase 2: pattern promotion
    # ------------------------------------------------------------------

    def promote(self, raw: RawPageExtraction) -> List[PromotedTestCase]:
        """
        Normalise raw test cases into :class:`PromotedTestCase` objects.

        Pattern A  →  one promoted TC per raw case   (id = TC_01)
        Pattern B  →  one promoted TC per step        (id = TC_1_1)
        """
        promoted: List[PromotedTestCase] = []
        for raw_case in raw.test_cases:
            if self._is_pattern_a(raw_case):
                promoted.append(self._promote_pattern_a(raw_case))
            else:
                promoted.extend(self._promote_pattern_b(raw_case))
        return promoted

    # ------------------------------------------------------------------
    # Pattern detection
    # ------------------------------------------------------------------

    @staticmethod
    def _is_pattern_a(raw_case: RawTestCase) -> bool:
        """
        True  → merge all steps into one TC  (Pattern A / old format)
        False → each step becomes its own TC (Pattern B / new format)
        """
        if raw_case.description:       # Description line present → Pattern A
            return True
        if raw_case.has_call_trace:    # Call-trace present → Pattern A
            return True
        if len(raw_case.test_steps) <= 1:  # Single step → Pattern A (backward compat)
            return True
        return False                   # Multiple steps, no description → Pattern B

    # ------------------------------------------------------------------
    # Pattern A: merge all steps into one promoted TC
    # ------------------------------------------------------------------

    def _promote_pattern_a(self, raw_case: RawTestCase) -> PromotedTestCase:
        ptc = PromotedTestCase(
            testcase_id=f"TC_{raw_case.case_number:02d}",
            description=raw_case.description,
        )
        for step in raw_case.test_steps:
            ptc.input_rows.extend(step.input_rows)
            ptc.output_rows.extend(step.output_rows)
            ptc.call_trace_rows.extend(step.call_trace_rows)
        return ptc

    # ------------------------------------------------------------------
    # Pattern B: each step → its own promoted TC
    # ------------------------------------------------------------------

    def _promote_pattern_b(self, raw_case: RawTestCase) -> List[PromotedTestCase]:
        result: List[PromotedTestCase] = []
        for step in raw_case.test_steps:
            ptc = PromotedTestCase(
                testcase_id=f"TC_{step.parent_case_num}_{step.step_num}",
                description="",  # filled downstream by json_builder
            )
            ptc.input_rows.extend(step.input_rows)
            ptc.output_rows.extend(step.output_rows)
            ptc.call_trace_rows.extend(step.call_trace_rows)
            result.append(ptc)
        return result

    # ------------------------------------------------------------------
    # Row parsers — word-position primary, text fallback secondary
    # ------------------------------------------------------------------

    def _parse_input_row(self, line: str) -> Optional[RawInputRow]:
        """
        Parse one input data row.

        x-column layout:
          Name:   x0 <  200
          Value:  x0 >= 250
        """
        if not line or self._is_section_header(line) or self._is_footer_line(line):
            return None

        # ── Primary: word-position ────────────────────────────────────
        y_key = self._find_y_for_line(line)
        if y_key is not None:
            words_at_y  = self._y_index.get(y_key, [])
            name_words  = [w["text"] for w in words_at_y if w["x0"] <  200]
            value_words = [w["text"] for w in words_at_y if w["x0"] >= 250]
            if name_words and value_words:
                name  = " ".join(name_words).strip()
                value = " ".join(value_words).strip()
                if not self._is_section_header(name):
                    return RawInputRow(name=name, value=value)

        # ── Fallback: 2+-space split ──────────────────────────────────
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) >= 2:
            name  = parts[0].strip()
            value = parts[-1].strip()
            if name and value and not self._is_section_header(name):
                return RawInputRow(name=name, value=value)

        # ── Last resort: single-space, 2-token, strict validation ─────
        tokens = line.strip().split()
        if len(tokens) == 2:
            name, value = tokens
            if re.match(r"^[A-Za-z_]\w*(?:\(\))?(?:\.[A-Za-z_]\w*)?$", name):
                return RawInputRow(name=name, value=value)

        return None

    def _parse_output_row(self, line: str) -> Optional[RawOutputRow]:
        """
        Parse one output data row.

        x-column layout:
          Name:     x0 <  200
          Actual:   200 ≤ x0 < 400
          Expected: 400 ≤ x0 < 530
        """
        if not line or self._is_section_header(line) or self._is_footer_line(line):
            return None

        # ── Primary: word-position ────────────────────────────────────
        y_key = self._find_y_for_line(line)
        if y_key is not None:
            words_at_y     = self._y_index.get(y_key, [])
            name_words     = [w["text"] for w in words_at_y if w["x0"] <  200]
            actual_words   = [w["text"] for w in words_at_y if 200 <= w["x0"] < 400]
            expected_words = [w["text"] for w in words_at_y if 400 <= w["x0"] < 530]
            if name_words:
                name     = " ".join(name_words).strip()
                actual   = " ".join(actual_words).strip()
                expected = " ".join(expected_words).strip()
                if not self._is_section_header(name):
                    return RawOutputRow(
                        name=name,
                        actual_value=actual,
                        expected_value=expected,
                    )
            elif actual_words or expected_words:
                # No name words at this y: continuation of a long name on the previous line.
                return RawOutputRow(
                    name="",
                    actual_value=" ".join(actual_words).strip(),
                    expected_value=" ".join(expected_words).strip(),
                )

        # ── Fallback: 2+-space split ──────────────────────────────────
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) >= 3:
            name     = parts[0].strip()
            actual   = parts[1].strip()
            expected = parts[2].strip()
            result   = parts[3].strip() if len(parts) > 3 else ""
            if name and not self._is_section_header(name):
                return RawOutputRow(
                    name=name,
                    actual_value=actual,
                    expected_value=expected,
                    result=result,
                )

        return None

    def _parse_call_trace_row(self, line: str) -> Optional[RawCallTraceRow]:
        """
        Parse one call-trace data row.

        Format: actual_func [count] expected_func [count] [result]
        Take first two tokens; validate as identifier + integer.
        """
        if not line or self._is_section_header(line) or self._is_footer_line(line):
            return None
        if line.startswith("©") or "TESSY" in line:
            return None

        tokens = line.strip().split()
        if len(tokens) >= 2:
            func      = tokens[0]
            count_str = tokens[1]
            if (
                re.match(r"^[A-Za-z_]\w*$", func)
                and re.match(r"^\d+$", count_str)
            ):
                return RawCallTraceRow(actual_function=func, count=count_str)

        return None

    # ------------------------------------------------------------------
    # Word-position helpers
    # ------------------------------------------------------------------

    def _find_y_for_line(self, line: str) -> Optional[int]:
        """
        Match a text line to its y-bucket by requiring ALL tokens of the
        line to be present in the words at that y-level.

        Using all tokens instead of just the first makes disambiguation
        reliable for short, repeated names like "a" and "b" that appear
        at multiple y-coordinates with different values beside them.
        e.g.  "a 127"  must match y=137 {a,127}  not y=233 {a,-128}.
        """
        tokens = line.strip().split()
        if not tokens:
            return None

        for y_key, words_at_y in self._y_index.items():
            texts = {w["text"] for w in words_at_y}
            if all(t in texts for t in tokens):
                return y_key

        # Fallback: match first token only (handles long lines where some
        # tokens may be split differently by pdfplumber)
        first = tokens[0]
        for y_key, words_at_y in self._y_index.items():
            if any(w["text"] == first for w in words_at_y):
                return y_key

        return None

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_lines(text: str) -> List[str]:
        return [ln.strip() for ln in text.splitlines() if ln.strip()]

    @staticmethod
    def _is_page_header(line: str) -> bool:
        """
        Return True for repeating page-header lines that TESSY prints at the
        top of every page (report title, date, function name).

        These must be silently skipped during cross-page parsing so they are
        not misidentified as test data.
        """
        page_header_patterns = [
            "TEST DETAILS REPORT",
        ]
        # Date pattern: e.g. "2025-05-15, 10:26:19+0530"
        if re.match(r"^\d{4}-\d{2}-\d{2},\s+\d{2}:\d{2}:\d{2}", line):
            return True
        return any(h.lower() in line.lower() for h in page_header_patterns)

    @staticmethod
    def _is_section_header(line: str) -> bool:
        headers = {
            "TEST DETAILS REPORT",
            "Name Input Value",
            "Name Actual Value Expected Value Result",
            "Test Step Call Trace",
            "Actual Function Count Expected Function Count Result",
        }
        return any(h.lower() in line.lower() for h in headers)

    @staticmethod
    def _is_footer_line(line: str) -> bool:
        return bool(RE_FOOTER_LINE.search(line or ""))
