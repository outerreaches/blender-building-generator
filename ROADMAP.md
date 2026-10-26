# City dressing roadmap

Planned work after v0.7 (metro scale + wasteland). Each phase is a separate
shippable step with its own tests, renders and release.

**Phase 1 shipped in v0.8**: interior ratio, condition model, corner shear,
rubble mound and the condition sheet render.

## Requirements

### R1 — Interior budget
Most buildings should not get a full interior. Replace the all-or-nothing
operator checkbox with a **ratio** of buildings that receive interiors; the rest
stay shells or rubble-filled. Interiors must be visible in the plan (per lot),
not re-rolled by the adapter.

### R2 — Damage and collapse conditions
Tall buildings need more than a weathered top. Conditions to support:

| Condition | Intent |
| --- | --- |
| Intact | Full shell, optional interior |
| Weathered | Irregular collapsed top (existing damage system) |
| Semi-collapsed | Missing corner/wedge and rubble apron around the building |
| Rubble-filled | Shell stands, interior packed with rubble; not enterable |
| Lower floors only | Damage cuts the tower to 1–3 floors; only those are enterable |
| Shell | No roof, exposed floor slabs/beams, not enterable |
| Collapsed | No standing shell; rubble field and wall stumps |
| Shaft (stretch) | Lower floors and roof reachable through an elevator shaft, middle full of rubble |

Conditions are chosen with district-specific weights; tall downtown buildings
collapse more often than houses.

### R3 — Common city locations
Every city should contain the following, explorable unless noted. Placement
follows district logic, not a one-per-parcel random draw.

| Location | Where | Notes |
| --- | --- | --- |
| Gas station | Suburban, industrial, residential arterials | Canopy, pumps, kiosk (enterable), price sign |
| Park / small plaza | All districts | Trees, benches, paths; outdoors |
| Bus / transit shelter | Downtown, old town, residential | Small shelter on the footway, 2–3 per map |
| Fast food | Residential, suburban, industrial | Distinctive roof; with or without drive-thru |
| Parking lot | Suburban, industrial, old town | Painted stalls, booth; outdoors |
| Parking structure | Downtown, brutalist | 3–4 open decks, ramps |
| Grocery / big box | Suburban, industrial | Rare downtown; clustered with mall/strip mall; some collapsed |
| Auto repair | Industrial | Bay doors, canopy, hardstanding |
| Mall | Suburban | 1–2 per map, part of the retail megacluster |

### R4 — Repeating urban patterns
- Mall + big box + strip mall **megacluster** outside the core.
- **Strip malls** in suburban and industrial areas.
- **Plazas** in the uptown/old-town area.
- **Cul-de-sacs** in the suburban street layout.

### R5 — Scale (done in v0.7)
3–4× city extent, 6 km wasteland ground, denser suburbs.

## Design

### Plan schema v4
`Lot` gains `kind`, `condition`, `interiors` and `damage`. The POI pad is the
existing lot width/depth/center/rotation, so the adapter stays dumb.

`CitySettings` gains `interior_ratio` (0–1, default 0.25). The operator's
`interiors` boolean is replaced, not aliased.

### Condition mapping (existing builder capabilities where possible)

| Condition | Builder/adapter mapping |
| --- | --- |
| Intact | `damage × 1.0`; interiors when flagged |
| Weathered | `damage × 1.3`; interiors only below the damage line |
| Semi-collapsed | `damage × 1.8`, corner shear (bmesh bisect), `exterior_rubble` |
| Rubble-filled | `interior_fill='FILLED'`, `building_profile='NONE'`, no interior |
| Lower floors | `damage ≥ .85` so the cut lands at 1–3 floors; interiors forced on |
| Shell | `flat_roof=False`, `floor_slabs=True`, `exterior_rubble`, no interior |
| Collapsed | Adapter builds a rubble mound + wall stump instead of a shell |
| Shaft | Needs a dedicated interiors routine; stretch goal |

Proposed weights (percent):

| Style | Intact | Weathered | Semi | Filled | Lower | Shell | Collapsed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Downtown | 20 | 26 | 20 | 12 | 6 | 10 | 6 |
| Old town | 40 | 30 | 10 | 8 | 4 | 4 | 4 |
| Residential | 45 | 30 | 8 | 8 | 4 | 3 | 2 |
| Brutalist | 30 | 30 | 14 | 10 | 6 | 6 | 4 |
| Industrial | 35 | 25 | 8 | 8 | 4 | 12 | 8 |
| Suburban | 60 | 25 | 5 | 4 | 2 | 2 | 2 |

Damage multipliers per condition: intact 1.0, weathered 1.3, semi 1.7, filled
1.0, lower 0.95, shell 1.5; collapsed has no shell.

### POI placement
- A **block-level pass** after normal lot placement: a POI buys the whole block
  interior (a bigger pad than one parcel) and removes that block's normal lots.
- Quotas scale with radius and are capped; a shortfall is reported like the
  circuit warning instead of silently missing a required type.
- District weights come from the R3 table. Retailing is clustered: the mall
  anchors the suburban edge, big boxes and the strip mall go into the nearest
  blocks, parking lots sit between them.
- POI conditions are limited to intact / collapsed / shell. Collapsed POIs keep
  the pad and place a rubble field, sign pylon or wall stumps.

### POI assets
Blockout-level composed meshes built from boxes, cones and quads, with reused
shell bodies where a volume must be enterable (big box, repair bays, mall,
strip-mall units). Each POI becomes a small set of objects in its district
collection, using shared materials (asphalt, pavement, wall, glass, signage,
foliage, metal). Props are part of the same object set, so FBX export and
culling keep working.

### Street patterns
- Cul-de-sacs: suburban local growth gains dead-end stubs; the distance-field
  tessellator already rounds dead ends, so they read as turning circles.
- Retail access: POI pads align to a parking apron and connect to the nearest
  non-highway road; no new street topology needed.
- Plazas and strip malls repeat near their district anchors rather than being
  spread uniformly.

## Phases

### Phase 1 — Interior budget and conditions — shipped in v0.8
Plan v4, `interior_ratio`, condition weights, damage mapping, corner shear,
rubble mound, shell/lower-floor/filled variants, adapter cutover, condition-sheet
render. Acceptance: every condition occurs at the proposed frequency across
seeds; tall lots can be collapsed; interiors only where flagged; corner-sheared
meshes validate; no interiors in filled/shell/collapsed; Blender smoke and
round-trip still pass.

### Phase 2 — POI framework + roadside set
Block-level placement pass, quotas and reporting, gas station, park, plaza,
transit shelter, fast food. Acceptance: a default city contains each type (or
reports a shortfall); pads and props export; no overlap with buildings; renders.

### Phase 3 — Retail and parking set
Parking lot, parking structure, auto repair, big box, strip mall, mall,
megacluster placement, collapsed POI variants. Acceptance: quotas hold on
default and metro maps; cluster spacing is bounded; enterable volumes have
interiors; renders.

### Phase 4 — Street patterns and polish
Suburban cul-de-sac stubs, plaza/strip-mall repetition, final scale tuning,
documentation and release. Acceptance: street invariants still hold (route
coverage, field classification, mesh topology), cul-de-sacs appear only in the
suburbs, metro renders updated.

## Open decisions
- Confirm the condition weights above (they are data, cheap to tune).
- POIs replace whole blocks (proposed) rather than sharing a block.
- Default interior ratio 0.25 (shipped).
- Which POIs need enterable interiors: proposed big box, mall, repair, fast
  food, gas kiosk; parks/plazas/parking are outdoors only.
- Mall count by radius: proposed 1 for radius 6–11, 2 for radius ≥ 12.
