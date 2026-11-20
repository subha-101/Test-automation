# utg - deterministic C unit-test generator for CppUTest

Parses a C function with **Clang**, builds a typed IR, runs a **symbolic execution** of the function in
source order, solves inputs with **Z3**, and renders **CppUTest** tests with **Jinja2**.
No AI, no LLM, no network calls: the same sources + configuration always give byte-identical output
(checked in the tests, in one process and across processes with different `PYTHONHASHSEED`).

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
**Not implemented:** MC/DC, switch, loops, pointers/arrays, calls to functions defined in the same file,
float->int conversion, learning formatting from an uploaded reference test, editing/adding scenarios in the GUI
(removal works). These are reported as *unsupported* when met - never skipped silently.
