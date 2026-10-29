# Architecture (v0.10)

v0.10 replaces the geometry pipeline. This note records why, how the new one
works, the rules it keeps, and what is still open.

## Why: audit of v0.9.9

Measured on 96 buildings (6 styles x 8 conditions x 2 seeds), counting only
real gaps (boundary edges no other face's edge lies along) and coplanar faces
that face the same way and overlap (they z-fight even with backface culling):

| Stage | Real open edge length | Same-facing overlaps |
| --- | --- | --- |
| Shell as built | 0-1.4 m per building | 0 |
| After chunk cuts | 46-352 m | 1-6 |
| After the repair passes | 56-364 m | 138-347 faces |

0 of 96 buildings came out hole-free, and the repair code was the main cause:
`_repair_wall_shell` looked for an inner wall face within 8 cm of each outer
face's centre, but `_dissolve_wall_seams` had already merged outer cells into
large n-gons, so it rarely found one and pasted an unwelded copy over the real
inner face (the z-fighting stripes in `qa_skyA_top0.png`). That happened on
intact buildings too. The other passes only capped boundary shapes they
recognised. Chunks were rectangular because the cutter was an axis-aligned box.

Other findings:

- **Interiors.** Partitions were placed by fixed fractions and then pulled away
  from windows; "apartments" were single rooms off a hall; office floors had
  one meeting room; houses one divider. Interior doors were 0.9 m wide (the
  0.8 m capsule plus 0.08 m skin does not fit) and on upper floors their height
  was measured from the slab underside, leaving 1.95 m clear for a 2.0 m
  capsule. Nothing checked that rooms were reachable.
- **Scale.** Ground floors were the same height as upper floors (no shopfront
  or lobby height); towers had small punched windows; masonry walls were
  0.25 m; slabs 0.15 m; stair flights 1.05 m; gable roofs were open
  underneath (sky visible from the top floor). `window_type` was ignored.
- **Code.** `mesh_builder.py` (2200 lines) and `interiors.py` (2000 lines)
  mixed geometry, layout and Blender calls, so nothing could be tested
  without Blender; legacy code used the global random state; three capping
  functions were dead code.

## Pipeline

```
params ─▶ spec.BuildingSpec ─▶ layouts.plan_building ─▶ damage.BreakField ─▶ shell.build_building ─▶ MeshData
          storeys, tiers,       rooms, doors, stairs,     standing height       closed solids          │
          facade bays           slab holes                over the footprint                           ▼
                                                                                  mesh_builder (Blender): BMesh, merge, UVs
```

Everything left of `mesh_builder` is pure Python and runs under plain
`python3`, so the tests check real buildings without Blender.

| Module | Role |
| --- | --- |
| `dims.py` | Dimensions derived from the Ares player (below) |
| `spec.py` | Storeys (ground floor may be taller), tiers (podium/setback/patio/arcade/pilotis), facade bay grids, openings |
| `layouts.py` | Interior programs as room tilings; resolver; partitions, doors, stairs, slab holes |
| `damage.py` | `BreakField`: ragged top + polygonal craters; breach outlines |
| `solids.py` | Closed solids: walls from 2D outlines, contoured slabs, boxes, prisms |
| `shell.py` | Assembles the building; trims broken windows; facade details |
| `rubble.py` | Mounds, piles and fills as closed solids |
| `meshdata.py` | Plain mesh container and edge checks |
| `mesh_builder.py` | Blender adapter (BMesh, coplanar merge, UVs, seams) |

## Rules the geometry keeps

1. **Every element is a closed solid built from its final outline.** A wall is
   the region under its top profile minus its openings, extruded through its
   thickness, with a strip along every boundary edge. Damage changes the
   outline before anything is built; nothing is cut or patched afterwards. The
   wall builder splits the outline into columns at every vertex and crossing
   and gives each face every vertex on its sides, so faces meet without
   T-junctions.
2. **No same-facing coplanar faces.** Solids touch only with opposite-facing
   faces (wall ends against wall faces, slabs against wall inner faces,
   partitions under slabs), which are hidden. Projecting features use
   distinct embed depths so their hidden back faces never share a plane.
3. **One damage field.** Facade walls, slabs, partitions and stairs all read
   the same `BreakField`, so they agree on what is missing.
4. **Partitions meet facades only on solid wall** (bay boundaries, or the
   solid stretches between openings), so they never land on a window.
5. **Every room is reachable** through a door the player fits, from a street
   door on the ground floor or the stair above it.

The tests enforce 1, 2, 4 and 5 for every style and condition.

## Damage model

`BreakField.height(x, y)` is the standing height over the footprint:

- **Ragged top** (weathering): the v0.9 wall-top profiles (median-smoothed,
  slope-limited), a ragged storey above the break line, the floors above it
  removed inside. Partitions of the broken storey stand as low stubs.
- **Craters** (collapse): a jagged plan polygon with a broken floor height and
  sloped sides (height grows with distance from the polygon), optionally
  terraced at the slab lines. Facades break in diagonals and steps; slabs step
  back storey by storey along contoured, polygonal edges.
- **Blasts**: bounded volumes one to three storeys high, mid-height, with the
  floors above intact. Walls get ragged holes (open at a corner the blast
  took), intermediate slabs and partitions go, stair flights in them go, and
  debris lands on the blown floor and the street below.
- **Collapse archetypes**, one per building by seed (weights favour corner
  collapses; cleave/gutted need 4+ storeys, blowouts 5+), placed on the tier
  standing at their height so setback towers break where their walls are:

  | Type | Look |
  | --- | --- |
  | Corner | Corner collapse with a higher lobe; a bay failure on taller buildings |
  | Stepped | Corner collapse breaking storey by storey (ledges at slab lines) |
  | Shear | One side sliced off along a diagonal plane rising across the plan |
  | Cleave | Split along a plan diagonal; one half gone above a low break |
  | Sawtooth | Two to four bites of different depths along the roofline |
  | Gutted | Facades stand, the middle of the floor plates has fallen in |
  | Blowout | One or two multi-storey holes blown through mid-height |

  `params['collapse']` forces a type; tall weathered towers draw from the
  milder sawtooth, blowout and corner.
- Under craters the top only weathers lightly (craters do the heavy damage).
- Windows the break passes through above the sill are filled, so broken walls
  read as masonry rather than holes in thin spikes.
- **Breaches** (exposed fills) and **blast holes** are jagged openings that
  replace whole windows.

The ground storey never breaks (`min_height`), so entrances stay usable.

## Interiors

Programs tile each storey with rectangles and name each room's parent:

| Profile | Plan |
| --- | --- |
| Residential | Double-loaded corridor, stair core, lobby at the street door; flats with hall, bath, kitchen, living room, bedroom. Walk-up plan on small plates |
| Storefront | Stair hall between two shops with back stores (own street and back doors); flats above |
| House | Hall and stair; living room, kitchen (back door), WC; bedrooms and bath above |
| Office | Central core (stair, 0-4 lifts, WC); lobby or retail podium on the ground floor; open plan or perimeter offices above; plant floors |
| Warehouse | Open hall, office and WC at a front corner, back stair |
| Bar | Bar room with counter, kitchen behind, private rooms upstairs |

The resolver keeps each requested parent when a door fits on the shared wall
(stair doors only at the entry landing), otherwise re-parents the room to the
best reachable neighbour (same flat first, then circulation). Rooms of one
group (open plans) need no wall. Plans that cannot fit a stair keep only the
ground floor and say so in `plan.notes` and the object's `plan_notes`.

## Dimensions

Sized for the Ares player (`Player.prefab`: capsule 2.0 m x 0.8 m, 0.08 m skin,
0.4 m step, reference doorway 2.2 x 1.2 m):

| Item | Value |
| --- | --- |
| Interior door | 1.2 m wide, 2.3 m clear above the finished floor |
| Street door | >= 1.4 m; main entrances of lobbies 2.6-3.2 m |
| Corridor | >= 1.8 m |
| Stair | 1.3 m flights, riser <= 0.19 m, tread 0.27 m, 1.3 m landings (compact/steep variants for small plates, riser <= 0.25 m) |
| Slab / roof | 0.25 m / 0.3 m |
| Partition / core wall | 0.15 m / 0.25 m |
| Storeys | residential 3.2 (ground 3.4), old town 3.6 (shops 4.2), offices 3.9 (lobby 4.8-7.8), houses 3.1, sheds 5.5 |

## Tests

- `python3 -m unittest discover -s tests` (no Blender): solids are watertight
  under random profiles and openings; every style x condition building is
  watertight with no z-fighting; layouts are complete, reachable, door-sized,
  window-clear and walkable; plan and style tests.
- `blender -b --factory-startup --python tests/blender_watertight.py`: every
  operator's meshes have each edge on exactly two faces after conversion and
  the coplanar merge.
- `tests/blender_interiors.py`: stairs reach the top floor, doors, tower cores,
  all lobby types.
- `tests/draw_plans.py OUT`: PNG floor plans (rooms, doors, stairs) for review.

## Open

- Railings, lift doors and cars, furniture.
- Non-rectangular footprints (L/T/courtyard): tiers and tilings extend to them.
- Balconies and fire escapes on residential facades.
- Interior damage beyond clipping (fallen slabs as ramps, debris on floors).
