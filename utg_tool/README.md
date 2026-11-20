# utg - deterministic C unit-test generator for CppUTest

Parses a C function with **Clang**, builds a typed IR, runs a **symbolic execution** of the function in
source order, solves inputs with **Z3**, and renders **CppUTest** tests with **Jinja2**.
No AI, no LLM, no network calls: the same sources + configuration always give byte-identical output
(checked in the tests, in one process and across processes with different `PYTHONHASHSEED`).
Each generation uses its own Z3 context so concurrent Streamlit sessions do not share native solver state.

## Install (Linux, Python 3.10+)
    pip install -r requirements.txt
    # optional, only for compile+run validation and *measured* coverage:
    sudo apt-get install g++ gcov            # or your platform's equivalent
    git clone --depth 1 https://github.com/cpputest/cpputest && cd cpputest
    cmake -S . -B build -DTESTS=OFF -DCMAKE_INSTALL_PREFIX=$HOME/cpputest && cmake --build build && cmake --install build
    export CPPUTEST_HOME=$HOME/cpputest      # or set "cpputest_home" in the project json
Without CppUTest/g++ the tool still generates and statically validates; it then states that compilation and
execution were **not** performed.

## Use
    python -m utg examples/benchmark/project.json --validate --out out     # CLI
    streamlit run app.py                                                    # GUI (6 pages)
    python -m pytest tests                                                  # the tool's own tests

### Project file (`project.json`) - the important keys
| key | meaning |
|---|---|
| `source_file`, `headers` | C file and the headers force-included before it, **in order** |
| `prelude_file` | declarations the source needs but does not contain (types, file-scope variables). Included before the source. |
| `include_dirs`, `defines`, `extra_flags`, `target` | compiler arguments. `target` defaults to `armv7m-none-eabi` so `unsigned long` is 32 bit |
| `static_access`, `global_access`, `pointer_pattern`, `access_overrides` | how a test reaches file-scope variables (`*p_{name}` by default for statics). `inaccessible` -> reported, never generated |
| `verify_params`, `strict_order`, `struct_return`, `bool_param_cast` | mock conventions |
| `int_pool`, `float_pool`, `assume_finite_floats` | preferred readable input values / finite-float assumption |

By default, generated mock expectations check calls and set return values without checking arguments.
To check arguments too, select **Verify mock parameters** on **File upload** before creating the project,
or set `"verify_params": true` in `project.json`. This does not change call ordering.
When using your own mocks, use the same setting: with checks off, the mocks should not report arguments.

On Windows, put **Clang-only** header paths in **Extra compiler flags**, e.g.
`-isystemC:\msys64\clang64\lib\clang\21\include -isystemC:\msys64\clang64\include`
with target `x86_64-w64-windows-gnu`. Keep project/CppUTest headers in **Include directories**.
The host `g++` used for validation must match the CppUTest libraries; it must not use Clang's system headers.

Missing includes: create stub headers at the paths the source expects (see `examples/benchmark/src/...`).
A missing include is a *fatal* Clang error that hides later errors, so the tool reports every unresolved
type as an explicit unsupported entry instead of continuing silently.

## Strategies
`branch` (decision outcomes), `condition` (atomic condition outcomes), `boundary` (operator rules of the spec:
`<=` -> less/equal/greater, `==`/`!=` -> equal/not-equal, plus explicit unsigned wrap-around scenarios).
Default = all three. Boundary targets are **context-qualified**: the timer comparison is exercised both after
the counter was incremented and after it was reset.

## Honest status (see docs/DESIGN.md for details)
Implemented: phase 1, most of phase 2 (nested/compound conditions, sequential state, float semantics, Z3,
boundaries), the validation engine from phase 4 (static, compile, execute, gcov).
Also supported: named scalar struct fields, file-scope object addresses passed to mocks (identity only;
generated mocks do not write through pointers), short-circuit mock calls in `if` conditions, representable
float-to-integer conversions up to 32 bits, and CppUTest's inline `mock_c()->actualCall("label")->returnIntValueOrDefault(...)`
pattern. A straight-line function gets a test for its observable effects even if it has no coverage targets.

Functions with scalar function-local statics are modeled from their C initializers only. UTG validation
runs each such case in a fresh process. For downloaded tests, run one case per process with CppUTest
`-st <group>.<test>`; running all cases in one process does not reset local static state.

**Not implemented:** MC/DC, switch, loops, general pointers/arrays or writes through mock pointers,
calls to functions defined in the same file, learning formatting from a reference test, and editing/adding
scenarios in the GUI (removal works). Unsupported operations that stop execution are reported on the
scenario page separately from a genuine zero-feasible-path result.
