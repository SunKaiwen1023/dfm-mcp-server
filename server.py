"""DFM analytical tools as an MCP server (24-679 HW5).

Exposes the four Homework 4 tools and two new tools chosen from shop-pro interviews:

  HW4  cnc_cutting_parameters   spindle speed, feed, MRR, power, force, roughing time
  HW4  end_mill_reach_check     L/D reach class, tool deflection, internal-corner check
  HW4  fdm_print_estimate       FDM print time, mass, cost, flow limit, support flag
  HW4  process_cost_breakeven   FDM vs CNC vs injection molding cost and crossovers
  NEW  fit_allowance_check      as-made fit after tolerance, shrinkage and coating; CAD size to draw
  NEW  fdm_feature_check        thin walls, layer-direction strength, overhang, enclosed channels

Run:  mcp dev server.py        (opens the MCP Inspector)
      python server.py         (stdio, for Claude Desktop or any MCP client)
      python server.py --http  (streamable HTTP at http://localhost:8000/mcp)

Division of labour: this server owns the math, units, input validation and error
messages. The client owns choosing a tool, filling arguments from the conversation,
asking the user for missing inputs, and presenting results. A human owns checking that
the inputs match the real CAD model and shop, and the final go / no-go decision.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from dfm_tools import hw4_tools as hw4
from dfm_tools import new_tools as new

mcp = MCPServer(
    name="dfm-tools",
    version="1.0.0",
    instructions=(
        "Design-for-manufacturing calculators for CNC milling and FDM printing. "
        "Always call a tool for numbers instead of estimating. State any defaults you rely on, "
        "give units, and repeat the tool's main assumption and 'why' text to the user. "
        "Results are estimates for early design review, not sign-off."
    ),
)

READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)

CncMaterial = Literal["aluminum_6061", "steel_1018", "stainless_304", "titanium_6al4v", "pom_acetal"]
FdmMaterial = Literal["PLA", "PETG", "ABS", "nylon"]


def _run(fn, **kwargs) -> dict[str, Any]:
    """Call a pure tool function; turn domain errors into MCP tool errors (isError=true)."""
    try:
        return fn(**kwargs)
    except ValueError as e:
        raise ToolError(f"Invalid input: {e}") from e


# ----------------------------------------------------------------------------- HW4 tools
@mcp.tool(annotations=READ_ONLY)
def cnc_cutting_parameters(
    tool_diameter_mm: Annotated[float, Field(ge=1, le=25, description="End-mill diameter D, mm (1–25)")],
    flutes: Annotated[int, Field(ge=1, le=6, description="Number of flutes (1–6)")] = 3,
    material: Annotated[CncMaterial, Field(description="Workpiece material")] = "aluminum_6061",
    axial_depth_mm: Annotated[float | None, Field(gt=0, description="Axial depth of cut ap, mm (0.05–3D). Default 0.5D")] = None,
    radial_width_mm: Annotated[float | None, Field(gt=0, description="Radial width of cut ae, mm (0.05–D). Default 0.4D")] = None,
    spindle_max_rpm: Annotated[float, Field(ge=1000, le=60000, description="Machine spindle limit, rpm")] = 10000,
    volume_to_remove_cm3: Annotated[float, Field(ge=0, le=10000, description="Material to remove for a roughing-time estimate, cm^3")] = 0,
) -> dict[str, Any]:
    """[HW4] Spindle speed, feed, material-removal rate, spindle power, average cutting force and
    roughing time for a carbide end mill. Caps rpm at the machine limit and flags it."""
    return _run(hw4.cnc_cutting_parameters, **locals())


@mcp.tool(annotations=READ_ONLY)
def end_mill_reach_check(
    tool_diameter_mm: Annotated[float, Field(ge=1, le=25, description="End-mill diameter D, mm (1–25)")],
    pocket_depth_mm: Annotated[float, Field(ge=0.1, le=150, description="Pocket depth, mm (0.1–150)")],
    material: Annotated[CncMaterial, Field(description="Workpiece material")] = "aluminum_6061",
    internal_corner_radius_mm: Annotated[float | None, Field(ge=0, le=50, description="Internal vertical corner radius in CAD, mm (0–50)")] = None,
    stickout_mm: Annotated[float | None, Field(description="Tool stickout L, mm (D–200). Default depth + 2 mm")] = None,
    force_N: Annotated[float | None, Field(ge=1, le=5000, description="Cutting force, N (1–5,000). Default from cnc_cutting_parameters")] = None,
    deflection_limit_mm: Annotated[float, Field(ge=0.001, le=0.5, description="Allowed tool-tip deflection, mm")] = 0.025,
) -> dict[str, Any]:
    """[HW4] Can this pocket be milled with this end mill? Returns L/D reach class, static tool
    deflection vs. limit, maximum stickout, and whether the tool fits the internal corner radius."""
    return _run(hw4.end_mill_reach_check, **locals())


@mcp.tool(annotations=READ_ONLY)
def fdm_print_estimate(
    volume_cm3: Annotated[float, Field(ge=0.1, le=5000, description="Part volume, cm^3")],
    surface_area_cm2: Annotated[float, Field(ge=1, le=20000, description="Part surface area, cm^2")],
    height_mm: Annotated[float, Field(ge=0.5, le=500, description="Build height (Z), mm")],
    material: Annotated[FdmMaterial, Field(description="Filament")] = "PLA",
    layer_height_mm: Annotated[float, Field(ge=0.05, description="Layer height, mm (0.05–0.6 x nozzle)")] = 0.2,
    nozzle_mm: Annotated[float, Field(ge=0.2, le=1.2, description="Nozzle diameter, mm")] = 0.4,
    infill_pct: Annotated[float, Field(ge=0, le=100, description="Infill, %")] = 20,
    walls: Annotated[int, Field(ge=1, le=10, description="Perimeter count")] = 3,
    print_speed_mm_s: Annotated[float, Field(ge=10, le=500, description="Print speed, mm/s")] = 60,
    overhang_deg: Annotated[float, Field(ge=0, le=90, description="Worst overhang, degrees from vertical")] = 0,
    max_flow_mm3_s: Annotated[float, Field(ge=2, le=60, description="Hot-end volumetric flow limit, mm^3/s")] = 12,
) -> dict[str, Any]:
    """[HW4] FDM print time, deposited volume, mass and cost; flags hot-end flow saturation and supports."""
    return _run(hw4.fdm_print_estimate, **locals())


@mcp.tool(annotations=READ_ONLY)
def process_cost_breakeven(
    volume_cm3: Annotated[float, Field(ge=0.1, le=2000, description="Part volume, cm^3")],
    bbox_x_mm: Annotated[float, Field(ge=1, le=600, description="Bounding box X, mm")],
    bbox_y_mm: Annotated[float, Field(ge=1, le=600, description="Bounding box Y, mm")],
    bbox_z_mm: Annotated[float, Field(ge=1, le=600, description="Bounding box Z, mm")],
    quantity: Annotated[int, Field(ge=1, le=1_000_000, description="Order quantity")],
    surface_area_cm2: Annotated[float | None, Field(ge=1, le=20000, description="Surface area, cm^2. Default = 1.5 x area of an equal-volume cube")] = None,
    cnc_material: Annotated[CncMaterial, Field(description="CNC material")] = "aluminum_6061",
    mold_cost_usd: Annotated[float, Field(ge=1000, le=200000, description="Injection mold cost, USD")] = 8000,
) -> dict[str, Any]:
    """[HW4] Cost per part for FDM (PLA), CNC and injection molding (ABS) at a quantity, the cheapest
    process, and crossover quantities (scipy brentq). Always returns a caveat that cheapest is not best."""
    return _run(hw4.process_cost_breakeven, **locals())


# ----------------------------------------------------------------------------- new tools
@mcp.tool(annotations=READ_ONLY)
def fit_allowance_check(
    nominal_diameter_mm: Annotated[float, Field(ge=1, le=100, description="Nominal size of the bought mating part (pin, bearing, shaft), mm")],
    fit_goal: Annotated[Literal["press", "transition", "slip", "clearance"], Field(description="Desired fit")],
    process: Annotated[Literal["cnc", "fdm"], Field(description="How the feature is made")],
    feature: Annotated[Literal["hole", "shaft"], Field(description="'hole' = you make the bore; 'shaft' = you make the pin")] = "hole",
    material: Annotated[FdmMaterial | None, Field(description="FDM filament (required for fdm, default PLA)")] = None,
    cad_diameter_mm: Annotated[float | None, Field(gt=0, description="Diameter currently drawn in CAD, mm. Default = nominal (line-to-line)")] = None,
    coating: Annotated[Literal["none", "anodize_type_ii", "anodize_type_iii", "zinc_plate", "powder_coat"], Field(description="Finish applied after machining (metal only)")] = "none",
    coating_thickness_um: Annotated[float | None, Field(ge=1, le=200, description="Override coating thickness from the finisher, um")] = None,
    process_tolerance_mm: Annotated[float | None, Field(ge=0.001, le=1.0, description="Override ± process tolerance from your shop/vendor, mm. Default cnc 0.025, fdm 0.15")] = None,
    shrinkage_pct: Annotated[float | None, Field(ge=0, le=5, description="Override measured FDM linear shrinkage, %")] = None,
) -> dict[str, Any]:
    """[NEW] Predict the as-made fit of a hole or shaft against a precise bought part after process
    tolerance, FDM shrinkage and perimeter squish, and coating build-up (e.g. anodize). Returns the
    clearance band, the share of parts that land in the target fit, a breakdown of each shift
    ('why'), and the CAD diameter to draw instead. Accepts shop/vendor overrides."""
    return _run(new.fit_allowance_check, **locals())


@mcp.tool(annotations=READ_ONLY)
def fdm_feature_check(
    min_wall_mm: Annotated[float, Field(ge=0.05, le=50, description="Thinnest wall or rib, mm")],
    material: Annotated[FdmMaterial, Field(description="Filament")] = "PLA",
    nozzle_mm: Annotated[float, Field(ge=0.2, le=1.2, description="Nozzle diameter, mm")] = 0.4,
    load_direction: Annotated[Literal["none", "in_plane", "across_layers"], Field(description="Main load relative to layers: along them (in_plane) or pulling them apart (across_layers, Z)")] = "none",
    applied_stress_mpa: Annotated[float | None, Field(gt=0, le=200, description="Nominal tensile stress in the critical section, MPa")] = None,
    required_safety_factor: Annotated[float, Field(ge=1, le=10, description="Required safety factor")] = 2.0,
    overhang_deg: Annotated[float, Field(ge=0, le=90, description="Worst overhang, degrees from vertical")] = 0,
    channel_diameter_mm: Annotated[float | None, Field(ge=0.1, le=100, description="Diameter of the smallest horizontal internal channel or hole, mm")] = None,
    channel_enclosed: Annotated[bool, Field(description="True if the channel is enclosed so support inside cannot be reached")] = True,
) -> dict[str, Any]:
    """[NEW] Pre-flight check of FDM features: wall thickness vs. nozzle line width, strength along vs.
    across layers under load (with orientation advice), overhang support, and enclosed channels that
    trap support or close up. Each check returns status, value vs. limit, why, and a fix."""
    return _run(new.fdm_feature_check, **locals())


if __name__ == "__main__":
    import sys

    # stdio by default (MCP Inspector, Claude Desktop); --http serves at http://localhost:8000/mcp
    mcp.run(transport="streamable-http" if "--http" in sys.argv else "stdio")
