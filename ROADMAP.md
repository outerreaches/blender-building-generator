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

See [CHANGELOG.md](CHANGELOG.md) for the details.

## Next

**Buildings**

- Non-rectangular footprints (L, T, courtyard); the tiers and room tilings
  extend to them.
- Balconies and fire escapes on residential facades.
- Interior damage beyond clipping: fallen slabs as ramps, debris on floors.

**City**

- Irregular block subdivision and curved frontages; parcels are still
  axis-aligned sub-cells of the block lattice.
- More variety: a courthouse or city hall, authored facade kits, rooftop
  clutter, per-district palettes.

**Game delivery**

- Chunk and LOD export, collision proxies.
- Navigation checks and vehicle swept-clearance tests.
- Unity import and play-mode tests.

## Planned: terrain and infrastructure

Design: [docs/design/elevation.md](docs/design/elevation.md). Flat cities
stay as they are; every feature below is off until its setting is changed.

| Version | Scope |
| --- | --- |
| v0.22 | Terraced terrain (benches and a plateau, with escarpments), and the hills carried on into the wasteland so small maps reach their relief. Cross-sections: roadside ditches outside the dense districts, embankments and cuttings, retaining walls, ramp and stair streets at escarpments, culverts |
| v0.23 | Levels: elevated, at-grade and below-grade structures; a raised highway with ramps; road tunnels at the map edge; rail with level crossings and a freight siding; subway routes with station entrances; the sewer network as data, with manholes |
| v0.24 | Megacity preset: megablocks, stacked highway decks, skybridges and collapsed spans, built from instanced modules with a low-poly skyline ring |

## Later

- Walkable subway tunnels and platforms.
- Walkable sewers: some reachable, some collapsed, some breaking into the
  subway tunnels.
- **Water edge, optional**: a river crossing the city, or a dried-up
  coastline with port infrastructure (quays, cranes, warehouses, a dry
  harbour basin).

## Open decisions

- Condition weights per district are data and cheap to tune (see
  [CITY_GENERATOR.md](CITY_GENERATOR.md#building-conditions)).
- Sites replace whole blocks; small kinds could later share a block with
  ordinary lots.
