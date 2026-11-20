import json
from conftest import FN
from utg.config import ProjectConfig
from utg.parser import CParser


def test_six_decisions_found_with_atoms(analysis):
    ir = analysis.ir
    assert [c.id for c in ir.conditions] == ["C1", "C2", "C3", "C4", "C5", "C6"]
    ops = {c.id: (c.logical_ops, [a.op for a in c.atoms]) for c in ir.conditions}
    assert ops["C1"] == ([], ["<="])
    assert ops["C2"] == (["&&"], ["<=", "=="])
    assert ops["C5"] == (["||"], ["!=", "!="])
    assert ops["C6"] == ([], ["!="])          # FALSE != b : macro-expanded operand handled


def test_dependencies_are_mocks_and_flags(analysis):
    calls = analysis.ir.calls
    assert set(calls) == {"sig_hwc_rx_cu_meas_11_get", "sig_hwc_tx_LS11_set", "sig_hwc_tx_LS11_flush"}
    assert all(c.requires_mock and not c.conditional for c in calls.values())
    assert calls["sig_hwc_rx_cu_meas_11_get"].return_used
    assert calls["sig_hwc_rx_cu_meas_11_get"].result_members == ["physical"]
    assert not calls["sig_hwc_tx_LS11_set"].return_used
    assert [p[0] for p in calls["sig_hwc_tx_LS11_set"].params] == ["b_LSOut11_250us"]


def test_types_resolved_by_clang_not_by_name(analysis):
    v = analysis.ir.variables
    assert (v["u8_time_LSOut11Short"].type.canonical, v["u8_time_LSOut11Short"].type.bits) == ("unsigned char", 8)
    assert v["f32_CuLSOut11"].type.kind == "float"
    assert analysis.ir.return_type.kind == "enum" and "RC_SUCCESS" in analysis.ir.return_type.enumerators
    assert analysis.ir.return_values == ["RC_SUCCESS"]


def test_sequential_dependency_recorded(analysis):
    uses = {(u.cond_id, u.var): u for u in analysis.ir.cond_uses}
    c2 = uses[("C2", "u8_time_LSOut11Short")]
    assert c2.modified_before and "entry" not in c2.defs           # both C1 branches redefine the counter
    assert any("++" in d for d in c2.defs) and any("= 0" in d for d in c2.defs)
    assert "entry" in uses[("C5", "f32_CuLSOut11CurrH")].defs       # conditional write: entry value still reaches


def test_roles_and_conditional_writes(analysis):
    v = analysis.ir.variables
    assert v["u8_time_LSOut11Short"].role == "state"
    assert v["f32_CuLSOut11"].role == "output"
    assert v["f32_LSOut11Short"].role == "input"
    assert v["f32_CuLSOut11Short"].conditionally_written


def test_ir_json_roundtrip_and_cfg(analysis):
    data = json.loads(analysis.ir.to_json())
    assert data["name"] == FN and len(data["conditions"]) == 6
    assert analysis.cfg_graph.syntactic_paths() == 48
    assert "digraph" in analysis.cfg_graph.to_dot()


def test_missing_declarations_are_reported_not_ignored(bench_copy):
    cfg = ProjectConfig.load(str(bench_copy / "project.json"))
    cfg.headers = [h for h in cfg.headers if not h.endswith("prelude.h")]
    ir = CParser(cfg).build_ir(FN)
    assert ir.unsupported, "unresolved declarations must be reported"
    assert any("unresolved" in u["reason"] or "undeclared" in u["reason"] or "error" in u["kind"] or u["kind"] == "diagnostic"
               for u in ir.unsupported)


def test_unsupported_constructs_reported(tmp_path):
    src = tmp_path / "s.c"
    src.write_text("static int a;\nint f(int x){ switch(x){case 1: a=1; break; default: a=2;} while(a<5){a++;} return a; }\n")
    cfg = ProjectConfig(source_file=str(src), target="")
    ir = CParser(cfg).build_ir("f")
    kinds = {u["kind"] for u in ir.unsupported}
    assert {"SWITCH_STMT", "WHILE_STMT"} <= kinds
