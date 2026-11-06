"""Two new HW5 tools, chosen from the shop-pro interviews.

fit_allowance_check  - predicts the as-made clearance of a hole or shaft after process
                       tolerance, FDM shrinkage / hole compensation and coating build-up,
                       and recommends the CAD size that lands in the target fit.
                       (Interviews: anodize eating press-fits; material shrinkage
                       changing fits; "explain why"; vendor-capability overrides.)
fdm_feature_check    - checks thin walls against nozzle line width, layer-direction
                       strength under load, overhangs and enclosed channels, and says
                       why each check fails and by how much.
                       (Interviews: sub-nozzle walls, parts snapping along layer lines,
                       supports trapped in small tubes, orientation decisions.)
"""
from __future__ import annotations

import math

from .hw4_tools import FDM_MATERIALS, _check

# ---------------------------------------------------------------------------
# Shared data
# ---------------------------------------------------------------------------
# Target diametral clearance bands (hole minus pin), mm, for a feature mating with a
# precise purchased part (dowel, bearing, shaft). Simplified from ISO 286 practice
# for ~3-50 mm (CNC) and common FDM rules of thumb.
FIT_BANDS = {
    "cnc": {
        "press": (-0.040, -0.005),
        "transition": (-0.005, 0.015),
        "slip": (0.010, 0.040),
        "clearance": (0.040, 0.150),
    },
    "fdm": {
        "press": (-0.10, 0.00),
        "transition": (0.00, 0.10),
        "slip": (0.10, 0.25),
        "clearance": (0.25, 0.50),
    },
}
DEFAULT_PROCESS_TOL = {"cnc": 0.025, "fdm": 0.15}  # +/- mm, overridable by the vendor/shop

# Linear shrinkage %, typical as-printed (overridable with a measured value)
FDM_SHRINK_PCT = {"PLA": 0.3, "PETG": 0.4, "ABS": 0.7, "nylon": 1.2}
FDM_HOLE_COMP_MM = 0.10  # perimeter squish / polygon facets: holes print ~0.1 mm small, bosses ~0.1 mm large

# coating: (typical thickness um, fraction that builds up outward from the original surface)
COATINGS = {
    "none": (0.0, 0.0),
    "anodize_type_ii": (10.0, 0.5),
    "anodize_type_iii": (50.0, 0.5),
    "zinc_plate": (8.0, 1.0),
    "powder_coat": (75.0, 1.0),
}

# FDM strength: XY tensile strength (MPa) and Z/XY ratio (interlayer). Mid-range literature values.
FDM_STRENGTH = {
    "PLA": dict(xy_mpa=50.0, z_ratio=0.55, wall_floor_mm=1.2),
    "PETG": dict(xy_mpa=45.0, z_ratio=0.65, wall_floor_mm=1.2),
    "ABS": dict(xy_mpa=35.0, z_ratio=0.50, wall_floor_mm=1.5),
    "nylon": dict(xy_mpa=45.0, z_ratio=0.60, wall_floor_mm=1.5),
}


