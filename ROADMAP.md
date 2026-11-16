# Roadmap

## Shipped

| Version | What |
| --- | --- |
| v0.3-v0.7 | City generator: seeded growth, curved roads with driving circuits, six district archetypes, metro scale and open wasteland |
| v0.8-v0.9 | Interior budget and building conditions: weathered tops, collapses, rubble fills, partial fills, shells, wall rings, rubble mounds |
| v0.10 | Closed-solid geometry, real floor plans sized for the player, polygonal collapses; seven collapse archetypes in v0.10.1 |
| v0.11 | Points of interest (twelve kinds with two to four layouts each) and transit stops; highways running out into the wasteland |
| v0.12 | Dense downtown: party-walled towers built out to the footway, superblocks |
| v0.13 | Small-props switch and city metadata for Unity; walkable stairs, no loose floor pieces, windows kept through damage |
| v0.14 | Interiors for the game: rooms to furnish, lifts, railings and fixtures in the metadata (game assets, not modelled) |
| v0.15 | The rest of the retail set: auto repair and an enclosed mall, with the other retail gathered round it; a water switch |
| v0.16 | Hotels, motels, cinemas and drive-in cinemas |
| v0.17 | Street patterns: suburban cul-de-sacs; plazas and strip malls repeating round their district centres |
| v0.18 | Small-town preset: an old-town main street, low buildings, only a town's sites; suburbs built out, houses round cul-de-sacs (v0.18.1) |
| v0.19 | Organic city shape: an irregular edge with lobes, notches and fingers |
| v0.20 | Cinemas: palace, twin and multiplex filling their pads, stadium seating with seat markers; cul-de-sacs only among houses; one drive-in per city |
| v0.21 | Rolling hills: streets graded to their tier's limit, level pads with plinths and cut slopes, retaining curbs, heights in the metadata, a heightmap export |
| v0.22 | Terraced terrain: a built-up plateau and podiums of whole blocks at the city's edge, walled on some sides and falling naturally into the open ground on two or three others; edge streets along the top; ramps (on viaducts where high) and stairs up to them; retaining walls with parapets |
| v0.23 | Raised highway: a straight viaduct across the city on piers, the streets passing under it; diamond interchanges whose ramps climb alongside the deck and taper into it; at grade again out in the wasteland. Stairs and walls in every standing building, gutted ones with rubble on the floors, column frames (v0.23.4); superblocks in the old town, residential, brutalist and industrial districts (v0.23.5); courtyards, estate grounds and uneven plots (v0.23.6) |
| v0.24 | Building footprints: L, T, U and courtyard buildings made of wings, with corridors along every wing, a stair to every storey and a door out to the court; whole-block buildings in the old town, residential and brutalist districts |
| v0.25 | Cross-sections: forecourts that follow a sloping street (no more stepped bases), the ground graded to them; wild hills round Rolling Hills cities, the highway leaving through them in cuttings (with ditches) and on embankments; rural streets with gravel shoulders, V-ditches, culverts and driveways |
| v0.26 | Game delivery, part one: a shell and a massing level of detail for every building; the ground, streets and other city-wide meshes exported as tiles |
| v0.27 | Ground materials by district; balconies on brutalist and residential blocks; stairs in every damaged site building; drill and clock towers with stairs |
| v0.28 | Basements, part one: a storey or two under many buildings, their rooms and an underground graph in the metadata |
| v0.29 | Tunnels between basements: through shared walls, under open ground and under streets, on two storeys, in the underground graph |
| v0.30 | Sewers: trunks, crouch-height laterals, chambers and manhole shafts cut through the street, collapses and breaches into basements; graph facts (depth, exits, bridges) |
| v0.31 | Subway: a line with stations, platforms, ticket halls and street entrances, utility branches with exits, sewers ending in the halls, basement accesses; drops from old town and brutalist basements into the sewers; ditches only in the suburbs |
| v0.32 | Subway, part two: curves instead of square turns; side and island stations with wider platforms; ticket halls with fare lines, booths and bathrooms; entrances in the open ground beside the footway; sewers ending beside the halls through service rooms; hallways off the line to utility rooms, emergency exits and the sewer above; track centre lines; underground materials of their own; turning loops past the end stations; kiosks, benches and bins; basins in the sewers' chambers |

See [CHANGELOG.md](CHANGELOG.md) for the details.

## Next

**Buildings**

- Pitched roofs over L-shaped houses (per-wing roofs), so suburbs get them too;
  set-back towers on non-rectangular podiums.
- Fire escapes on residential facades; railings instead of solid upstands on balconies.
- Underground, next: a second subway line with a transfer station, more direct access from buildings to the halls, tunnels that turn a corner (larger clusters), basements under site buildings, sewer outfalls at the city edge, silted sections; edge points of roofs and broken floors in the metadata.
- Interior damage beyond clipping: fallen slabs as ramps.

**City**

- Irregular block subdivision and curved frontages; parcels are still
  axis-aligned sub-cells of the block lattice.
- More variety: a courthouse or city hall, authored facade kits, rooftop
  clutter, per-district palettes.

**Game delivery** (levels of detail and ground tiles shipped in v0.26)

- One combined massing mesh per tile for the far distance, and occluders.
- Collision proxies: ramps for stairs, rubble as low hulls, no trim.
- Surviving connectivity in the metadata: rooms and openings as flat
  tables with ids, reachability from the street, road edges mapped to their
  polylines.
- Vehicle swept-clearance tests; play-mode tests.

## Planned: terrain and infrastructure

Design: [docs/design/elevation.md](docs/design/elevation.md). Flat cities
stay as they are; every feature below is off until its setting is changed.

| Version | Scope |
| --- | --- |
| v0.33 | Levels: elevated, at-grade and below-grade structures; road tunnels at the map edge; rail with level crossings and a freight siding |
| v0.34 | Freeway to North American practice: the raised highway on a free-flowing alignment with gentle curves (curve radii and grades for its design speed) instead of straight along the lattice, and partial cloverleafs where there is room |
| v0.35 | Megacity preset: megablocks, stacked highway decks, skybridges and collapsed spans, built from instanced modules with a low-poly skyline ring |

## Later

- Ditches on Terraced cities' rural streets (their footways meet the
  retaining walls), and a Terraced city's highway through its hills rather
  than along a valley floor.
- Grading round compound buildings' outlines: their notches and courts are
  paved yards at floor level for now.
- **Water edge, optional**: a river crossing the city, or a dried-up
  coastline with port infrastructure (quays, cranes, warehouses, a dry
  harbour basin).

## Open decisions

- Condition weights per district are data and cheap to tune (see
  [CITY_GENERATOR.md](CITY_GENERATOR.md#building-conditions)).
- Sites replace whole blocks; small kinds could later share a block with
  ordinary lots.
