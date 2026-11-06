"""Homework 4 analytical tools (CNC cutting, end-mill reach, FDM estimate, process cost).

Pure functions: inputs in SI-style shop units (mm, cm^3, USD), outputs as plain dicts.
Every function validates its own inputs and raises ``ValueError`` with a readable
message when an input is outside the documented range, so any client (the HW4
OpenAI agent or the HW5 MCP server) gets the same contract.
"""
from __future__ import annotations

import math

from scipy.optimize import brentq

# ---------------------------------------------------------------------------
# Material data (catalog mid-range values; carbide tooling)
#   vc  : cutting speed, m/min
#   fz_per_D : chip load per tooth as a fraction of tool diameter (fz = k * D), mm/mm
#   kc  : specific cutting energy, N/mm^2 (Kalpakjian & Schmid mid-range)
#   rho : density, g/cm^3 ; usd_kg : bar-stock price, USD/kg
# ---------------------------------------------------------------------------
CNC_MATERIALS = {
    "aluminum_6061": dict(vc=300.0, fz_per_D=0.008, kc=700.0, rho=2.70, usd_kg=8.8, E_label="6061-T6 Al"),
    "steel_1018": dict(vc=120.0, fz_per_D=0.005, kc=2000.0, rho=7.87, usd_kg=4.0, E_label="1018 steel"),
    "stainless_304": dict(vc=80.0, fz_per_D=0.004, kc=2500.0, rho=8.00, usd_kg=8.0, E_label="304 stainless"),
    "titanium_6al4v": dict(vc=50.0, fz_per_D=0.004, kc=1700.0, rho=4.43, usd_kg=40.0, E_label="Ti-6Al-4V"),
    "pom_acetal": dict(vc=250.0, fz_per_D=0.010, kc=300.0, rho=1.41, usd_kg=12.0, E_label="POM (acetal)"),
}

FDM_MATERIALS = {
    # rho g/cm^3, usd_kg filament price
    "PLA": dict(rho=1.24, usd_kg=22.0),
    "PETG": dict(rho=1.27, usd_kg=25.0),
    "ABS": dict(rho=1.04, usd_kg=22.0),
    "nylon": dict(rho=1.14, usd_kg=50.0),
}

CARBIDE_E_MPA = 600_000.0  # 600 GPa
SHOP_RATE_CNC = 90.0       # USD/h
SHOP_RATE_MOLD = 60.0      # USD/h
FDM_MACHINE_RATE = 4.0     # USD/h
FDM_POST_RATE = 40.0       # USD/h


def _check(name: str, value: float, lo: float, hi: float, unit: str) -> None:
    if value is None or not (lo <= value <= hi) or (isinstance(value, float) and math.isnan(value)):
        raise ValueError(f"{name}={value} {unit} is outside the valid range {lo}–{hi} {unit}.")


def _material(table: dict, key: str, kind: str) -> dict:
    if key not in table:
        raise ValueError(
            f"Unsupported {kind} material '{key}'. Supported: {', '.join(sorted(table))}."
        )
    return table[key]