# ---------------------------------------------------------------------------
# New tool A: fit allowance
# ---------------------------------------------------------------------------
def fit_allowance_check(
    nominal_diameter_mm: float,
    fit_goal: str,
    process: str,
    feature: str = "hole",
    material: str | None = None,
    cad_diameter_mm: float | None = None,
    coating: str = "none",
    coating_thickness_um: float | None = None,
    process_tolerance_mm: float | None = None,
    shrinkage_pct: float | None = None,
) -> dict:
    """Predict the as-made fit of a hole/shaft against a precise mating part and recommend a CAD size."""
    _check("nominal_diameter_mm", nominal_diameter_mm, 1, 100, "mm")
    if process not in FIT_BANDS:
        raise ValueError(f"process='{process}' is not supported. Use 'cnc' or 'fdm'.")
    if fit_goal not in FIT_BANDS[process]:
        raise ValueError(f"fit_goal='{fit_goal}' is not supported. Use one of: {', '.join(FIT_BANDS[process])}.")
    if feature not in ("hole", "shaft"):
        raise ValueError("feature must be 'hole' (you make the hole, the pin is bought) or 'shaft' (you make the shaft, the bore is bought).")
    if coating not in COATINGS:
        raise ValueError(f"coating='{coating}' is not supported. Use one of: {', '.join(COATINGS)}.")
    if process == "fdm":
        if material is None:
            material = "PLA"
        if material not in FDM_MATERIALS:
            raise ValueError(f"FDM material '{material}' is not supported. Use one of: {', '.join(FDM_MATERIALS)}.")
        if coating != "none":
            raise ValueError(f"coating='{coating}' cannot be applied to an FDM {material} part; anodizing and plating are metal finishes. Use coating='none'.")
    elif shrinkage_pct is not None:
        raise ValueError("shrinkage_pct only applies to process='fdm'.")
    cad = nominal_diameter_mm if cad_diameter_mm is None else cad_diameter_mm
    _check("cad_diameter_mm", cad, 0.5 * nominal_diameter_mm, 1.5 * nominal_diameter_mm, "mm")
    tol = DEFAULT_PROCESS_TOL[process] if process_tolerance_mm is None else process_tolerance_mm
    _check("process_tolerance_mm", tol, 0.001, 1.0, "mm")

    sign = -1.0 if feature == "hole" else 1.0  # a hole shrinks when material is added, a shaft grows
    contributions = {}
    if process == "fdm":
        s = FDM_SHRINK_PCT[material] if shrinkage_pct is None else shrinkage_pct
        _check("shrinkage_pct", s, 0.0, 5.0, "%")
        contributions["shrinkage_mm"] = round(-cad * s / 100.0, 4)  # both holes and shafts get smaller
        contributions["perimeter_squish_mm"] = round(sign * FDM_HOLE_COMP_MM, 4)
    t_um, build = COATINGS[coating]
    if coating_thickness_um is not None:
        if coating == "none":
            raise ValueError("coating_thickness_um was given but coating='none'.")
        _check("coating_thickness_um", coating_thickness_um, 1, 200, "um")
        t_um = coating_thickness_um
    if coating != "none":
        contributions["coating_buildup_mm"] = round(sign * 2 * t_um * build / 1000.0, 4)
    systematic = sum(contributions.values())

    made_nom = cad + systematic
    made_lo, made_hi = made_nom - tol, made_nom + tol
    if feature == "hole":
        clr_lo, clr_hi = made_lo - nominal_diameter_mm, made_hi - nominal_diameter_mm
    else:
        clr_lo, clr_hi = nominal_diameter_mm - made_hi, nominal_diameter_mm - made_lo
    tgt_lo, tgt_hi = FIT_BANDS[process][fit_goal]
    overlap = max(0.0, min(clr_hi, tgt_hi) - max(clr_lo, tgt_lo))
    frac_in = overlap / (clr_hi - clr_lo)
    tgt_mid = (tgt_lo + tgt_hi) / 2
    if feature == "hole":
        rec_cad = nominal_diameter_mm + tgt_mid - systematic
    else:
        rec_cad = nominal_diameter_mm - tgt_mid - systematic
    band_too_wide = 2 * tol > (tgt_hi - tgt_lo)

    if frac_in >= 0.99:
        verdict = "meets target"
    elif clr_hi < tgt_lo:
        verdict = "too tight: parts will bind or not assemble"
    elif clr_lo > tgt_hi:
        verdict = "too loose: parts will rattle or slip"
    else:
        verdict = "partly in target: some parts will be " + ("too tight" if clr_lo < tgt_lo else "too loose")

    biggest = max(contributions, key=lambda k: abs(contributions[k])) if contributions else None
    why = []
    if biggest:
        why.append(f"Largest systematic shift is {biggest.replace('_mm','').replace('_',' ')} ({contributions[biggest]:+.3f} mm on diameter).")
    why.append(f"Process tolerance ±{tol:.3f} mm gives a clearance band {clr_lo:+.3f} to {clr_hi:+.3f} mm vs. target {tgt_lo:+.3f} to {tgt_hi:+.3f} mm.")
    if band_too_wide:
        why.append("The process tolerance band is wider than the target fit band, so no CAD size can guarantee this fit; tighten the process, ream/bore, or relax the fit.")

    failure_mode = ("interference too high: parts will not assemble or will crack" if clr_hi < tgt_lo and fit_goal != "press"
                    else "fit too tight for target" if clr_lo < tgt_lo
                    else "fit too loose for target" if clr_hi > tgt_hi else "none")
    reasoning = {
        "observe": f"Expected clearance {clr_lo:+.3f} to {clr_hi:+.3f} mm ({frac_in:.0%} of parts in target).",
        "orient": failure_mode,
        "decide": f"{fit_goal} fit needs clearance {tgt_lo:+.3f} to {tgt_hi:+.3f} mm.",
        "act": (f"Draw the {feature} at {rec_cad:.3f} mm" + ("" if not band_too_wide else
                ", and tighten the process (ream/bore, or tune and measure a print coupon) because ±" + f"{tol:.3f} mm is wider than the fit band") + "."),
    }
    return {
        "tool": "fit_allowance_check",
        "feature": feature,
        "process": process,
        "material": material,
        "fit_goal": fit_goal,
        "cad_diameter_mm": round(cad, 4),
        "systematic_shift_mm": round(systematic, 4),
        "contributions_mm": contributions,
        "expected_made_diameter_mm": {"min": round(made_lo, 4), "nominal": round(made_nom, 4), "max": round(made_hi, 4)},
        "expected_clearance_mm": {"min": round(clr_lo, 4), "max": round(clr_hi, 4)},
        "target_clearance_mm": {"min": tgt_lo, "max": tgt_hi},
        "fraction_of_band_in_target": round(frac_in, 3),
        "verdict": verdict,
        "recommended_cad_diameter_mm": round(rec_cad, 3),
        "target_achievable_with_this_tolerance": not band_too_wide,
        "why": why,
        "reasoning": reasoning,
        "assumptions": "Mating part is exact at nominal; uniform tolerance band; shrinkage and coating values are typical unless overridden with shop/vendor measurements; bands simplified from ISO 286 for ~3-50 mm.",
    }


