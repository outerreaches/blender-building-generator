# City generator — v0.7 metro scale and wasteland

This generator supplies the main static environment for a low-poly first-person Unity game. Existing signs, ruined cars and other props remain separate assets.

## Try it

Install `output/procedural_building_shell_v0.7.0.zip` as a Blender add-on. Use **Shift+A → Mesh → Generate City** or **Generate Building by Style**. Start with **Layout Preview**; select **Detailed Shells** for windows, doors, floors, damage and optional interiors. Both modes use the same plan. Each run creates a new collection at the 3D cursor. Undo removes that run; failure rolls back its own objects.

The original single-building and bulk operators remain available. Architecture uses six district archetypes built from rectangular shells:

| District | City heights | Differences |
| --- | --- | --- |
| Downtown | 8–24 floors | Glazed offices, dense windows, storefront ground, rooftop plant box |
| Old town | 2–4 floors | Narrow tall windows, storefronts, corner pilasters, parapets |
| Residential | 2–5 floors | Regular apartment openings and modest parapets |
| Brutalist | 4–8 floors | Thick walls, square openings, higher parapets |
| Industrial | 1–2 floors, 5.5 m storeys | Wide low sheds, high windows, 3.2 m doors, no parapet |
| Suburban | 1–2 floors, 3.0 m storeys | Small footprints, pitched gable roof, front yard |

## Controls

| Control | Effect |
| --- | --- |
| Seed | Repeatable locations, roads, lots and per-building seeds |
| Radius / Block Size | Square extent in blocks/metres; 6 × 56 is about 672 m across |
| Primary / Secondary Locations | District seeds (default 6: downtown core, three midtown styles, industrial and suburban edges) and smaller growth destinations |
| Driving Circuits | Target count of distinct highway-to-district circuits, 0–8 |
| Core Radius Fraction | Distance over which core density stays constant |
| Core / Outskirts Density | Lot occupancy probabilities, smoothly blended radially |
| Local Road Density | Additional connected branches and incidental street loops |
| Road Corner Radius | Fraction of the tier fillet radius: 26 m highway, 18 m arterial, 12 m collector, 8 m local. 0 keeps square turns |
| Minimum Road Setback | Extra parcel clearance beyond street/ramp reservations |
| Sidewalk Width / Curb Height | Default 2 m footway and 0.15 m curb |
| Wasteland Extent | Open ground beyond the city edge, default 6000 m. The city stays inside the invisible game walls; the ground keeps going to the horizon |
| Architecture | Mixed districts or one style throughout |
| Building Damage | Existing shell damage; does not reroute roads |
| Building Budget | Stable sampling cap on eligible lots; reports when capped |
| Worn Lane Markings | Optional broken paint on highway/arterial/collector roads |
| Show Driving Route Guides | Colored curves, excluded from FBX export |

| Starting layout | Core radius | Core density | Outskirts density | Local roads |
| --- | --- | --- | --- | --- |
| Dense core in wasteland | .2 | 1 | .03 | .65 |
| Scattered ruined districts | .35 | .75 | .15 | .55 |
| Dense city across the map | 1 | 1 | 1 | 1 |

Increase the budget for large dense layouts. Density means occupancy of eligible parcels, not buildings per square kilometre. Small maps can fit fewer locations/circuits than requested; circuit shortfalls produce a warning. Wide sidewalks and large setbacks can eliminate undersized parcels.

**Scale.** Radius 6 is a district-sized map (about 670 m across); radius 18 is a metro (about 2 km across) and is what the `ares_metro` demo uses. Street-surface cost grows with the square of the radius (roughly 120k faces at radius 6 and 650k at radius 18 with default density), before buildings; keep Layout Preview on while tuning large maps.

## Growth and driving circuits

1. Place the center and primary district locations.
2. Route arterial links, favouring existing corridors.
3. Extend highway corridors to opposite map boundaries.
4. Connect secondary destinations.
5. Add highway entry → district streets → highway exit → return circuits.
6. Grow local streets, reserve circulation space and populate blocks.

Circuits are closed simple paths: no repeated intermediate node or retraced edge. Each includes highway and non-highway roads, spans at least six block edges, and has a distinct edge set. Circuits can share sections. The default is three, even with Local Road Density zero. Loop nodes, lengths and tiers are serialized in the plan. These are topology guarantees, not vehicle-physics certification.

Edge topology is grouped into continuous same-tier **routes**, preferring a straight continuation at each junction. Every interior corner of a route becomes a circular fillet (tangent-capped at 45% of each adjacent block edge), so a circuit turns through an arc rather than a square corner. Junctions are not hand-built: they are the union of the curved corridors, which gives each intersection its own shape from the incident widths and angles. Route centrelines are serialized under `paths`, separate from the lattice `roads` used for topology and parcels.