# ---------------------------------------------------------------------------
# Tool 1: CNC cutting parameters
# ---------------------------------------------------------------------------
def cnc_cutting_parameters(
    tool_diameter_mm: float,
    flutes: int = 3,
    material: str = "aluminum_6061",
    axial_depth_mm: float | None = None,
    radial_width_mm: float | None = None,
    spindle_max_rpm: float = 10_000.0,
    volume_to_remove_cm3: float = 0.0,
) -> dict:
    """Spindle speed, feed, MRR, power, force and roughing time for a carbide end mill."""
    D = tool_diameter_mm
    _check("tool_diameter_mm", D, 1, 25, "mm")
    if not isinstance(flutes, int) or not (1 <= flutes <= 6):
        raise ValueError(f"flutes={flutes} is outside the valid range 1–6.")
    m = _material(CNC_MATERIALS, material, "CNC")
    ap = 0.5 * D if axial_depth_mm is None else axial_depth_mm
    ae = 0.4 * D if radial_width_mm is None else radial_width_mm
    _check("axial_depth_mm", ap, 0.05, 3 * D, "mm")
    _check("radial_width_mm", ae, 0.05, D, "mm")
    _check("spindle_max_rpm", spindle_max_rpm, 1_000, 60_000, "rpm")
    _check("volume_to_remove_cm3", volume_to_remove_cm3, 0, 10_000, "cm^3")

    rpm_ideal = m["vc"] * 1000.0 / (math.pi * D)
    rpm = min(rpm_ideal, spindle_max_rpm)
    vc_actual = rpm * math.pi * D / 1000.0  # m/min
    fz = m["fz_per_D"] * D
    feed = fz * rpm * flutes  # mm/min
    mrr = ap * ae * feed / 1000.0  # cm^3/min
    power_w = ap * ae * feed * m["kc"] / 60_000.0  # W  (Pc[kW] = ap*ae*vf*kc / 60e6)
    force_n = power_w / (vc_actual / 60.0)
    t_min = volume_to_remove_cm3 / mrr if volume_to_remove_cm3 > 0 else 0.0
    return {
        "tool": "cnc_cutting_parameters",
        "material": material,
        "spindle_rpm": round(rpm, 1),
        "ideal_rpm": round(rpm_ideal, 1),
        "rpm_limited_by_machine": rpm_ideal > spindle_max_rpm,
        "cutting_speed_m_min": round(vc_actual, 1),
        "chip_load_mm_per_tooth": round(fz, 4),
        "feed_mm_min": round(feed, 1),
        "axial_depth_mm": round(ap, 3),
        "radial_width_mm": round(ae, 3),
        "mrr_cm3_min": round(mrr, 3),
        "spindle_power_W": round(power_w, 1),
        "avg_cutting_force_N": round(force_n, 1),
        "roughing_time_min": round(t_min, 2),
        "assumptions": "Carbide tool; mid-range catalog vc; fz proportional to D; no chip thinning; constant kc.",
    }


# ---------------------------------------------------------------------------
# Tool 2: End-mill reach / deflection / corner check
# ---------------------------------------------------------------------------
def end_mill_reach_check(
    tool_diameter_mm: float,
    pocket_depth_mm: float,
    material: str = "aluminum_6061",
    internal_corner_radius_mm: float | None = None,
    stickout_mm: float | None = None,
    force_N: float | None = None,
    deflection_limit_mm: float = 0.025,
) -> dict:
    """Can this pocket be milled with this end mill? Reach class, deflection, corner check."""
    D = tool_diameter_mm
    _check("tool_diameter_mm", D, 1, 25, "mm")
    _check("pocket_depth_mm", pocket_depth_mm, 0.1, 150, "mm")
    _material(CNC_MATERIALS, material, "CNC")
    L = pocket_depth_mm + 2.0 if stickout_mm is None else stickout_mm
    _check("stickout_mm", L, D, 200, "mm")
    if L < pocket_depth_mm:
        raise ValueError(f"stickout_mm={L} mm is shorter than pocket_depth_mm={pocket_depth_mm} mm; the tool cannot reach the floor.")
    if internal_corner_radius_mm is not None:
        _check("internal_corner_radius_mm", internal_corner_radius_mm, 0, 50, "mm")
    _check("deflection_limit_mm", deflection_limit_mm, 0.001, 0.5, "mm")
    if force_N is None:
        force_N = cnc_cutting_parameters(D, material=material)["avg_cutting_force_N"]
    _check("force_N", force_N, 1, 5000, "N")
    force_n = force_N

    d_eff = 0.8 * D
    I = math.pi * d_eff**4 / 64.0
    defl = force_n * L**3 / (3 * CARBIDE_E_MPA * I)
    L_max = (3 * CARBIDE_E_MPA * I * deflection_limit_mm / force_n) ** (1 / 3)
    LD = L / D
    reach = ("standard" if LD <= 3 else "long-reach: reduce depth of cut" if LD <= 5
             else "extended reach: high chatter risk, use a larger tool or shallower pocket" if LD <= 8
             else "beyond practical reach")
    out = {
        "tool": "end_mill_reach_check",
        "material": material,
        "L_over_D": round(LD, 2),
        "reach_class": reach,
        "stickout_mm": L,
        "force_N": round(force_n, 1),
        "deflection_mm": round(defl, 4),
        "deflection_limit_mm": deflection_limit_mm,
        "deflection_ok": defl <= deflection_limit_mm,
        "max_stickout_for_limit_mm": round(L_max, 1),
        "assumptions": "Static cantilever, end load; effective solid diameter 0.8D; E=600 GPa carbide; corner OK if R >= 1.1 x tool radius. Ignores chatter/runout.",
    }
    if internal_corner_radius_mm is not None:
        ok = internal_corner_radius_mm >= 1.1 * D / 2
        out["internal_corner_radius_mm"] = internal_corner_radius_mm
        out["corner_ok"] = ok
        out["largest_tool_for_corner_mm"] = round(2 * internal_corner_radius_mm / 1.1, 2)
    return out


