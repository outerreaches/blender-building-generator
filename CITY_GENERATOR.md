# City generator — v0.4 street and driving-circuit foundation

This generator supplies the main static environment for a low-poly first-person Unity game. Existing signs, ruined cars and other props remain separate assets.

## Try it

Install `output/procedural_building_shell_v0.4.0.zip` as a Blender add-on. Use **Shift+A → Mesh → Generate City** or **Generate Building by Style**. Start with **Layout Preview**; select **Detailed Shells** for windows, doors, floors, damage and optional interiors. Both modes use the same plan. Each run creates a new collection at the 3D cursor. Undo removes that run; failure rolls back its own objects.

The original single-building and bulk operators remain available. Architecture is still based on rectangular-shell recipes:

| Style | City heights | Differences |
| --- | --- | --- |
| Old town | 2–4 floors | Tall windows, storefronts, corner pilasters, parapets |
| Residential | 2–5 floors | Regular apartment openings and modest parapets |
| Industrial | 1–2 floors | High storeys, wider doors, optional warehouse interiors |
| Brutalist | 4–8 floors | Thick walls, square openings, higher parapets |

## Controls

| Control | Effect |
| --- | --- |
| Seed | Repeatable locations, roads, lots and per-building seeds |
| Radius / Block Size | Square extent in blocks/metres; 6 × 56 is about 672 m across |
| Primary / Secondary Locations | District seeds and smaller growth destinations |
| Driving Circuits | Target count of distinct highway-to-district circuits, 0–8 |
| Core Radius Fraction | Distance over which core density stays constant |
| Core / Outskirts Density | Lot occupancy probabilities, smoothly blended radially |
| Local Road Density | Additional connected branches and incidental street loops |
| Minimum Road Setback | Extra parcel clearance beyond street/ramp reservations |
| Sidewalk Width / Curb Height | Default 2 m footway and 0.15 m curb |
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

## Growth and driving circuits

1. Place the center and primary district locations.
2. Route arterial links, favouring existing corridors.
3. Extend highway corridors to opposite map boundaries.
4. Connect secondary destinations.
5. Add highway entry → district streets → highway exit → return circuits.
6. Grow local streets, reserve circulation space and populate blocks.

Circuits are closed simple paths: no repeated intermediate node or retraced edge. Each includes highway and non-highway roads, spans at least six block edges, and has a distinct edge set. Circuits can share sections. The default is three, even with Local Road Density zero. Loop nodes, lengths and tiers are serialized in the plan. These are topology guarantees, not vehicle-physics certification.

The target is a network of connected driving circuits that change road type and district along the way.

## Street-level geometry

- Carriageways: 20 m highway, 12 m arterial, 8 m collector, 6 m local.
- Road/sidewalk rectangles are unioned before tessellation. Shared top edges are split and welded; intersection faces do not overlap.
- Footways have curb faces and flush corners, with 2 m approach transitions. The maximum 0.25 m curb gives an intended rise/run of 0.125, about 7.1°.
- Frontages use adjacent road widths instead of one city-wide highway setback. Doors face non-highway streets; shells occupy disjoint parcels.
- Each lot has a foundation/ground floor and paved approach at footway elevation. This supplies the ground slab omitted by the existing shell builder.
- Terrain is cut away under streets/foundations to avoid nearly coplanar surfaces. New surfaces have metre-scaled planar UVs and material slots.
- Exterior rubble remains disabled in city recipes so it cannot obstruct circulation.

The referenced Ares capsule is 2 m high, radius 0.4 m, with a 0.4 m step offset and 45° slope limit. Its 1.5 m camera-pivot height is used in the street preview. Actual collision/navigation behaviour still needs Unity play tests.

## Unity export and artifacts

Use **File → Export → Generated City for Unity (.fbx)** and choose the root city collection. This exports only its mesh objects, triangulates them, preserves UV/material assignments, and uses metre scale with Y-up axis conversion. It restores selection and active object. Hidden/excluded city objects and non-unit scene scales are rejected instead of silently omitted/rescaled. Editable source objects are not joined or destructively triangulated.

Output stays as separate meshes for culling and future chunk/LOD work. No texture baking, Unity materials, colliders, NavMesh, static flags or prop placement are generated. `City_LanePaint` is tagged `decoration_no_collision`; exclude it from collision generation. Route guide curves are omitted from FBX.

Workspace `output` examples:

- `ares_city_base.blend`: 114 detailed buildings, sidewalks/foundations; street-level camera. Guide curves are hidden after the overview render.
- `ares_city_base.fbx`: the same base, 231 static mesh objects, without guide curves.
- `street_level.png`: geometry preview at Ares camera-pivot height.
- `driving_circuits.png`: overview with three colored circuits.
- `city_preview.blend`: lightweight massing example generated by the smoke test.

A JSON text datablock stores the versioned plan. Coordinates are relative to the collection's stored `origin`; road nodes multiply by `block_size`, while lot positions/dimensions are metres. Schema version 2 adds circuit data and street dimensions. v0.4 parcel positions differ from v0.3 with the same seed. No legacy-plan or game-side importer is included.

## Code and verification

`city_plan.py`: pure settings, seeded routing, circuits, parcels. `streets.py`: pure street/terrain tessellation. `styles.py`: building recipes. `building_assets.py`: shell creation/shared materials. `city_operators.py`: Blender adapter. `city_export.py`: city-only FBX export.

Run `python -m unittest discover -s tests -v` for planning, circuit closure/tier diversity across seeds, parcel clearance, density, validation, road-union area, fractional dimensions, seam topology and terrain exclusion.

```
blender --background --factory-startup --python-exit-code 1 --python tests/blender_smoke.py
blender --background --factory-startup --python-exit-code 1 --python tests/blender_streets.py
```

Verified on Blender 5.1.2. The first script covers registration, original operators, styles/interiors/damage, mesh validation and rollback. The second covers UVs, city-only export, selection restoration, triangulation, and world bounds after FBX reimport, then renders examples. The declared Blender 4.5 minimum is not separately tested. Unity import/play-mode tests are pending.

## Next milestones and limits

1. **Natural roads:** replace orthogonal centerlines with constrained curves, bend radii, irregular junctions and parcels. Current circuits still have square turns, not finished driving-track geometry.
2. **Vertical routes:** bridges, ramps, interchanges and terrain obstacles with slope/headroom constraints. Highway currently means a wide at-grade corridor; no bridges exist yet.
3. **Asset variety:** L/U/courtyard footprints, industrial halls, civic landmarks, roof/facade kits and authored district palettes.
4. **Game delivery:** chunk/LOD export, collision proxies, navigation checks, vehicle swept-clearance tests and connected ruin/vegetation dressing.

Street surfaces have open bottoms below ground; they are not watertight solids. Terrain tiles can retain collinear boundary subdivisions. Legacy damaged shells/interiors are not certified manifold or fully navigable. Generation is synchronous; preview and conservative budgets are recommended for large cities.