# ---------------------------------------------------------------------------
# New tool B: FDM feature check
# ---------------------------------------------------------------------------
def fdm_feature_check(
    min_wall_mm: float,
    material: str = "PLA",
    nozzle_mm: float = 0.4,
    load_direction: str = "none",
    applied_stress_mpa: float | None = None,
    required_safety_factor: float = 2.0,
    overhang_deg: float = 0.0,
    channel_diameter_mm: float | None = None,
    channel_enclosed: bool = True,
) -> dict:
    """Check thin walls, layer-direction strength, overhangs and enclosed channels for an FDM part."""
    _check("min_wall_mm", min_wall_mm, 0.05, 50, "mm")
    if material not in FDM_STRENGTH:
        raise ValueError(f"FDM material '{material}' is not supported. Use one of: {', '.join(FDM_STRENGTH)}.")
    _check("nozzle_mm", nozzle_mm, 0.2, 1.2, "mm")
    if load_direction not in ("none", "in_plane", "across_layers"):
        raise ValueError("load_direction must be 'none', 'in_plane' (load runs along the layers) or 'across_layers' (load pulls layers apart, Z).")
    if applied_stress_mpa is not None:
        _check("applied_stress_mpa", applied_stress_mpa, 0.01, 200, "MPa")
        if load_direction == "none":
            raise ValueError("applied_stress_mpa was given but load_direction='none'; say whether the load is 'in_plane' or 'across_layers'.")
    _check("required_safety_factor", required_safety_factor, 1.0, 10.0, "")
    _check("overhang_deg", overhang_deg, 0, 90, "deg")
    if channel_diameter_mm is not None:
        _check("channel_diameter_mm", channel_diameter_mm, 0.1, 100, "mm")

    m = FDM_STRENGTH[material]
    w = 1.1 * nozzle_mm
    checks = []

    # 1. wall thickness vs line width
    lines = min_wall_mm / w
    rec_wall = max(3 * w, m["wall_floor_mm"])
    if lines < 1:
        st, msg = "fail", f"Wall is {lines:.2f} line widths; the slicer drops walls thinner than one {w:.2f} mm extrusion line, so this feature will be missing or print into air."
    elif lines < 2:
        st, msg = "warn", f"Wall fits only one extrusion line ({lines:.2f} lines); single-line walls are fragile and gap-prone."
    elif min_wall_mm < rec_wall:
        st, msg = "warn", f"Wall prints ({int(lines)} perimeter lines) but is below the {rec_wall:.2f} mm structural minimum for {material} with a {nozzle_mm} mm nozzle."
    else:
        st, msg = "ok", f"Wall holds {int(lines)} perimeter lines; at or above the {rec_wall:.2f} mm structural minimum."
    checks.append({"check": "wall_thickness", "status": st,
                   "failure_mode": {"fail": "wall dropped by slicer / prints into air", "warn": "fragile thin wall, gaps between perimeters", "ok": "none"}[st],
                   "criterion": f"wall >= 1 line width ({w:.2f} mm) to print; >= {rec_wall:.2f} mm to carry load",
                   "value_mm": min_wall_mm, "limit_mm": round(rec_wall, 2),
                   "min_printable_mm": round(w, 2), "margin_mm": round(min_wall_mm - rec_wall, 2), "why": msg,
                   "fix": None if st == "ok" else f"Thicken to at least {rec_wall:.2f} mm, or use a smaller nozzle."})

    # 2. strength vs layer direction
    orientation_advice = None
    if load_direction != "none":
        xy, z = m["xy_mpa"], m["xy_mpa"] * m["z_ratio"]
        strength = z if load_direction == "across_layers" else xy
        entry = {"check": "layer_strength", "load_direction": load_direction,
                 "failure_mode": "interlayer delamination (snaps along layer lines)" if load_direction == "across_layers" else "in-plane tensile failure",
                 "criterion": f"strength / applied stress >= {required_safety_factor}",
                 "strength_mpa": round(strength, 1),
                 "xy_strength_mpa": xy, "z_strength_mpa": round(z, 1)}
        if applied_stress_mpa is not None:
            sf = strength / applied_stress_mpa
            sf_inplane = xy / applied_stress_mpa
            st = "ok" if sf >= required_safety_factor else ("warn" if sf >= 1.0 else "fail")
            entry.update(status=st, applied_stress_mpa=applied_stress_mpa, safety_factor=round(sf, 2),
                         required_safety_factor=required_safety_factor,
                         why=(f"Interlayer (Z) strength is only {m['z_ratio']:.0%} of in-plane strength for {material}; " if load_direction == "across_layers" else "")
                         + f"safety factor {sf:.2f} vs required {required_safety_factor}.")
            if st != "ok" and load_direction == "across_layers" and sf_inplane >= required_safety_factor:
                orientation_advice = f"Reorient so the load runs along the layers: in-plane safety factor would be {sf_inplane:.2f}."
                entry["fix"] = orientation_advice
            elif st != "ok":
                entry["fix"] = "Increase the section, raise wall/infill count, or change material; test a coupon under the real load."
        else:
            entry.update(status="info", why="No stress given; strength reported for reference only.")
            if load_direction == "across_layers":
                orientation_advice = "Load pulls layers apart; if possible orient so the load runs along the layers."
        checks.append(entry)

    # 3. overhang
    st = "ok" if overhang_deg <= 45 else "warn"
    checks.append({"check": "overhang", "status": st,
                   "failure_mode": "sagging / spaghetti on unsupported overhang" if st == "warn" else "none",
                   "criterion": "overhang <= 45 deg from vertical without support",
                   "value_deg": overhang_deg, "limit_deg": 45,
                   "why": "Overhangs steeper than 45 deg from vertical need support." if st == "warn" else "Self-supporting (<= 45 deg from vertical).",
                   "fix": "Add a 45 deg chamfer, reorient, or plan support removal." if st == "warn" else None})

    # 4. enclosed / horizontal channel
    if channel_diameter_mm is not None:
        d = channel_diameter_mm
        min_d = 2.5 * w
        if d < min_d:
            st, msg, fix = "fail", f"Channel {d} mm is under {min_d:.2f} mm (2.5 line widths) and is likely to close up or clog.", f"Open the channel to at least {min_d:.2f} mm or drill it after printing."
        elif d <= 5:
            st, msg, fix = "warn", "A horizontal channel this size bridges by itself, but auto-supports are often generated inside it and are very hard to remove.", "Block supports inside the channel (support blocker) or use a teardrop profile."
        elif d <= 10:
            st, msg, fix = "warn" if not channel_enclosed else "fail", "Channel needs internal support; " + ("support trapped in an enclosed channel cannot be removed." if channel_enclosed else "support is reachable but slow to remove."), "Use a teardrop/diamond profile so it self-supports, or split the part."
        else:
            st, msg, fix = "warn" if not channel_enclosed else "fail", "Large channel needs full internal support; " + ("enclosed support cannot be removed." if channel_enclosed else "check tool access for removal."), "Split the part along the channel axis or reorient the channel vertical."
        fm = "channel closes up or clogs" if d < min_d else "support trapped inside channel"
        checks.append({"check": "channel", "status": st, "failure_mode": fm,
                       "criterion": f"diameter >= {min_d:.2f} mm to stay open; <= 5 mm to bridge without internal support",
                       "diameter_mm": d, "enclosed": channel_enclosed, "why": msg, "fix": fix})

    order = {"fail": 3, "warn": 2, "info": 1, "ok": 0}
    worst = max(checks, key=lambda c: order[c["status"]])["status"]
    overall = {"fail": "not printable as designed", "warn": "printable with risks", "info": "printable", "ok": "printable"}[worst]
    return {
        "tool": "fdm_feature_check",
        "material": material,
        "nozzle_mm": nozzle_mm,
        "line_width_mm": round(w, 3),
        "overall": overall,
        "checks": checks,
        "orientation_advice": orientation_advice,
        "reasoning_fields": "each check reads observe (value vs limit) -> orient (failure_mode) -> decide (criterion) -> act (fix)",
        "assumptions": "Line width 1.1 x nozzle (same as fdm_print_estimate); structural wall = max(3 lines, material floor); Z/XY strength ratios are mid-range literature values for 100% perimeters and vary with printer, temperature and moisture; 45 deg overhang rule.",
    }
