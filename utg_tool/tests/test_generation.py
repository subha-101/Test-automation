import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from utg.pipeline import generate
from utg.scenarios import ScenarioGenerator
from utg.symexec import SymbolicExecutor


def test_all_feasible_targets_covered_and_no_redundancy(generated):
    r = generated.result
    assert not r.truncated and r.path_count == 48
    # the only uncovered targets are the ones Z3 proves impossible: "Max < counter" right after the counter
    # was reset to 0 (unsigned value below 0)
    assert sorted(t.key[1] for t, _ in r.uncovered) == ["C2.a1", "C4.a1"]
    assert all(t.key[2] == "lt" and t.key[3][0][1] is False for t, _ in r.uncovered)
    assert all("proven infeasible" in why for _, why in r.uncovered)
    open_keys = {t.key for t, _ in r.uncovered}
    union = set().union(*[s.covers for s in r.scenarios])
    assert {t.key for t in r.targets} - open_keys <= union
    for i, s in enumerate(r.scenarios):          # every scenario contributes something no other one provides
        others = set().union(*[o.covers for j, o in enumerate(r.scenarios) if j != i])
        assert not s.covers <= others


def test_boundary_rules(generated):
    keys = {t.key[:3] for t in generated.result.targets}
    for rel in ("lt", "eq", "gt"):                      # <=  -> less, equal, greater
        assert ("R", "C1.a1", rel) in keys
    assert {("R", "C2.a2", "eq"), ("R", "C2.a2", "ne")} <= keys    # == -> equal / not equal
    assert {("R", "C6.a1", "eq"), ("R", "C6.a1", "ne")} <= keys    # != -> equal / not equal


def test_boundary_targets_are_context_qualified(generated):
    texts = [t.text for t in generated.result.targets if t.key[1] == "C2.a1" and t.key[2] == "eq"]
    assert any("after C1=TRUE" in x for x in texts) and any("after C1=FALSE" in x for x in texts)


def test_sequential_semantics_counter_after_c1(generated):
    """C2 must see the counter AFTER C1: a scenario with C1 true, counter=Max-1 makes C2's first atom true."""
    hit = False
    for s in generated.result.scenarios:
        d = dict(s.decisions)
        if d["C1"] and s.inputs.get("u8_time_LSOut11Short", 0) + 1 == s.inputs.get("u8_MaxTime_LSOut11Short", -1):
            assert ("O", "C2.a1", "true") in s.covers
            hit = True
        if not d["C1"]:
            assert s.expected_vars["u8_time_LSOut11Short"] == 0          # reset branch
        if d["C1"] and s.inputs.get("u8_time_LSOut11Short", 0) < 255:
            assert s.expected_vars["u8_time_LSOut11Short"] == s.inputs.get("u8_time_LSOut11Short", 0) + 1
    assert hit


def test_wraparound_only_in_explicit_scenarios(generated):
    wrapping = [s for s in generated.result.scenarios if ("W", "W@18:7", "wrap") in s.covers
                or ("W", "W@38:7", "wrap") in s.covers or any(k[0] == "W" for k in s.covers)]
    assert len(wrapping) == 2
    for s in generated.result.scenarios:
        if s not in wrapping:
            assert 255 not in s.inputs.values()


def test_mock_expectations_only_for_executed_calls_in_order(generated):
    for s in generated.result.scenarios:
        assert [e.name for e in s.events] == ["sig_hwc_rx_cu_meas_11_get", "sig_hwc_tx_LS11_set", "sig_hwc_tx_LS11_flush"]
        out = s.expected_vars
        b = dict(s.decisions)
        expect_true = (not b["C5"]) and b.get("C6", False)
        assert s.events[1].args[0][2] == (1 if expect_true else 0)


def test_float_inputs_are_finite_and_signed_zero_free(generated):
    import math
    for s in generated.result.scenarios:
        for v in list(s.inputs.values()) + list(s.expected_vars.values()):
            if isinstance(v, float):
                assert math.isfinite(v) and math.copysign(1, v) == 1 or v != 0


def test_determinism(cfg, analysis):
    a = generate(cfg, analysis).code
    b = generate(cfg, analysis).code
    assert a == b


def test_concurrent_generations_preserve_deterministic_output(tmp_path):
    cfg, a = _analyse_source(tmp_path, """
        int subject(float x, unsigned int y) {
            if (x + 0.5f <= 0.0f && y == 7u) return 1;
            return 0;
        }
    """)
    expected = generate(cfg, a)
    assert len(expected.result.scenarios) > 1
    ready = Barrier(2, timeout=10)

    def run():
        ready.wait()
        return generate(cfg, a)

    with ThreadPoolExecutor(max_workers=2) as pool:
        runs = [pool.submit(run) for _ in range(2)]
        for future in runs:
            actual = future.result(timeout=30)
            assert actual.result == expected.result
            assert actual.code == expected.code


def test_mcdc_not_silently_accepted(cfg, analysis):
    with pytest.raises(ValueError, match="MC/DC"):
        ScenarioGenerator(analysis.ir, cfg).generate(("mcdc",))


def test_branch_only_strategy_is_smaller(cfg, analysis):
    small = generate(cfg, analysis, ("branch",)).result
    assert 0 < len(small.scenarios) < len(generate(cfg, analysis).result.scenarios)
    assert all(t.kind == "decision" for t in small.targets)


