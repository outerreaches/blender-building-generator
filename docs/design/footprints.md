# Design: non-rectangular footprints

Status: shipped in v0.24.0. Before it, buildings were boxes: one rectangle
per storey (set back above a podium), four facades, a plan tiling one
rectangular plate. v0.24 adds L, T, U and courtyard (O) buildings, built by
the same pipeline and keeping its guarantees: closed solids, no z-fighting,
windows on piers, every storey reachable by a stair the player can climb.

## Footprint

`params['footprint']` is a list of rectangular **wings** in building space
(x along the front, y to the back), which tile the outline without
overlapping; the first is the **main wing**, along the street front. Absent
or a single rectangle, the building is the box it always was (byte for byte).

| Shape | Wings |
| --- | --- |
| L | main wing + one wing at the back, flush with the left or the right side |
| T | main wing + one wing from the middle of its back |
| U | main wing + a wing at each end of its back |
| O | front and back bars + two side wings between them round a court |

Compound buildings have one tier: no setbacks, pilotis, arcades or patios.
Their roofs are flat (per-wing pitched roofs come later, for houses).

## Shell

- **Outline.** The union of the wings is traced into its boundary: an outer
  ring and, for a courtyard, an inner ring. Every edge is a facade, named by
  its outward normal (front, right, back, left); a side can have several.
  Facades on the court face into it.
- **Corners.** At a convex corner the front/back wall covers the corner
  square and the side wall stops a wall's thickness short (as now). At a
  concave corner both walls end at the vertex: their solids touch along the
  corner line and the room's inside corner is the two wall ends.
- **Slabs and roof** cover the interior region, the outline inset by the
  wall thickness; the rest of the bounding rectangle (the notch, the court,
  the walls) is cut out of the slab grid as holes.
- **Damage** is the same break field over the bounding rectangle. A
  facade's ragged top is read from its side's profile at its own position
  along that side, so facades on one side share one weathering line.
- **Details** (cornices, pilasters) stop where two facades meet at a
  concave corner, so they never overlap there.
- **Rubble** fills each interior rectangle; debris stays in the interior
  rectangle it falls in.

## Interiors

Each wing gets a **zone**: its rectangle inset by the wall thickness on any
side that is (partly) exterior, and reaching to the neighbouring zone across
a joint. Zones tile the interior but for a wall-thickness square at each
concave corner. `compound.plan_compound` plans them together (the
rectangle programs assume one plate, and their corridors would not meet):

- **Corridors.** Each zone runs a corridor along its axis: a spine along the
  main bar and the bars, a branch up each wing. Where a wing meets a bar its
  corridor carries on through the bar's row to the spine (a stub); all are
  one open corridor group. A zone too narrow for rooms both sides gets a
  corridor along one side; narrower still, a run of rooms.
- **Walls on solid wall.** A wall may meet a zone side along a joint
  anywhere, along a facade only clear of its openings (`ZoneSide`); corridor
  walls must meet both ends of their zone, so they are searched on a fine
  grid where both are solid. Long facades get a pier where a joint's wall
  meets them (bays laid out segment by segment).
- **Stair and lobby.** The stair stands in a row of the main bar (flights
  across the row, its door on the corridor, in any stair mode before
  flights along the row), its walls on clear spots, wider than its flights
  where the piers ask; the lobby at the street door.
- **Units.** The rows between are cut at piers into flats (hall strip on
  the corridor side, living room and bedroom out), offices, shops with
  street doors (old town ground floors) or studios. Sheds are one open hall
  over every wing, with an office at the front and the stair at the back.
- **Court.** A courtyard gets a passage from the corridor to its court
  facade, as wide as the bays its door takes.
- The plan then goes through the usual steps: structure (`PARTITIONS`,
  `BEARING`), resolve (every room reached), walls, doors, slab openings.

## City

- Each style picks a shape by lot size and seed: residential L, U and
  courtyard blocks; old town L and courtyards; brutalist L, T and U;
  industrial L sheds with an office wing. Downtown towers and houses stay
  rectangular for now.
- Lots keep their rectangle: foundations and pads cover the bounding
  rectangle, so a notch or a court is a paved yard at floor level (grading
  round the true outline is planned for later).
- The metadata lists each building's `footprint` (shape and wings).

## Phases

1. Shell: outline, facades, corners, slabs, roof, damage, rubble, details.
2. Interiors: zones, the zone view of the spec, wing programs, merged plans.
3. City: shapes by style, recipe, metadata, Blender, renders.
