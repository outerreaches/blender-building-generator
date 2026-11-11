# Design: elevation, infrastructure levels and the megacity

Status: v0.21 (Rolling hills), v0.22 (Terraced) and v0.23 (Raised
highway) done; the rest planned.

**As built in v0.23:** the highway is raised (`highway: RAISED`, the
default; `GRADE` keeps the at-grade one, plan for plan). It runs straight
along the y = 0 lattice line, which no street takes, on a 25 m deck whose
top clears the ground and the streets under it by 6.5 m at no more than 3%
(an envelope of 3% cones over the required heights, sampled every 8 m,
then widened and averaged over 48 m either way to round its crests and
sags without breaking the clearance or the grade). It comes down to grade
beyond the map, where the outer road starts (`deck`). Interchanges are
diamonds at main street crossings ten blocks apart, chosen on hills where
the deck a ramp's length away stands least above the cross street (over
the ungraded hills). Each ramp runs at grade 10 m past the cross street's
footway, climbs at 6% (eased; longer, up to 200 m, on hills, and steeper
only where a street crossing under it needs the headroom) and tapers into
the deck over 40 m. The crossings one and two blocks from an interchange
(three on hills) are closed and the network rejoined round them. Lots,
pads and superblocks keep 3.5 m clear of the decks and never span the
line; terraces keep a block off it. On hills the line is graded as a
highway. This covers the raised highway of §4 and the grade separation,
diamond interchanges and tapered ramps of §4b; the free-flowing alignment
and partial cloverleafs are still to come.

**As built in v0.22.7:** the ground is graded to every foundation
(`Grading._shaped`): level for `PAD_SHOULDER`, then cut at `PAD_CUT_SLOPE`
or filled at `PAD_FILL_SLOPE`, meeting the footways near a building at the
same slopes; where two foundations disagree the nearer wins. A house that
cannot blend into a footway beside it (`_walled_house`) is dropped with its
row. Under a viaduct's start the ground and the walls stay under the road.

**As built in v0.22.6:** a terrace takes two or three natural sides
(`SOFT_SIDES`), so it seeds where two of its faces look out of the city;
a terrace with fewer such faces is not built.

**As built in v0.22.5:** the plateau defaults to 9 m, and a terrace's
hill target climbs past its top (`HILL_KNOTS`: 1.2 times the rise a block
out, 1.6 three blocks out, nothing at eight), so the terrace is a bench in
a hillside rather than a hilltop.

**As built in v0.22.4:** a terraced city's lattice is extended by 20
blocks of wild land, graded with it (noise hills scaled as the city's,
fading to level over the last four blocks; the highway's rows pinned level
beyond the map). Each terrace's hill is a grading target on the open ground
beyond its natural sides (its full rise at the top's edge, falling to
nothing over six blocks); the edges down a slope are free of limits, since
the terrace's rise is not in the base heights. The wild land is meshed as
facets on the same snapped lines; a few centimetres separate it from the
city ground where the fine grid crosses facet creases.

**As built in v0.22.3:** every corner of a terrace's blocks is on top, so
the streets round its edge run along the top with the wall beyond them;
terraces stand in downtown and residential districts at the city's edge,
fully built, with their natural sides facing out into the open ground
beyond the city.

**As built in v0.22.2:** slopes and the hills under a terraced city are
flat facets (low-poly); ramps turn on wide chorded curves and climb at a
steady grade along their route; viaduct abutments stay under the road; a
ramp always meets a street on top.

**As built in v0.22.1:** each terrace falls naturally to the hills on one
to three random sides (a one-block slope band; rounded corner blocks where
two meet). High ramps stand on viaducts (piers, cap beams, parapets, flat
abutments) with the ground running on under them. Retaining walls holding
ground up stand back from the footway behind a 2.5 m verge, and walls
dropping more than 1.5 m carry parapets. No transit stops on ramps or
grades over 4%.

**As built in v0.22:**

- **Terraced = hills + terraces.** The Rolling base (relief) carries one
  plateau (default 18 m) and a few 4.2 m podiums of whole blocks, rather
  than quantising all the ground into benches. The hills under a terrace are
  graded nearly level (0.4 m per block edge), so it stands its full height
  all round.
- **Laid out first.** Terraces are chosen on the main streets, before the
  driving circuits and the local streets, which then keep to them: circuits
  never climb a terrace, a local street up its face becomes a stair, and no
  street runs through a terrace at its foot level.
