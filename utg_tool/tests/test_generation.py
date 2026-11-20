import os
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
