"""Regression tests: HW4 numbers, hand checks, and the new tools' contracts."""
import math

import pytest

from dfm_tools.hw4_tools import (cnc_cutting_parameters, end_mill_reach_check,
                                 fdm_print_estimate, process_cost_breakeven)
from dfm_tools.new_tools import fdm_feature_check, fit_allowance_check


def test_cnc_matches_sandvik_hand_calc():
    r = cnc_cutting_parameters(10, 3, "aluminum_6061", 5, 5)
    n = 300 * 1000 / (math.pi * 10)
    vf = 0.08 * n * 3
    assert r["spindle_rpm"] == pytest.approx(n, rel=1e-3)
    assert r["feed_mm_min"] == pytest.approx(vf, rel=1e-3)
    assert r["mrr_cm3_min"] == pytest.approx(5 * 5 * vf / 1000, rel=1e-3)
    assert r["spindle_power_W"] == pytest.approx(5 * 5 * vf * 700 / 60e6 * 1000, rel=1e-3)


def test_reach_matches_cantilever_and_hw4():
    r = end_mill_reach_check(6, 22, "aluminum_6061", internal_corner_radius_mm=2)
    assert r["L_over_D"] == 4.0 and r["deflection_mm"] == pytest.approx(0.011, abs=5e-4)
    assert r["corner_ok"] is False and r["largest_tool_for_corner_mm"] == pytest.approx(3.64, abs=0.01)
    I = math.pi * 4.8**4 / 64
    assert end_mill_reach_check(6, 22, force_N=100)["deflection_mm"] == pytest.approx(100 * 24**3 / (3 * 600000 * I), rel=1e-3)


def test_fdm_and_cost_match_hw4():
    f = fdm_print_estimate(48, 110, 30, "PLA", overhang_deg=60)
    assert (f["print_time_h"], f["mass_g"], f["cost_usd"], f["supports_needed"]) == (pytest.approx(1.68, abs=0.005), 26.3, 7.29, True)
    d = process_cost_breakeven(48, 60, 40, 30, 200)          # HW4 run: area omitted -> default
    assert d["cost_per_part_usd"]["FDM (PLA)"] == pytest.approx(14.27, abs=0.01)
    assert d["cost_per_part_usd"]["CNC (6061-T6 Al)"] == pytest.approx(64.12, abs=0.05)
    assert any(abs(x["quantity"] - 610) <= 5 for x in d["crossovers"])
    assert cnc_cutting_parameters(25, 3, "aluminum_6061")["spindle_rpm"] == pytest.approx(3820, abs=1)
    c = process_cost_breakeven(48, 60, 40, 30, 200, surface_area_cm2=110)
    assert c["cost_per_part_usd"]["FDM (PLA)"] == pytest.approx(13.96, abs=0.01)
    assert c["cost_per_part_usd"]["Injection molding (ABS)"] == pytest.approx(42.16, abs=0.02)
    assert c["cost_per_part_usd"]["CNC (6061-T6 Al)"] == pytest.approx(61.46, abs=0.05)
    assert any(x["quantity"] == 624 for x in c["crossovers"])


def test_fit_anodize_shrinks_hole():
    r = fit_allowance_check(10, "press", "cnc", coating="anodize_type_iii")
    assert r["systematic_shift_mm"] == pytest.approx(-0.05)
    assert r["expected_clearance_mm"] == {"min": -0.075, "max": -0.025}
    assert r["recommended_cad_diameter_mm"] == pytest.approx(10.0275, abs=1e-3)


def test_fit_override_makes_target_achievable():
    r = fit_allowance_check(10, "press", "cnc", cad_diameter_mm=10.028, coating="anodize_type_iii", process_tolerance_mm=0.01)
    assert r["verdict"] == "meets target" and r["target_achievable_with_this_tolerance"]


def test_fit_rejects_coating_on_plastic():
    with pytest.raises(ValueError, match="metal finishes"):
        fit_allowance_check(10, "press", "fdm", material="PLA", coating="anodize_type_ii")


def test_feature_check_sub_nozzle_wall_fails():
    r = fdm_feature_check(0.2, "PETG")
    assert r["overall"] == "not printable as designed" and r["checks"][0]["status"] == "fail"


def test_feature_check_orientation_advice():
    r = fdm_feature_check(1.0, "PLA", load_direction="across_layers", applied_stress_mpa=15)
    assert "Reorient" in r["orientation_advice"]
    strength = [c for c in r["checks"] if c["check"] == "layer_strength"][0]
    assert strength["failure_mode"].startswith("interlayer") and "criterion" in strength


def test_range_errors_are_readable():
    with pytest.raises(ValueError, match="valid range 1–25"):
        end_mill_reach_check(40, 22)
