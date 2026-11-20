# Design and first-task answers (numbers are from the real benchmark run)

## 1-2. Inspected input and dependencies
`rc_lsout11_out_250us(void)` returns `RC` (enum, `RC_SUCCESS` is the only return). Six decisions C1..C6 (8 atomic
conditions), three mocked dependencies, each called once and unconditionally:
`sig_hwc_rx_cu_meas_11_get()` (returns struct, member `.physical` is consumed), `sig_hwc_tx_LS11_set(BO)`,
`sig_hwc_tx_LS11_flush()`. Ten file-scope variables are used; they are **not declared** anywhere in the uploaded
files, nor is `volt_ratio_physical_t` (`types_common.h` etc. were not provided). The benchmark therefore ships
`prelude.h` whose types are *assumptions* (F32/U8/BO, `struct {F32 physical;}`) and stub headers for the three
missing includes. Replace them with the real declarations.

## 3. How Clang parses it
`CParser` builds an in-memory translation unit `#include headers... #include prelude #include source.c` and parses
it with libclang (`--target=armv7m-none-eabi`). Types come from `Type.get_canonical()` (typedef `U8` -> `unsigned char`,
8 bit, unsigned; `RC` -> enum with its enumerators), scopes from `semantic_parent` / `storage_class`, call
declarations from `Cursor.referenced`. Implicit conversions are materialised as `cast` nodes, so C integer
promotion (`unsigned char` -> `int`) is explicit in the IR. Two libclang weaknesses are handled explicitly:
macro-expanded nodes have no tokens (`TRUE` = `(!0)`, `FALSE`): operators are read from the source bytes between
operand extents and constants are folded with `clang_Cursor_Evaluate`; a fatal diagnostic hides later errors, so
unresolved types become blocking "unsupported" entries.

## 4. Function IR (`utg/ir.py`, JSON via `FunctionIR.to_json()`)
`FunctionIR{name, return_type, args, signature, loc, variables{VarInfo}, calls{CallInfo}, conditions[Condition{id,
text, atoms[Atom], logical_ops, vars, true_branch, false_branch}], var_dependencies, cond_uses, body[Stmt],
return_values, unsupported, diagnostics}`. Executable logic is a typed `Expr` tree, never only a string.

## 5. The six decisions
Each `Condition` keeps the `Expr` tree plus flattened `Atom`s, e.g. C2 =
`binary(&&, binary(<=, cast(int, var u8_MaxTime_LSOut11Short), cast(int, var u8_time_LSOut11Short)), binary(==, float_lit 0.0, var f32_CuLSOut11Short))`
-> atoms `C2.a1`, `C2.a2`. C1/C3 one atom each, C5 `||` of two `!=`, C6 `FALSE != b_LSOut11_10ms`.
All six were found without any information about their content being supplied.

## 6. Input constraints
Symbolic execution creates a Z3 symbol for each file-scope value when it is first read (`in__<var>`) and for each
mock return (`ret__<callee>_<n>[__member]`). Integers are bit-vectors of the Clang-resolved width/sign, floats are
IEEE `Float32` terms (`fpLEQ`, `fpEQ`, ...), so C float semantics hold (NaN/Inf are excluded by default and stated).
A target such as "C1.a1: lhs equal rhs after ..." becomes `pathcondition AND fpEQ(lhs, rhs)`.
Z3 only decides satisfiability; values are chosen by a fixed, reproducible ladder (pool values, then values relative to
already pinned ones, then a minimising optimum) so output never depends on Z3's arbitrary models.

## 7. Sequential modelling
Statements run in order on one state; `u8_time++` in C1's branch changes the term that C2 later reads, so C2's
constraint is over the *post-increment* value (`ite`-free because each path is explored separately). Branches fork
the state and infeasible forks are pruned. `cond_uses` records which definitions reach each condition
(C2 sees `++` and `= 0`; C5 sees `entry` and the assignment). Benchmark: 48 feasible paths.

## 8. Mocks and expected results
Only calls executed on the scenario's path are emitted, in order (`strictOrder`). Return values and the checked
`b_LSOut11_250us` argument come from the model; expected variables are the final symbolic state evaluated under it.
The tests were then **executed against the real source**: 12/12 pass, gcov 24/24 lines, 18/18 branches; 8 of 9
hand-made mutants are killed.

## Findings from inspecting the output (and what was changed)
1. Boundaries reached through unsigned wrap-around -> wrap is now a separate, explicit target; wrapped scenarios earn no
   ordinary boundary credit.
2. Write-only state is initialised to a value different from its expected result so resets are observable.
3. Z3 fall-back values differed between runs -> replaced by the deterministic ladder.
4. `TRUE` is `bool` but `FALSE` is `int` in C++, which breaks CppUTest parameter matching -> `bool_param_cast`.
5. Boundary targets are context-qualified by earlier decisions that redefine their operands.
6. Two targets are reported as *proven infeasible* ("Max < counter" right after the counter was reset to 0).

## Known limitations
* MC/DC missing: mutant `||` -> `&&` in C5 survives (strict xfail test documents it).
* Thresholds are mostly 0/1/2: valid, but not realistic values; the tool cannot know them.
* Accessor `p_<name>`, `.withParameter(...)`, `.andReturnValue(&local)` are *conventions assumed from the spec example*.
  The validation harness is the tool's own; your project's mocks may differ.
* Validated on x86-64 g++ while parsing for ARM 32-bit; identical for `U8`/`float`, not proven for 32-bit `long` arithmetic.
* gcov branch counts include compiler-generated short-circuit branches.
* Scenario editing/adding in the GUI, reference-file formatting learning, MC/DC, switch, loops: remaining work.
