# dfm-mcp-server

Design-for-manufacturing (DFM) calculators exposed as an MCP server, for CMU 24-679 Homework 5 (team Manu-Sense, Autodesk "Manufacturability Awareness" project).

Six read-only tools: the four analytical tools from Homework 4 and two new tools chosen from interviews with experienced shop professionals.

| Tool | Origin | What it answers |
| --- | --- | --- |
| `cnc_cutting_parameters` | HW4 | Spindle rpm (capped at the machine limit), feed, MRR, power, cutting force, roughing time |
| `end_mill_reach_check` | HW4 | Can this pocket be milled with this end mill? L/D reach class, deflection, internal-corner check |
| `fdm_print_estimate` | HW4 | FDM print time, mass, cost, hot-end flow saturation, support flag |
| `process_cost_breakeven` | HW4 | FDM vs CNC vs injection molding cost per part and crossover quantities |
| `fit_allowance_check` | **new** | As-made fit after process tolerance, FDM shrinkage/perimeter squish and coating build-up (anodize, plating); CAD size to draw instead |
| `fdm_feature_check` | **new** | Pre-flight FDM check: wall vs nozzle line width, strength along vs across layers, overhang, enclosed channels that trap support |

## Setup

Requires Python 3.11+ (tested on 3.13) and, for the MCP Inspector, Node.js 22.19+.

```bash
git clone https://github.com/SunKaiwen1023/dfm-mcp-server.git
cd dfm-mcp-server
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q                                    # 9 tests: HW4 numbers, hand checks, new-tool contracts
```

### Run with the MCP Inspector (UI)

```bash
mcp dev server.py
# or: npx @modelcontextprotocol/inspector python server.py
```

Open the printed URL, connect, go to **Tools**, pick a tool, toggle **Edit as JSON**, paste arguments, **Execute Tool**.

### Run with the Inspector CLI (scriptable)

```bash
npx @modelcontextprotocol/inspector --cli python server.py --method tools/list
npx @modelcontextprotocol/inspector --cli python server.py --method tools/call \
  --tool-name fit_allowance_check --tool-arg nominal_diameter_mm=10 \
  --tool-arg fit_goal=press --tool-arg process=cnc --tool-arg coating=anodize_type_iii
```

### Run over streamable HTTP

```bash
python server.py --http        # serves http://localhost:8000/mcp
npx @modelcontextprotocol/inspector --server-url http://localhost:8000/mcp --transport http
```

### Use from Claude Desktop (or any stdio MCP client)

```json
{
  "mcpServers": {
    "dfm-tools": {
      "command": "/absolute/path/to/dfm-mcp-server/.venv/bin/python",
      "args": ["/absolute/path/to/dfm-mcp-server/server.py"]
    }
  }
}
```

## Tool contracts

All inputs are typed in the JSON schema (numbers with `minimum`/`maximum`, enums for materials and modes). Out-of-range or wrong-type inputs are rejected by schema validation before any math runs; inputs that pass the schema but break a physical rule (e.g. anodizing a PLA print, stickout shorter than the pocket) raise a `ToolError`. Both come back as `isError: true` with a readable message. Successful calls return `structuredContent` (a JSON object) plus the same JSON as text.

### `cnc_cutting_parameters` (HW4)
- **Inputs:** `tool_diameter_mm` 1–25 (required); `flutes` 1–6 (3); `material` ∈ aluminum_6061, steel_1018, stainless_304, titanium_6al4v, pom_acetal; `axial_depth_mm` 0.05–3D (0.5D); `radial_width_mm` 0.05–D (0.4D); `spindle_max_rpm` 1,000–60,000 (10,000); `volume_to_remove_cm3` 0–10,000 (0).
- **Returns:** `spindle_rpm`, `ideal_rpm`, `rpm_limited_by_machine`, `cutting_speed_m_min`, `chip_load_mm_per_tooth`, `feed_mm_min`, `mrr_cm3_min`, `spindle_power_W`, `avg_cutting_force_N`, `roughing_time_min`, `assumptions`.
- **Model:** n = vc·1000/(πD); vf = fz·n·z; Q = ap·ae·vf/1000; Pc = ap·ae·vf·kc/60e6 (Sandvik Coromant formulas). Carbide, catalog mid-range vc, fz ∝ D, constant kc.

### `end_mill_reach_check` (HW4)
- **Inputs:** `tool_diameter_mm` 1–25, `pocket_depth_mm` 0.1–150 (required); `material`; `internal_corner_radius_mm` 0–50; `stickout_mm` D–200 (depth + 2); `force_N` 1–5,000 (from tool 1); `deflection_limit_mm` 0.001–0.5 (0.025).
- **Returns:** `L_over_D`, `reach_class`, `deflection_mm`, `deflection_ok`, `max_stickout_for_limit_mm`, `corner_ok`, `largest_tool_for_corner_mm`, `assumptions`.
- **Model:** cantilever δ = FL³/(3EI), effective diameter 0.8D, E = 600 GPa; corner reachable if R ≥ 1.1 × tool radius.

### `fdm_print_estimate` (HW4)
- **Inputs:** `volume_cm3` 0.1–5,000, `surface_area_cm2` 1–20,000, `height_mm` 0.5–500 (required); `material` ∈ PLA, PETG, ABS, nylon; `layer_height_mm` 0.05–0.6×nozzle (0.2); `nozzle_mm` 0.2–1.2 (0.4); `infill_pct` 0–100 (20); `walls` 1–10 (3); `print_speed_mm_s` 10–500 (60); `overhang_deg` 0–90 (0); `max_flow_mm3_s` 2–60 (12).
- **Returns:** `print_time_h`, `deposited_volume_cm3`, `mass_g`, `cost_usd`, `flow_limited`, `speed_where_flow_saturates_mm_s`, `supports_needed`.