# ---------------------------------------------------------------------------
# Tool 3: FDM print estimate
# ---------------------------------------------------------------------------
def fdm_print_estimate(
    volume_cm3: float,
    surface_area_cm2: float,
    height_mm: float,
    material: str = "PLA",
    layer_height_mm: float = 0.2,
    nozzle_mm: float = 0.4,
    infill_pct: float = 20.0,
    walls: int = 3,
    print_speed_mm_s: float = 60.0,
    overhang_deg: float = 0.0,
    max_flow_mm3_s: float = 12.0,
) -> dict:
    """Print time, deposited volume, mass and cost for an FDM part."""
    _check("volume_cm3", volume_cm3, 0.1, 5000, "cm^3")
    _check("surface_area_cm2", surface_area_cm2, 1, 20000, "cm^2")
    _check("height_mm", height_mm, 0.5, 500, "mm")
    m = _material(FDM_MATERIALS, material, "FDM")
    _check("nozzle_mm", nozzle_mm, 0.2, 1.2, "mm")
    _check("layer_height_mm", layer_height_mm, 0.05, 0.6 * nozzle_mm, "mm")
    _check("infill_pct", infill_pct, 0, 100, "%")
    if not isinstance(walls, int) or not (1 <= walls <= 10):
        raise ValueError(f"walls={walls} is outside the valid range 1–10.")
    _check("print_speed_mm_s", print_speed_mm_s, 10, 500, "mm/s")
    _check("overhang_deg", overhang_deg, 0, 90, "deg")
    _check("max_flow_mm3_s", max_flow_mm3_s, 2, 60, "mm^3/s")

    w = 1.1 * nozzle_mm
    shell = min(volume_cm3, surface_area_cm2 * walls * w / 10.0)
    deposited = shell + (volume_cm3 - shell) * infill_pct / 100.0  # cm^3
    rate_req = print_speed_mm_s * w * layer_height_mm
    rate = min(rate_req, max_flow_mm3_s)
    t_s = deposited * 1000.0 / (0.7 * rate) + 2.0 * (height_mm / layer_height_mm)
    hours = t_s / 3600.0
    mass = deposited * m["rho"]
    cost = hours * FDM_MACHINE_RATE + mass / 1000.0 * m["usd_kg"]
    return {
        "tool": "fdm_print_estimate",
        "material": material,
        "print_time_h": round(hours, 3),
        "deposited_volume_cm3": round(deposited, 2),
        "mass_g": round(mass, 1),
        "cost_usd": round(cost, 2),
        "flow_limited": rate_req > max_flow_mm3_s,
        "speed_where_flow_saturates_mm_s": round(max_flow_mm3_s / (w * layer_height_mm), 1),
        "supports_needed": overhang_deg > 45.0,
        "assumptions": "Line width 1.1 x nozzle; skins folded into walls; 70% motion efficiency; 2 s per layer change; 45 deg self-supporting rule; 4 USD/h machine.",
    }


