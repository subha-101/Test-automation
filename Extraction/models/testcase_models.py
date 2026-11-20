"""
models/testcase_models.py
--------------------------
Dataclass models for TESSY test report entities.

Changes:
  - ReturnValueCheck gains an optional `actual_return_value` field.
    This is populated for Pattern B PDFs where the Actual Value column
    records what the function really returned during execution.
  - TestCase drops the `steps` list — after promotion, steps are
    already merged into flat input/output/call_trace lists.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, List, Optional


# ---------------------------------------------------------------------------
# Input Models
# ---------------------------------------------------------------------------

@dataclass
class FunctionArgumentInput:
    """A direct parameter passed to the function under test."""
    type: str = "function_argument"
    name: str = ""
    value: Any = None


@dataclass
class MockReturnInput:
    """An internal dependency function mocked to return a value."""
    type: str = "mock_return"
    function: str = ""
    return_value: Any = None


@dataclass
class MockStructReturnInput:
    """An internal function returns a struct whose member holds a value."""
    type: str = "mock_struct_return"
    function: str = ""
    member: str = ""
    value: Any = None


# ---------------------------------------------------------------------------
# Output Models
# ---------------------------------------------------------------------------

@dataclass
class ReturnValueCheck:
    """Expected return value of the function under test.

    actual_return_value
        The value the function actually returned during test execution.
        Populated only for Pattern B PDFs (plain-argument style), where
        the Actual Value column explicitly records the function's return.
        None for Pattern A PDFs (mock-style) where actual values are not
        semantically meaningful for the JSON output.
    """
    type: str = "return_value_check"
    function: str = ""
    expected_value: Any = None
    actual_return_value: Any = None   # NEW — Pattern B


@dataclass
class GlobalVariableCheck:
    """Expected value of a global variable after execution."""
    type: str = "global_variable_check"
    name: str = ""
    expected_value: Any = None


# ---------------------------------------------------------------------------
# Call Trace Model
# ---------------------------------------------------------------------------

@dataclass
class CallTraceEntry:
    """Expected internal function call and its invocation count."""
    type: str = "internal_call_trace"
    function: str = ""
    count: int = 1


# ---------------------------------------------------------------------------
# Test Step (kept for internal use; not serialised directly)
# ---------------------------------------------------------------------------

@dataclass
class TestStep:
    """One test step — kept for potential future use / debug output."""
    step_id: str = ""
    repeat_count: int = 1
    inputs:     List[Any] = field(default_factory=list)
    outputs:    List[Any] = field(default_factory=list)
    call_trace: List[CallTraceEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Test Case (flat — steps have already been merged by TableExtractor.promote)
# ---------------------------------------------------------------------------

@dataclass
class TestCase:
    """
    A single normalised test case.

    For Pattern A PDFs the id is "TC_01".
    For Pattern B PDFs the id is "TC_1_1", "TC_1_2" etc.
    """
    testcase_id: str = ""
    description: str = ""
    inputs:     List[Any] = field(default_factory=list)
    outputs:    List[Any] = field(default_factory=list)
    call_trace: List[CallTraceEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Function-level Report
# ---------------------------------------------------------------------------

@dataclass
class FunctionReport:
    """Full extracted report for one function under test."""
    function_under_test: str = ""
    source_pdf:          str = ""
    project:             str = ""
    module:              str = ""
    total_testcases:     int = 0
    successful:          int = 0
    failed:              int = 0
    testcases: List[TestCase] = field(default_factory=list)
