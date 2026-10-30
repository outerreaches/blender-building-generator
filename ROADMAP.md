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

See [CHANGELOG.md](CHANGELOG.md) for the details.

## Next

**Buildings**

- Railings, lift doors and cars, furniture.
- Non-rectangular footprints (L, T, courtyard); the tiers and room tilings
  extend to them.
- Balconies and fire escapes on residential facades.
- Interior damage beyond clipping: fallen slabs as ramps, debris on floors.

**City**

- The rest of the retail set: auto repair and an enclosed mall (proposed one
  for radius 6-11, two from radius 12), clustered with the big boxes and strip
  malls at the suburban edge.
- Street patterns: suburban cul-de-sacs, plazas and strip malls repeating near
  their district anchors.
- Irregular block subdivision and curved frontages; parcels are still
  axis-aligned sub-cells of the block lattice.
- More variety: a courthouse or city hall, authored facade kits, rooftop
  clutter, per-district palettes.

**Game delivery**

- Chunk and LOD export, collision proxies.
- Navigation checks and vehicle swept-clearance tests.
- Unity import and play-mode tests.

## Later: terrain and infrastructure

- **Elevation changes**: terrain height across the map, streets on grades,
  stepped pads and retaining walls; streets currently sit on one plane.
- **Railway and subway**: surface rail corridors with crossings, elevated
  sections and subway entrances or stations tied to the transit sites.
- **Bridges**: road and rail bridges over rail cuts, water or dips in the
  terrain, with headroom and slope limits for vehicles.
- **Tunnel entrances**: portals where roads or rail go below grade.
- **Water edge, optional**: a river crossing the city, or a dried-up
  coastline with port infrastructure (quays, cranes, warehouses, a dry
  harbour basin).

## Open decisions

- Condition weights per district are data and cheap to tune (see
  [CITY_GENERATOR.md](CITY_GENERATOR.md#building-conditions)).
- Sites replace whole blocks; small kinds could later share a block with
  ordinary lots.