# ---------------------------------------------------------------------------
# Tool 4: Process cost break-even (FDM vs CNC aluminum vs injection molding)
# ---------------------------------------------------------------------------
def process_cost_breakeven(
    volume_cm3: float,
    bbox_x_mm: float,
    bbox_y_mm: float,
    bbox_z_mm: float,
    quantity: int,
    surface_area_cm2: float | None = None,
    cnc_material: str = "aluminum_6061",
    mold_cost_usd: float = 8000.0,
) -> dict:
    """Cost per part for FDM, CNC and injection molding; crossover quantities."""
    _check("volume_cm3", volume_cm3, 0.1, 2000, "cm^3")
    for n, v in (("bbox_x_mm", bbox_x_mm), ("bbox_y_mm", bbox_y_mm), ("bbox_z_mm", bbox_z_mm)):
        _check(n, v, 1, 600, "mm")
    if not isinstance(quantity, int) or not (1 <= quantity <= 1_000_000):
        raise ValueError(f"quantity={quantity} is outside the valid range 1–1,000,000.")
    bbox_vol = bbox_x_mm * bbox_y_mm * bbox_z_mm / 1000.0
    if volume_cm3 > bbox_vol:
        raise ValueError(f"volume_cm3={volume_cm3} is larger than the bounding box ({bbox_vol:.1f} cm^3); check units.")
    area_defaulted = surface_area_cm2 is None
    if area_defaulted:
        surface_area_cm2 = 1.5 * 6.0 * volume_cm3 ** (2.0 / 3.0)  # HW4 default: 1.5 x area of an equal-volume cube
    _check("surface_area_cm2", surface_area_cm2, 1, 20000, "cm^2")
    m = _material(CNC_MATERIALS, cnc_material, "CNC")
    _check("mold_cost_usd", mold_cost_usd, 1000, 200000, "USD")

    # FDM: variable only
    fdm = fdm_print_estimate(volume_cm3, surface_area_cm2, bbox_z_mm, "PLA")
    fdm_var = fdm["cost_usd"] + 10 / 60 * FDM_POST_RATE
    fdm_fixed = 0.0
    # CNC: 3 h CAM + setup; stock = bbox + 6 mm per axis
    stock_cm3 = (bbox_x_mm + 6) * (bbox_y_mm + 6) * (bbox_z_mm + 6) / 1000.0
    rough_min = cnc_cutting_parameters(10.0, 3, cnc_material, volume_to_remove_cm3=stock_cm3 - volume_cm3)["roughing_time_min"]
    finish_min = surface_area_cm2 * 100.0 / 0.5 / 1000.0  # area / stepover / feed
    cnc_hours = (rough_min + finish_min) / 60.0 + 0.25
    cnc_fixed = 3.0 * SHOP_RATE_CNC
    cnc_var = cnc_hours * SHOP_RATE_CNC + stock_cm3 * m["rho"] / 1000.0 * m["usd_kg"]
    # Injection molding (ABS): mold + 5 h press setup; 30 s cycle
    mold_fixed = mold_cost_usd + 5.0 * SHOP_RATE_MOLD
    mold_var = 30 / 3600 * SHOP_RATE_MOLD + volume_cm3 * 1.04 / 1000.0 * 3.0

    procs = {"FDM (PLA)": (fdm_fixed, fdm_var), f"CNC ({m['E_label']})": (cnc_fixed, cnc_var), "Injection molding (ABS)": (mold_fixed, mold_var)}
    cpp = {k: f / quantity + v for k, (f, v) in procs.items()}

    def cost(k, q):
        f, v = procs[k]
        return f / q + v

    crossovers = []
    keys = list(procs)
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i], keys[j]
            g = lambda q: cost(a, q) - cost(b, q)
            lo, hi = 1.0, 1e6
            if g(lo) * g(hi) < 0:
                q = brentq(g, lo, hi)
                crossovers.append({"between": [a, b], "quantity": round(q)})
    # cheapest by range
    grid = sorted({1, 1_000_000, *[c["quantity"] for c in crossovers], *[c["quantity"] + 1 for c in crossovers]})
    ranges, prev = [], None
    for q in grid:
        best = min(keys, key=lambda k: cost(k, q))
        if best != prev:
            ranges.append({"from_qty": q, "cheapest": best})
            prev = best
    return {
        "tool": "process_cost_breakeven",
        "quantity": quantity,
        "surface_area_cm2": round(surface_area_cm2, 1),
        "surface_area_defaulted": area_defaulted,
        "cost_per_part_usd": {k: round(v, 2) for k, v in cpp.items()},
        "cheapest_process": min(cpp, key=cpp.get),
        "crossovers": crossovers,
        "cheapest_by_quantity": ranges,
        "cnc_hours_per_part": round(cnc_hours, 3),
        "typical_tolerance_mm": {"FDM (PLA)": 0.3, f"CNC ({m['E_label']})": 0.05, "Injection molding (ABS)": 0.1},
        "caveat": "Cheapest is not the same as right: the processes differ in material, strength and tolerance.",
    }
