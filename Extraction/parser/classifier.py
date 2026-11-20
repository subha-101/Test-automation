"""
parser/classifier.py
---------------------
Semantic classification of raw extracted rows into typed model instances.

INPUT ROWS
----------
  mock_struct_return  — name matches  func().member
  mock_return         — name ends with ()
  function_argument   — plain identifier (no parens)

OUTPUT ROWS
-----------
  return_value_check      — name ends with () (function call)
  global_variable_check   — plain identifier

  For Pattern B PDFs the output row contains:
    name         = "max2_s8()"  (function under test, with parens)
    actual_value = "127"        (what the function actually returned)
    expected_value = "127"      (what the test expected)

  When the stripped function name (without parens) matches function_under_test,
  actual_return_value is populated on the ReturnValueCheck object.

CALL TRACE ROWS
---------------
  Always → internal_call_trace
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional, Union

from models.testcase_models import (
    CallTraceEntry,
    FunctionArgumentInput,
    GlobalVariableCheck,
    MockReturnInput,
    MockStructReturnInput,
    ReturnValueCheck,
)
from parser.table_extractor import RawCallTraceRow, RawInputRow, RawOutputRow

logger = logging.getLogger(__name__)

DEFAULT_VALUES: dict[str, Any] = {
    "uint8_t":  0,
    "uint16_t": 0,
    "uint32_t": 0,
    "int":      0,
    "float":    0.0,
    "double":   0.0,
    "bool":     False,
    "char*":    "NULL",
}
_DEFAULT_NUMERIC = 0

RE_FUNC_CALL    = re.compile(r"^(?P<func>[A-Za-z_]\w*)\s*\([^)]*\)$")
RE_STRUCT_RETURN = re.compile(
    r"^(?P<func>[A-Za-z_]\w*)\s*\([^)]*\)\.(?P<member>[A-Za-z_]\w*)$"
)
RE_IDENTIFIER   = re.compile(r"^[A-Za-z_]\w*$")
# Matches scoped static names like  FuncName::var_name#N  →  captures var_name
RE_SCOPED_VAR   = re.compile(r"^[^:]+::(?P<var>[^#]+)#")


class InputClassifier:
    """Classifies a RawInputRow into a typed input model."""

    def classify(
        self, row: RawInputRow
    ) -> Union[FunctionArgumentInput, MockReturnInput, MockStructReturnInput]:

        name  = row.name.strip()
        value = self._parse_value(row.value)

        # Priority 1: struct member return  → func().member
        m = RE_STRUCT_RETURN.match(name)
        if m:
            logger.debug("Classified '%s' as mock_struct_return", name)
            return MockStructReturnInput(
                function=m.group("func"),
                member=m.group("member"),
                value=value,
            )

        # Priority 2: mocked function return  → func()
        m = RE_FUNC_CALL.match(name)
        if m:
            logger.debug("Classified '%s' as mock_return", name)
            return MockReturnInput(
                function=m.group("func"),
                return_value=value,
            )

        # Priority 3: plain function argument
        # Scoped static: FuncName::var_name#N  →  *p_var_name
        m = RE_SCOPED_VAR.match(name)
        if m:
            name = "*p_" + m.group("var").strip()
        logger.debug("Classified '%s' as function_argument", name)
        return FunctionArgumentInput(
            name=name,
            value=value if value is not None else _DEFAULT_NUMERIC,
        )

    @staticmethod
    def _parse_value(raw: str) -> Any:
        """Convert a raw string value to the most appropriate Python type."""
        raw = raw.strip()
        if not raw:
            return _DEFAULT_NUMERIC

        # false_val before true_val so "false" wins
        if raw.lower() in {"false", "false_val"}:
            return 0

        # Integer (handles negative values like -128, -100)
        try:
            return int(raw)
        except ValueError:
            pass

        # Float
        try:
            return float(raw)
        except ValueError:
            pass

        if raw.upper() == "NULL":
            return "NULL"

        return raw


class OutputClassifier:
    """Classifies a RawOutputRow into a typed output model."""

    def classify(
        self,
        row: RawOutputRow,
        function_under_test: str = "",
    ) -> Union[ReturnValueCheck, GlobalVariableCheck]:
        """
        Parameters
        ----------
        row:
            The raw output row.
        function_under_test:
            The name of the function being tested (from report metadata).
            Used to detect Pattern B output rows where actual_value is the
            real return value of the function.
        """
        name     = row.name.strip()
        expected = InputClassifier._parse_value(row.expected_value)
        actual   = InputClassifier._parse_value(row.actual_value) if row.actual_value else None

        # Function return check  →  name ends with ()
        m = RE_FUNC_CALL.match(name)
        if m:
            func_name = m.group("func")
            logger.debug("Classified output '%s' as return_value_check", name)

            # Pattern B: when the output name is the function under test,
            # actual_value carries what the function really returned.
            actual_return = None
            if function_under_test and func_name == function_under_test:
                actual_return = actual

            return ReturnValueCheck(
                function=func_name,
                expected_value=expected,
                actual_return_value=actual_return,
            )

        # Global variable check
        # Scoped static: FuncName::var_name#N  →  *p_var_name
        m = RE_SCOPED_VAR.match(name)
        if m:
            name = "*p_" + m.group("var").strip()
            # Fallback: if expected_value is absent (PDF row wrap), use actual_value.
            if not row.expected_value and actual is not None:
                expected = actual
        logger.debug("Classified output '%s' as global_variable_check", name)
        return GlobalVariableCheck(
            name=name,
            expected_value=expected,
        )


class CallTraceClassifier:
    """Classifies a RawCallTraceRow into a CallTraceEntry."""

    def classify(self, row: RawCallTraceRow) -> CallTraceEntry:
        func = row.actual_function.strip()
        try:
            count = int(row.count.strip())
        except (ValueError, AttributeError):
            count = 1
            logger.warning("Could not parse call count for '%s', defaulting to 1", func)

        logger.debug("Classified call-trace '%s' count=%d", func, count)
        return CallTraceEntry(function=func, count=count)