def test_inaccessible_static_is_reported_and_not_emitted(cfg, bench_copy):
    from utg.config import ProjectConfig
    from utg.pipeline import analyse_function
    c = ProjectConfig.load(str(bench_copy / "project.json"))
    c.static_access = "inaccessible"
    a = analyse_function(c, "rc_lsout11_out_250us")
    assert a.access_issues and "not accessible" in a.access_issues[0]
    g = generate(c, a)
    assert g.report.blocked and "*p_" not in g.code and "direct" not in g.code.lower().split("note")[0]


def _analyse_source(tmp_path, text, name="subject"):
    from utg.config import ProjectConfig
    from utg.pipeline import analyse_function

    source = tmp_path / "source.c"
    source.write_text(text)
    cfg = ProjectConfig(source_file=str(source))
    return cfg, analyse_function(cfg, name)


def test_straight_line_struct_write_and_mock_address(tmp_path):
    cfg, a = _analyse_source(tmp_path, """
        typedef struct { int value; int array[4]; } State;
        static State state;
        void observe(const State *object);
        int subject(void) { state.value = 5; observe(&state); return state.value; }
    """)
    cfg.verify_params = True
    g = generate(cfg, a)
    assert g.result.path_count == 1
    (sc,) = g.result.scenarios
    assert sc.inputs["state.value"] != 5
    assert sc.expected_vars == {"state.value": 5}
    assert sc.expected_ret == 5
    assert '.withConstPointerParameter("object", static_cast<const void*>(&(*p_state)))' in g.code
    assert "CHECK_EQUAL(5, (*p_state).value);" in g.code
    assert not g.report.blocked


def test_default_mock_expectations_omit_pointer_and_scalar_parameters(tmp_path):
    cfg, a = _analyse_source(tmp_path, """
        static int value;
        float read(const int *object, int index);
        void observe(int index);
        float subject(void) { observe(2); return read(&value, 3); }
    """)
    g = generate(cfg, a)
    assert not g.report.blocked
    assert 'mock().expectOneCall("observe");' in g.code
    assert 'mock().expectOneCall("read").andReturnValue(0.0f);' in g.code
    assert "Parameter(" not in g.code
    assert "mock().strictOrder();" in g.code


def test_short_circuit_mock_and_local_static_share_no_state(tmp_path):
    cfg, a = _analyse_source(tmp_path, """
        _Bool probe(void);
        int subject(int gate) {
            static int count = 4;
            if (gate /* local gate */ || probe()) ++count;
            return count;
        }
    """)
    g = generate(cfg, a)
    assert g.result.path_count == 3
    assert {bool(sc.events) for sc in g.result.scenarios} == {False, True}
    for sc in g.result.scenarios:
        assert bool(sc.events) == (sc.inputs["gate"] == 0)
        assert sc.expected_ret == (5 if sc.decisions[0][1] else 4)
        assert "count" not in sc.inputs
    header = g.code.split("*/", 1)[0].splitlines()
    assert r" * \brief Unit tests for subject()." in header
    assert r" * \author Subhasish Singha <subhasish.singha1@kiongroup.com>" in header
    assert not any("NOTE:" in line or "generated by utg" in line for line in header)
    assert any("fresh process" in note for note in g.report.notes)
    assert "local gate * /" in g.code
    assert ".andReturnValue(static_cast<long>(1))" in g.code


def test_defined_float_cast_and_infeasible_float_cast(tmp_path):
    cfg, a = _analyse_source(tmp_path, "int subject(void) { return (int)-3.75f; }")
    assert generate(cfg, a).result.scenarios[0].expected_ret == -3
    cfg, a = _analyse_source(tmp_path, "short subject(void) { return (short)40000.0f; }")
    result = generate(cfg, a).result
    assert not result.blocked and result.path_count == 0


def test_unsupported_operation_is_not_reported_as_infeasible(tmp_path):
    cfg, a = _analyse_source(tmp_path, "int subject(int *p) { return *p; }")
    g = generate(cfg, a)
    assert g.result.path_count == 0 and not g.result.scenarios
    assert g.result.blocked["loc"].endswith("source.c:1")
    assert "unsupported type" in g.result.blocked["reason"]


def test_inline_cpputest_mock_hook_preserves_mock_order(tmp_path):
    cfg, a = _analyse_source(tmp_path, """
        typedef struct { int (*returnIntValueOrDefault)(int); } MockActualCall_c;
        typedef struct { MockActualCall_c *(*actualCall)(const char *); } MockSupport_c;
        MockSupport_c *mock_c(void);
        int probe(void);
        #define CUSTOM_HOOK(x) mock_c()->actualCall("CUSTOM_HOOK")->returnIntValueOrDefault(x)
        int subject(void) { int value = probe(); return CUSTOM_HOOK(value); }
    """)
    g = generate(cfg, a)
    (sc,) = g.result.scenarios
    assert [ev.name for ev in sc.events] == ["probe", "CUSTOM_HOOK"]
    assert sc.expected_ret == sc.events[-1].ret_value
    assert 'expectOneCall("CUSTOM_HOOK")' in g.code