The target is a network of connected driving circuits that change road type and district along the way.

## Districts

With **Mixed Districts**, the centre and the closest primary form the downtown core; the outermost primary anchors the industrial edge and the primary farthest from it anchors the suburbs on the opposite side; the remaining primaries cycle old town, residential and brutalist. Every lot inherits the style of its nearest centre/primary, so districts form contiguous areas rather than a per-building mix. Choosing a single **Architecture** style overrides the assignment and therefore also the district-driven street network.

Each district changes all of the following, not just the material colour:

| District | Parcels per block | Footprint | Density | Extra setback | Local streets | Corner radius | Damage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Downtown | 1 | 72–92% | ×1.25 | 2 m | ×1.2 | ×0.5 | ×1.0 |
| Old town | 2×2 | 80–100% | ×1.0 | 0 m | ×1.0 | ×1.0 | ×1.0 |
| Residential | 2×2 | 80–100% | ×1.0 | 0 m | ×1.0 | ×1.0 | ×0.9 |
| Brutalist | 2×2 | 85–100% | ×0.95 | 0.5 m | ×0.85 | ×0.8 | ×0.8 |
| Industrial | 1 | 75–95% | ×0.8 | 2 m | ×0.6 | ×1.3 | ×1.2 |
| Suburban | 2×2 | 45–65% | ×1.0 | 3 m | ×0.5 | ×1.4 | ×0.3 |

"Footprint" is the fraction of the parcel the shell may occupy; the remainder becomes the yard, plaza or hardstanding. Downtown gets one tower per block, industrial one wide shed, and suburban four small houses with gardens. Local street growth multiplies the road-density probability, so downtown is a tighter grid while the industrial and suburban edges have fewer, longer blocks. Corner radii scale the per-tier fillet, which makes suburban bends wider and downtown corners tighter. Damage scales the city setting, so the suburbs stay mostly intact.

## Street-level geometry

- Carriageways: 20 m highway, 12 m arterial, 8 m collector, 6 m local. Corner fillets default to 0.6 × the tier radius (15.6 m highway, 10.8 m arterial, 7.2 m collector, 4.8 m local), scaled again by district.
- The surface is a distance field: `A(p)` is the nearest centreline distance minus that road's half width. Carriageway is `A ≤ 0`, footway `0 < A ≤ sidewalk width`. Both are extracted per 1.5 m cell by clipping two triangles against those iso-levels, so neighbouring cells share every crossing vertex.
- There is no boolean union: junctions are the natural union of the corridors, faces never overlap, and the only boundary edges are the open bottoms of the outer curb skirt. Curved boundaries deviate by at most ~0.5 m from the analytic envelope, at concave junction corners; road edges, fillets and curbs otherwise follow the centreline to centimetre accuracy.
- Footway height ramps smoothly at intersections; the feet are flush where the two roads meet. The maximum 0.25 m curb gives an intended rise/run of 0.125, about 7.1°.
- Frontages use adjacent road widths instead of one city-wide highway setback. Doors face non-highway streets; shells occupy disjoint parcels. Parcel margins exceed the maximum fillet intrusion, so buildings never intersect a curved corridor or its footway.
- Each lot has a foundation/ground floor and paved approach at footway elevation. This supplies the ground slab omitted by the existing shell builder.
- Lane paint follows each route's tangent, so dashes curve through bends and stop short of junctions. Terrain is cut only under sample cells that the footway fully covers, which keeps the unpaved surface continuous. Beyond the city the same ground continues as a flat wasteland frame out to the **Wasteland Extent** (default 6000 m), so the horizon reads as open ground while the game keeps the player inside invisible walls. New surfaces have metre-scaled planar UVs and material slots.
- Exterior rubble remains disabled in city recipes so it cannot obstruct circulation.

The referenced Ares capsule is 2 m high, radius 0.4 m, with a 0.4 m step offset and 45° slope limit. Its 1.5 m camera-pivot height is used in the street preview. Actual collision/navigation behaviour still needs Unity play tests.

## Unity export and artifacts

Use **File → Export → Generated City for Unity (.fbx)** and choose the root city collection. This exports only its mesh objects, triangulates them, preserves UV/material assignments, and uses metre scale with Y-up axis conversion. It restores selection and active object. Hidden/excluded city objects and non-unit scene scales are rejected instead of silently omitted/rescaled. Editable source objects are not joined or destructively triangulated.