- **Ramps** run out from the terrace (two for the plateau, every crossing
  for a podium) at no more than 10%, easing flat where they meet streets or
  turn; the side streets along a ramp's raised junctions are closed. Where
  the cuts leave streets apart, short new streets join them back on.
- **Walls from the ground's own edges.** On a terraced city the ground is
  cut at the footways' iso-line on the street mesh's sample grid; walls
  join each ground edge to the footway (or stair) above or below it, and
  terrace edges are snapped to that grid (within 0.75 m of the block line).

**As built in v0.21:**

- **Level map edge.** The map's edge stays level with the flat wasteland and
  the outgoing highways. That caps how high a small map's hills can rise,
  about 12 m at radius 6. Carrying the terrain on into the wasteland comes
  with the Terraced style in v0.22.
- **Grade limits** are highway 4%, arterial 5%, collector 6%, local 8%, and
  open ground 12%.
- **Retaining curbs.** Curb skirts on terrain are 2.5 m deep, so a footway
  above a lower pad shows as a retaining curb wall. Flat cities stay exactly as they are: every
feature below is off until its setting is changed.

## Reference

A hand-built hub map from the game is the target this design is calibrated
against. Its walking surfaces sit on a few clear levels, not on rolling
hills:

| Level | Height | What stands there |
| --- | --- | --- |
| Sunken road | about −10 m below the streets | a road in a cutting, leading to a tunnel |
| Downtown streets | 0 m (the base) | the street grid and low-rise ruins |
| Podium | +4 to +5 m | a walled compound on a raised platform |
| Plateau | about +22 m | the high-rise district |
| Raised highway | up to the plateau | an elevated road into the city |

The levels are joined by ramps, stairs and retaining walls. The map also has
road tunnels out of the city, overgrown train tracks, a bus station,
skybridges between towers, and sewers reached through manholes.

## 1. Terrain

**Height field.** `terrain_height(x, y)` is a pure function of the seed and
settings, sampled everywhere. Nothing stores a mesh of it, so the plan, the
meshes, the metadata and the heightmap export all agree.

**Settings:**

- **Terrain:** Flat (the default, unchanged), Rolling or Terraced.
- **Relief:** 0 to 30 m across the map.
- **Terrain seed:** follows the city seed by default.

**Styles:**

- **Rolling:** two or three octaves of smooth noise with 300–800 m
  wavelengths, and slopes capped at 6–8% so every block stays buildable.
  An optional valley or ridge bias gives the city a reason to sit where it
  does.
- **Terraced** (as in the reference):
  - The ground is quantised into benches about 5 m apart.
  - Each bench is level, and the steps between benches are escarpments
    with retaining walls.
  - A bench boundary follows block edges, never crossing a block, so every
    block is on a single level apart from its pads.
  - One large step of about 20 m (the plateau) is allowed per map.

**Organic cities.** The relief follows the outline: the highest ground can
sit inside a lobe, and the edge can fall away toward the wasteland.

## 2. Roads on grades

**Junction heights.** Every lattice node gets a height from the terrain.
The heights are then relaxed until every street segment stays under its
type's grade limit:

| Road type | Grade limit |
| --- | --- |
| Highway | 4% |
| Arterial | 6% |
| Collector | 8% |
| Local | 10% |
| Rail | 2% |

**Profiles.**

- Junctions are flat platforms.
- Segments get parabolic vertical curves.
- The street mesh samples its height along the centreline, with a 2%
  crossfall toward the gutters.

**Cut and fill.** The difference between the road and the terrain is cut
(the road lies below the ground) or fill (above it). The cross-sections in
§3 resolve it.

**Escarpments** (Terraced style):

- A street that would cross a step over the grade limit becomes one of:
  - a ramp street running along the escarpment: for the 22 m step, about
    7 blocks at 6%, or 4 blocks at 10% on a local street;
  - a pedestrian stair street, closed to vehicles;
  - a dead end at the retaining wall with a guard rail.
- At least two vehicle ramps reach every bench.
- The raised highway is the other way up to the plateau (§4).

## 3. Cross-sections, pads and walls

**Cross-section by context:**

