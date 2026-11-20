"""Project configuration (Module 1): compiler arguments, prelude, access conventions, mock conventions."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class ProjectConfig:
    # ---- parsing -------------------------------------------------------------------------------------------
    source_file: str = ""
    headers: list = field(default_factory=list)            # force-included before the source, in order
    include_dirs: list = field(default_factory=list)
    defines: list = field(default_factory=list)            # ["UNIT_TESTING", "FOO=1"]
    extra_flags: list = field(default_factory=list)
    # ARM Cortex-M so that `unsigned long` is 32 bit like on the real target.  Set "" to use the host ABI.
    target: str = "armv7m-none-eabi"
    prelude_file: str = ""                                 # declarations the source relies on but does not declare
    # ---- input generation ---------------------------------------------------------------------------------
    assume_finite_floats: bool = True                      # exclude NaN/Inf from float inputs
    int_pool: list = field(default_factory=lambda: [0, 1, 2, 3, 5, 10])
    float_pool: list = field(default_factory=lambda: [0.0, 1.0, 2.0, 5.0, 10.0, -1.0, 0.5])
    max_paths: int = 512
    # ---- test-file conventions ---------------------------------------------------------------------------
    test_group: str = ""                                   # default: function name
    testcase_prefix: str = "Testcase"
    function_index: int = 1                                # Testcase_<function_index>_<n>
    emit_test_group: bool = True
    includes: list = field(default_factory=list)           # #include lines of the generated test file
    float_tolerance: str = "0.0001"
    bool_param_cast: str = "int"                       # TRUE is bool but FALSE is int in C++: cast for CppUTest
    boolean_types: list = field(default_factory=lambda: ["BO"])   # typedefs rendered as TRUE / FALSE
    # How a test reaches file-scope variables.  `static_access` is used for `static` file-scope variables,
    # `global_access` for external ones.  pointer -> "*p_{name}", direct -> "{name}" (only valid when the test
    # file #includes the .c file), inaccessible -> reported, no code generated.
    static_access: str = "pointer"
    global_access: str = "direct"
    pointer_pattern: str = "*p_{name}"
    access_overrides: dict = field(default_factory=dict)   # {var_name: pattern or "inaccessible"}
    # ---- mock conventions ----------------------------------------------------------------------------------
    strict_order: bool = True                              # mock().strictOrder() when >1 mocked call
    verify_params: bool = True                             # .withParameter(<declared param name>, value)
    struct_return: str = "pointer"                         # pointer: .andReturnValue(&local)   (project convention)
    mock_overrides: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: str) -> "ProjectConfig":
        base = os.path.dirname(os.path.abspath(path))
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        cfg = cls(**raw)
        cfg.resolve_paths(base)
        return cfg

    def resolve_paths(self, base: str) -> None:
        def r(p: str) -> str:
            return p if (not p or os.path.isabs(p)) else os.path.normpath(os.path.join(base, p))
        self.source_file = r(self.source_file)
        self.headers = [r(h) for h in self.headers]
        self.include_dirs = [r(d) for d in self.include_dirs]
        self.prelude_file = r(self.prelude_file)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)