Output stays as separate meshes for culling and future chunk/LOD work. No texture baking, Unity materials, colliders, NavMesh, static flags or prop placement are generated. `City_LanePaint` is tagged `decoration_no_collision`; exclude it from collision generation. Route guide curves are omitted from FBX.

Workspace `output` examples:

- `ares_city_base.blend`: 100 detailed buildings across six districts, sidewalks/foundations; street-level camera. Guide curves are hidden after the overview render.
- `ares_city_base.fbx`: the same base, 203 static mesh objects, without guide curves.
- `street_level.png`: geometry preview at Ares camera-pivot height.
- `driving_circuits.png`: overview with three colored circuits on curved centerlines.
- `district_downtown.png`, `district_industrial.png`, `district_suburban.png`: QA plan views of the three district archetypes.
- `corner_curve.png` / `corner_plan.png`: QA close-up and plan view of one filleted arterial junction.
- `city_preview.blend`: lightweight massing example generated by the smoke test.
- `ares_metro.blend`: radius 18 (about 2 km across), 1200 shells, 6000 m wasteland; the scale demo.
- `metro_overview.png`, `metro_plan.png`, `metro_wasteland.png`: metro skyline, plan view and the view from the suburban edge into the wasteland.

The base scene's `City_Streets` mesh is 64.9k vertices / 101.5k polygons at 100 buildings; `City_Ground` is 1.6k polygons. A JSON text datablock stores the versioned plan. Coordinates are relative to the collection's stored `origin`; road nodes multiply by `block_size`, while lot positions/dimensions and path points are metres. Schema version 3 adds `paths`: one entry per continuous same-tier route with its lattice `nodes`, flattened metre-space `points` and `width`. Locations and lots carry their district `style`; the per-style profile table is code (`STYLE_PROFILE`), not part of the file. v0.6 road geometry and parcel positions differ from v0.5 with the same seed. No legacy-plan or game-side importer is included.

## Code and verification

`city_plan.py`: pure settings, district assignment, seeded routing, route grouping and corner fillets, circuits, parcels. `streets.py`: pure distance-field surface and terrain tessellation. `styles.py`: district building recipes (massing, openings, roofs). `building_assets.py`: shell creation/shared materials. `city_operators.py`: Blender adapter. `city_export.py`: city-only FBX export.

Run `python -m unittest discover -s tests -v` for planning, district assignment and per-district ranges, circuit closure/tier diversity across seeds, route coverage and fillet continuity, parcel clearance against curved corridors, density, validation, distance-field classification, crack/overlap topology, curb heights, terrain coverage, and the style recipes (archetype differences, damage/interiors, unknown styles).

```
blender --background --factory-startup --python-exit-code 1 --python tests/blender_smoke.py
blender --background --factory-startup --python-exit-code 1 --python tests/blender_streets.py
blender --background --factory-startup --python-exit-code 1 --python tests/render_views.py
```

The third script regenerates the district and corner QA renders from the scene saved by the second. `tests/render_metro.py` separately builds the radius-18 metro scene and its three renders (about two minutes; not part of the default loop).

Verified on Blender 5.1.2. The first script covers registration, original operators, styles/interiors/damage, mesh validation and rollback. The second covers UVs, city-only export, selection restoration, triangulation, and world bounds after FBX reimport, then renders examples. The declared Blender 4.5 minimum is not separately tested. Unity import/play-mode tests are pending.

## Next milestones and limits

1. **Parcels and block structure:** parcels are still axis-aligned sub-cells of a square lattice, so block edges and building rows remain rectilinear even though the streets curve. Downtown already uses one tower per block and the suburbs set houses well back, but L/U/courtyard footprints, curved frontages and irregular block subdivision are the next step.
2. **Vertical routes:** bridges, ramps, interchanges and terrain obstacles with slope/headroom constraints. Highway currently means a wide at-grade corridor; no bridges exist yet.
3. **Asset variety:** the six archetypes cover massing and roofs, but civic landmarks (courthouse, station, hospital), authored facade kits, rooftop clutter and per-district palettes remain.
4. **Game delivery:** chunk/LOD export, collision proxies, navigation checks, vehicle swept-clearance tests and connected ruin/vegetation dressing.

Street surfaces have open bottoms below ground; they are not watertight solids. The 1.5 m surface sampling is a fixed budget decision: a tighter grid would reduce the ~0.5 m concave-corner deviation at the cost of roughly quadratic triangle growth. Roof extras are skipped when damage cuts the top floors, so a ruined shell keeps its jagged demolition silhouette. Fixed-style runs change the street network because district road factors no longer vary. Legacy damaged shells/interiors are not certified manifold or fully navigable. Generation is synchronous; preview and conservative budgets are recommended for large cities.
