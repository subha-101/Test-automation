"""Function Intermediate Representation (Module 3).

Plain dataclasses only - no dependency on clang or z3 - so every other module can be unit-tested with
hand-built IR.  Executable logic is kept as a typed expression tree (``Expr``), never as a bare string;
``text`` is carried only for documentation / traceability.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


@dataclass
class SourceLoc:
    file: str = ""
    line: int = 0
    col: int = 0

    def __str__(self) -> str:
        return f"{self.file.split('/')[-1]}:{self.line}"


@dataclass
class TypeInfo:
    spelling: str = ""            # as written, e.g. "F32"
    canonical: str = ""           # resolved by Clang, e.g. "float"
    kind: str = "other"           # int | bool | float | enum | struct | pointer | void | other
    bits: int = 0
    signed: Optional[bool] = None
    is_const: bool = False
    enumerators: dict = field(default_factory=dict)      # name -> value   (kind == enum)
    fields: list = field(default_factory=list)           # [(name, TypeInfo)] (kind == struct)

    @property
    def is_numeric(self) -> bool:
        return self.kind in ("int", "bool", "float", "enum")


@dataclass
class Expr:
    kind: str                     # int_lit float_lit var_ref enum_const binary unary incdec assign cast call member cond unsupported
    type: TypeInfo = field(default_factory=TypeInfo)
    text: str = ""
    loc: SourceLoc = field(default_factory=SourceLoc)
    op: Optional[str] = None      # operator for binary / unary / assign / incdec
    name: Optional[str] = None    # var_ref / call / member / enum_const name
    value: Any = None             # literal value
    prefix: bool = False          # incdec only
    implicit: bool = False        # cast only
    children: list = field(default_factory=list)


@dataclass
class Stmt:
    id: int
    kind: str                     # decl | expr | if | return | unsupported
    loc: SourceLoc = field(default_factory=SourceLoc)
    text: str = ""
    expr: Optional[Expr] = None   # expr / return / decl-initialiser / if-condition
    var: Optional[str] = None     # decl
    cond_id: Optional[str] = None # if
    then: list = field(default_factory=list)
    els: list = field(default_factory=list)
    has_else: bool = False
    note: str = ""                # unsupported: reason


@dataclass
class VarInfo:
    name: str
    type: TypeInfo
    scope: str                    # global | static | local | param
    is_const: bool = False
    initial_value: Any = None     # known only for initialised declarations
    decl_loc: SourceLoc = field(default_factory=SourceLoc)
    read: bool = False
    written: bool = False
    read_before_write: bool = False
    conditionally_written: bool = False
    role: str = "internal"        # input | output | state | internal
    is_pointer: bool = False
    test_access: str = ""         # filled by the generator: pointer | direct | inaccessible


@dataclass
class CallInfo:
    name: str
    return_type: TypeInfo
    params: list                  # [(name, TypeInfo)]
    call_sites: list              # [SourceLoc]
    conditional: bool = False     # every call site sits inside a branch
    requires_mock: bool = True    # declared but not defined in the analysed translation unit
    return_used: bool = False     # value of the call feeds the function's logic
    void_cast: bool = False
    result_members: list = field(default_factory=list)  # struct members consumed from the return value
    inline_mock: bool = False                            # source already calls CppUTest for this event


@dataclass
class Atom:
    id: str                       # e.g. "C2.a1"
    text: str
    op: Optional[str]             # comparison operator, None for a plain boolean expression
    expr: Expr = None
    vars: list = field(default_factory=list)


@dataclass
class Condition:
    id: str                       # C1..Cn  (source order)
    text: str
    loc: SourceLoc
    expr: Expr
    atoms: list                   # [Atom]
    logical_ops: list             # ["&&"], ["||"] ...
    vars: list
    true_branch: list             # statement texts executed when TRUE
    false_branch: list            # statement texts executed when FALSE (empty if no else)
    has_else: bool = False


@dataclass
class VarDependency:
    target: str
    sources: list
    kind: str                     # data | control
    stmt: str
    loc: SourceLoc = field(default_factory=SourceLoc)


@dataclass
class CondUse:
    """Which definitions of a variable can reach a condition (sequential-dependency record)."""
    cond_id: str
    var: str
    defs: list                    # ["entry", "u8_time_LSOut11Short++ @source.c:25", ...]
    modified_before: bool


@dataclass
class FunctionIR:
    name: str
    return_type: TypeInfo
    args: list                    # [(name, TypeInfo)]
    signature: str
    loc: SourceLoc
    variables: dict = field(default_factory=dict)         # name -> VarInfo
    calls: dict = field(default_factory=dict)             # name -> CallInfo
    conditions: list = field(default_factory=list)        # [Condition]
    var_dependencies: list = field(default_factory=list)  # [VarDependency]
    cond_uses: list = field(default_factory=list)         # [CondUse]
    body: list = field(default_factory=list)              # [Stmt]
    return_values: list = field(default_factory=list)     # possible literal / enumerator returns
    unsupported: list = field(default_factory=list)       # [{kind, loc, reason, effect}]
    diagnostics: list = field(default_factory=list)       # [{severity, message, loc}]
    source_accessors: list = field(default_factory=list)  # source-defined pointer names
    link_dependencies: list = field(default_factory=list)  # other external calls in the included C file

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str, sort_keys=False)

    def condition(self, cid: str) -> Condition:
        for c in self.conditions:
            if c.id == cid:
                return c
        raise KeyError(cid)