### `process_cost_breakeven` (HW4)
- **Inputs:** `volume_cm3` 0.1–2,000; `bbox_x_mm`, `bbox_y_mm`, `bbox_z_mm` 1–600; `quantity` 1–10⁶ (required); `surface_area_cm2` (default 1.5 × area of an equal-volume cube, as in HW4); `cnc_material`; `mold_cost_usd` 1,000–200,000 (8,000).
- **Returns:** `cost_per_part_usd` per process, `cheapest_process`, `crossovers` (scipy `brentq`), `cheapest_by_quantity`, `typical_tolerance_mm`, `caveat`.

### `fit_allowance_check` (new)
- **Inputs:** `nominal_diameter_mm` 1–100 (size of the bought pin/bearing/shaft), `fit_goal` ∈ press, transition, slip, clearance, `process` ∈ cnc, fdm (required); `feature` ∈ hole, shaft (hole); `material` FDM filament (PLA); `cad_diameter_mm` 0.5–1.5× nominal (= nominal); `coating` ∈ none, anodize_type_ii, anodize_type_iii, zinc_plate, powder_coat (metal only); overrides: `coating_thickness_um` 1–200, `process_tolerance_mm` 0.001–1.0 (cnc 0.025, fdm 0.15), `shrinkage_pct` 0–5.
- **Returns:** `contributions_mm` (shrinkage, perimeter squish, coating build-up), `systematic_shift_mm`, `expected_made_diameter_mm` {min, nominal, max}, `expected_clearance_mm` {min, max}, `target_clearance_mm`, `fraction_of_band_in_target`, `verdict`, `recommended_cad_diameter_mm`, `target_achievable_with_this_tolerance`, `why` (list of sentences), `reasoning` {observe, orient, decide, act}, `assumptions`.
- **Model:** as-made = CAD + Σ shifts ± tolerance. FDM: shrinkage (PLA 0.3 %, PETG 0.4 %, ABS 0.7 %, nylon 1.2 %) and ±0.10 mm perimeter squish (holes small, bosses large). Coating: diameter change = 2 × thickness × build-up fraction (anodize 50 % outward, plating/powder 100 %). Target bands simplified from ISO 286 for ~3–50 mm.
- **Errors:** coating on an FDM part; `shrinkage_pct` with CNC; `coating_thickness_um` with `coating=none`; out-of-range values.

### `fdm_feature_check` (new)
- **Inputs:** `min_wall_mm` 0.05–50 (required); `material` (PLA); `nozzle_mm` 0.2–1.2 (0.4); `load_direction` ∈ none, in_plane, across_layers; `applied_stress_mpa` 0–200; `required_safety_factor` 1–10 (2); `overhang_deg` 0–90; `channel_diameter_mm` 0.1–100; `channel_enclosed` (true).
- **Returns:** `overall` (printable / printable with risks / not printable as designed), `checks[]` each with `status` (ok/warn/fail/info), `failure_mode`, `criterion`, value vs limit, margin, `why`, `fix` (observe → orient → decide → act); `orientation_advice`; `assumptions`.
- **Model:** line width 1.1 × nozzle; wall < 1 line fails, < 2 lines warns, structural minimum = max(3 lines, material floor); Z strength = XY × ratio (PLA 0.55, PETG 0.65, ABS 0.50, nylon 0.60); 45° overhang rule; horizontal channels < 2.5 lines close up, ≤ 5 mm bridge but attract trapped auto-supports, > 5 mm need support (fail if enclosed).
- **Errors:** stress given with `load_direction=none`; out-of-range values; unknown material.

## Who does what

| | Responsibility |
| --- | --- |
| **Server** | The math, units, valid ranges, input validation, structured results, "why" and "assumptions" text, readable errors. Stateless and read-only. |
| **Client** (Inspector, Claude Desktop, the HW4 agent) | Choosing the tool, filling arguments from the conversation or CAD, asking the user for missing inputs instead of guessing, showing results with their assumptions. |
| **Human** | Checking inputs against the real CAD model and drawing, replacing defaults with the real shop's tooling, tolerance, shrinkage and finisher data, printing or machining a test coupon for borderline results, and making the go/no-go call. |

## Demo record

`research/ai_interviews.md` holds the HW5 synthetic-persona profiles, prompts and verbatim transcripts. `demo/` holds MCP Inspector screenshots (`fig_*.png`) and a CLI transcript (`inspector_cli_transcript.md`) for one HW4 tool, both new tools and two invalid-input calls.

## Design notes

- Each tool follows the five-part contract from the 24-679 MCP lecture: purpose (docstring), typed inputs, units and valid ranges, structured result, and invalid-input behaviour.
- The two new tools return their reasoning as observe → orient → decide → act fields (value vs. limit → named failure mode → governing criterion → specific change), after the observation-to-action ontology in Ezemba, Tucker & McComb's agent-driven design work, so a client agent receives the professional reasoning explicitly instead of a bare verdict.
- Every result carries `"tool"` and `"assumptions"` so a logged call can be audited on its own.

## Notes

The HW4 tool functions in `dfm_tools/hw4_tools.py` follow the HW4 write-up (same names, inputs, ranges and assumptions) and reproduce its published example numbers (e.g. FDM 14.27 / CNC 64.12 USD per part and a ~610-part crossover for the 200-bracket question; 3,820 rpm at 25 mm); `tests/test_tools.py` checks this. Material constants, rates and fit bands are approximate catalog-style values for early design review, not sign-off.

License: MIT.