| Context | Section |
| --- | --- |
| Downtown, old town, residential | Curb and footway; the ground is graded to the footway at the lot line |
| Suburbs, towns, outskirts | Gravel shoulder, then a V-ditch or trapezoid swale 0.6–1.0 m deep and 2–3 m wide |
| Highways | Wider shoulders, ditches, embankments and cuttings |

Embankments and cuttings slope at 1:2 and blend back into the terrain.
Culverts take ditches under driveways and cross streets.

**Pads:**

- Every lot and site gets a level pad at its frontage footway height, so
  every door is at street level.
- Buildings keep flat floors: the floor plans, the shell and the interior
  facts do not change.
- The ground inside a block is graded between pads, following the same idea
  as the hand-built maps: level each footprint to a common height, then
  blend the edges back into the land.

**Plinths and retaining walls:**

- On the downhill side, the foundation is extended down to the graded
  ground as a plinth (a closed solid, like everything else).
- Where neighbouring pads, or a pad and the footway, differ by more than
  0.4 m (the player's step offset), a retaining wall stands between them.
- Steps cross the wall wherever a door, path or gate needs to get past it.

**Tests:**

- Grades along every road centreline stay under the limit.
- There is no gap or step over 0.4 m where a footway meets a pad or the
  ground.
- Every door threshold is at its pad height.
- Walkable ground is under 45°.
- Every gate is checked against an injected defect (a negative control).

## 4. Levels: elevated, at grade, below grade

**Structure types.** Every road segment gains a structure type and a height
profile:

| Structure | What it is |
| --- | --- |
| at-grade | on the ground, as today |
| embankment / cutting | on fill or in a cut |
| viaduct | a deck on piers |
| tunnel | below ground |

**Portals and junctions.**

- Portals and ramps stand wherever the structure type changes.
- Only segments on the same level meet at a junction.
- Segments on different levels cross without one: an overpass or an
  underpass.

**Corridors.** Rail, subway and elevated highways are corridors: a path
with its own height profile, cross-section and clearance envelope:

| Corridor | Clearance |
| --- | --- |
| Under a road deck | 5.0 m |
| Under rail | 6.5 m |
| Subway | 4.5 m inside the tunnel |

The plan reserves each corridor's right of way, so no lots stand on it.
Piers go in medians or inside blocks.

**First versions:**

- **Raised highway** (built in v0.23; see the top): one deck level on
  piers along a corridor, with ramps down to the arterials. Still to come:
  in the Terraced style, a way onto the plateau, and the deck listed with
  the roads as `structure: viaduct` (today it has its own `freeway`
  section).
- **Road tunnels out of the map:** portals cut into the relief at the map
  edge. The tunnel mouth is the level boundary, as in the reference.
- **Rail:**
  - at grade, with level crossings, or in cuttings;
  - a freight siding;
  - stations as sites.
- **Subway, routes only:**
  - The corridor runs 8–12 m below the street, under arterials.
  - Stations are sites: a street entrance with stairs going down, a
    headhouse, and ventilation grilles.
  - The metadata lists each route and its station positions, so walkable
    tunnels and platforms can be added later without moving anything.

## 4b. Freeway (North American practice)

The at-grade highway follows the street lattice, with filleted right-angle
turns; since v0.23 the raised one runs straight across the city instead,
with diamond interchanges. A proper freeway goes further:

- **Alignment.** A free-flowing alignment that ignores the lattice: tangents
  joined by circular curves (with spiral transitions where they help).
  - The curve radius suits the design speed: about 440 m at 100 km/h with
    8% superelevation, so curves are gentle and there are no right-angle
    turns.
  - Grades stay at 3–4%.
- **Grade separation.** The freeway runs on embankment, on a viaduct or in a
  cutting (the levels of §4). Every street it meets passes over or under it.
- **Interchanges** at the arterials it crosses, spaced as far apart as the
  map allows:
  - diamonds, or partial cloverleafs where space allows;
  - on-ramps with acceleration lanes and off-ramps with deceleration lanes,
    tapered into the through lanes;
  - ramp grades and curve radii for ramp speeds.
- **Cross-section.** Lane, shoulder and median widths per AASHTO practice,
  with a median barrier.

The megacity's stacked decks (§7) build on it.

## 5. Underground (later, groundwork now)

**Subway (later).** Walkable tunnels and platforms are built inside the
corridors reserved in §4, with platform rooms listed like other interior
rooms.

**Sewers.** The plan gains the sewer network as data first:

- **Layout:**
  - Trunk sewers run under arterials: 2–3 m wide and walkable.
  - Laterals run under local streets: too small to walk.
  - Manholes are markers at junctions and every 60–80 m.
- **States per segment** (seeded):
  - *reachable:* walkable, with a manhole shaft;
  - *collapsed:* blocked, with rubble and dead ends;
  - *breach:* opens into a subway tunnel.
- **Metadata from the start:** manholes and the network graph appear early,
  so the game can place manhole props and plan routes before the tunnels are
  modelled.

## 6. Heightmap export

The FBX exporter can also write a heightmap of the graded ground (terrain,
pads, roads and ditches, without buildings) as a separate file:

- `<name>.heightmap.raw`: 16-bit little-endian, square, 2^n + 1 samples
  (513, 1025 or 2049), as Unity Terrain imports.
- `<name>.heightmap.json`: origin, size in metres, minimum and maximum
  height, sample spacing, and the same Unity axis convention as the city
  metadata.

It is useful for gameplay sampling, AI and a Unity Terrain for the far
wasteland, even while the city ground stays a mesh.

## 7. Megacity preset

The aim is the scale of Akira or Judge Dredd at a cost the game can run.

**Layout:**

- **Megablocks:** 2×2 or 3×3 groups of lattice blocks merged into single
  buildings, 110–170 m on a side and 40–150 floors, on podiums.
- **Undercity:** the street level, in permanent shade.

**Stacked decks:**

- Two to four highway levels (for example +12, +28 and +46 m) along chosen
  street lines between megablocks.
- Where decks on different levels cross, they pass over and under each
  other, joined by straight or spiral ramps at block corners.
- Piers stand in the street medians.

**Skybridges** join towers at their sky-lobby floors.

**Ruin:**

- collapsed spans;
- hanging deck ends;
- fallen deck sections that become ramps down to the street (gameplay
  routes between levels).

### Performance

- **Instanced modules.** A megablock is a podium plus repeated floor
  modules plus a crown. Decks are repeated span modules, piers are repeated
  pier modules. The FBX carries each module once, and the metadata lists
  the placements so Unity can instance them (GPU instancing or static
  batching). Visible scale grows with placements, not triangles.
- **Massing above the playable floors.**
  - Only the floors the player can reach are modelled with real openings
    and listed interiors: the podium, the lobbies, the sky lobbies and the
    skybridge levels.
  - Floors above them are closed massing with windows left to the material
    (no cut openings), one mesh per tower section.
- **Skyline ring.** Beyond the play area, a ring of very low-polygon
  megastructure silhouettes gives the horizon the city's scale for almost
  no cost (the reference map's background ring is 15 polygons).
- **Chunks and LODs.** Chunked export by cell, a lower LOD per chunk
  (shell without openings), and occlusion: dense canyons occlude well, so
  Unity's baked occlusion culling does most of the work.
- **Budgets.** Agreed targets, checked by a test on every generated
  megacity:
  - triangles per chunk;
  - instanced draw count;
  - total unique meshes.

## Phases

| Version | Scope |
| --- | --- |
| v0.21 (done) | Terrain field (Flat, Rolling), road grading, pads and plinths, ground and street meshes on the terrain, metadata heights, heightmap export |
| v0.22 (done) | Terraced style: plateau and podiums behind retaining walls, ramp streets and stairs, exact walls where ground meets a street |
| v0.23 (done) | Raised highway: a straight viaduct across the city, the streets passing under it, diamond interchanges with tapered ramps, at grade again in the wasteland |
| v0.25 (done) | Cross-sections: rural streets with shoulders, ditches and culverts (Flat and Rolling; Rural Streets setting); the highway in cuttings and on embankments; hills continued past the map's edge (Rolling); forecourts following sloping streets |
| v0.26 | Levels: structure types, road tunnels at the map edge, rail with crossings and a freight siding, subway routes with station entrances, sewer network data with manholes |
| v0.27 | Freeway (§4b): free-flowing alignment with gentle curves, partial cloverleafs |
| v0.28 | Megacity preset: megablocks, stacked decks, skybridges, collapsed spans, instanced modules, skyline ring |
| Later | Walkable subway tunnels and platforms; walkable sewers with collapsed sections and breaches into the subway |
