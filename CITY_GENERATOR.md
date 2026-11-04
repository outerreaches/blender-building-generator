# City generator

This generator supplies the main static environment for a low-poly first-person Unity game. Existing signs, ruined cars and other props remain separate assets.

## Try it

Install the add-on as described in the [README](README.md#installation) (remove an old version and restart Blender first; each city collection records the `addon_version` that made it). Use **Shift+A → Mesh → Generate City**, **Generate Building by Style** or **Generate Site (Point of Interest)**. Start with **Layout Preview**; select **Detailed Shells** for windows, doors, floors, damage and optional interiors. Both modes use the same plan. Each run creates a new collection at the 3D cursor. Undo removes that run; failure rolls back its own objects.

The original single-building and bulk operators remain available. Architecture uses six district archetypes built from rectangular shells:

| District | City heights | Differences |
| --- | --- | --- |
| Downtown | 8–24 floors, 3.9 m storeys | Lobby (grand 6.4–7.8 m, retail podium, arcade or pilotis), curtain/ribbon/punched facades, podium and setbacks from 10 floors, plant floors every 12, plant room, stepped crown or mast |
| Old town | 2–4 floors, 3.6 m (shops 4.2 m) | 0.45 m masonry, tall windows, shopfronts, cornices and pilasters |
| Residential | 2–5 floors, 3.2 m (ground 3.4 m) | Regular apartment windows, parapets, cornices on some |
| Brutalist | 4–8 floors, 3.3 m | 0.45 m walls, deep grid of square windows, often lifted on pilotis |
| Industrial | 1–2 floors, 5.5 m storeys | Wide low sheds, high window band, 3.6 × 4.0 m loading door, no parapet |
| Suburban | 1–2 floors, 3.1 m storeys | Small footprints, gable roof over a ceiling, front yard |

## Controls

| Control | Effect |
| --- | --- |
| Preset | City (default), or [Small Town](#small-town): no towers and no big sites. Choosing one sets the sizes and densities that suit it |
| Seed | Repeatable locations, roads, lots and per-building seeds |
| Radius / Block Size | Square extent in blocks/metres; 6 × 56 is about 672 m across |
| City Shape | Square (default): the city fills the map. Organic: an [irregular edge](#city-shape) |
| Irregularity | How far an organic edge wanders, 0 (round) to 1 (default 0.6) |
| Terrain | Flat (default), [Rolling Hills](#terrain) or [Terraced](#terraced) |
| Relief | Hills: metres from the lowest ground to the highest, 0–40 (default 30) |
| Plateau Height | Terraced: how far the plateau rises above the streets round it, 0–30 m (default 9; 0: none) |
| Podiums | Terraced: low raised compounds of a few blocks, 0–3 (default 1) |
| Primary / Secondary Locations | District seeds (default 6: downtown core, three midtown styles, industrial and suburban edges) and smaller growth destinations |
| Driving Circuits | Target count of distinct highway-to-district circuits, 0–8 |
| Core Radius Fraction | Distance over which core density stays constant |
| Core / Outskirts Density | Lot occupancy probabilities, smoothly blended radially |
| Local Road Density | Additional connected branches and incidental street loops |
| Road Corner Radius | Fraction of the tier fillet radius: 26 m highway, 18 m arterial, 12 m collector, 8 m local. 0 keeps square turns |
| Minimum Road Setback | Extra parcel clearance beyond street/ramp reservations |
| Sidewalk Width / Curb Height | Default 2 m footway and 0.15 m curb |
| Wasteland Extent | Open ground beyond the city edge, default 12000 m. The city stays inside the invisible game walls; the ground keeps going to the horizon |
| Highway | Raised (default): a [viaduct straight across the city](#raised-highway), the streets passing under it, with diamond interchanges; at grade again out in the wasteland. At Grade: a street like the others, through the city's junctions |
| Highway Reach | How far the highways continue past the city edge, default 3000 m (never past the wasteland); the last 40% breaks up into the ground. 0 ends them at the edge |
| Architecture | Mixed districts or one style throughout |
| Building Damage | Base damage; district and condition scale it, and it does not reroute roads |
| Interior Ratio | Fraction of enterable buildings that get full interior layouts (default 0.25) |
| Building Budget | Stable sampling cap on eligible lots; reports when capped |
| Downtown Superblocks | Share of downtown local streets closed so blocks join into 2 x 1 and 2 x 2 superblocks (default 0.35) |
| District Superblocks | Chance that blocks of an old town, residential, brutalist or industrial district join into a 2 x 1 or 2 x 2 [superblock](#district-superblocks) (default 0.5; 0 keeps every street) |
| Small Props | Model benches, gas pumps, lamps, bollards, bins, dumpsters, tables, play equipment, goals, booths, hydrants, cart corrals, tyre stacks and drive-in speaker posts (default on). Off: no meshes for them; the metadata still lists every one for the game to place |
| Water | Model water in fountains and other basins (default off: they are dry, and the metadata's `water` markers say where the game adds its own) |
| Metadata Space | Coordinate space of the city metadata: Unity (default) or Blender |
| Interior Metadata | List every building's rooms, lifts and railings in the metadata (default on). Off: a much smaller file; counters, desks and cinema seats are still listed |
| Points of Interest | Reserve blocks for gas stations, fast food, schools, hospitals, police and fire stations, transit, parks, parking and malls, and put transit stops on the footways (default on) |
| Worn Lane Markings | Optional broken paint on highway/arterial/collector roads |
| Show Driving Route Guides | Colored curves, excluded from FBX export |

| Starting layout | Core radius | Core density | Outskirts density | Local roads |
| --- | --- | --- | --- | --- |
| Dense core in wasteland | .2 | 1 | .03 | .65 |
| Scattered ruined districts | .35 | .75 | .15 | .55 |
| Dense city across the map | 1 | 1 | 1 | 1 |

Increase the budget for large dense layouts. Density means occupancy of eligible parcels, not buildings per square kilometre. Small maps can fit fewer locations/circuits than requested; circuit shortfalls produce a warning. Wide sidewalks and large setbacks can eliminate undersized parcels.

**Scale.** Radius 6 is a district-sized map (about 670 m across); a radius-14 metro is about 1.6 km across. Street-surface cost grows with the square of the radius (roughly 120k faces at radius 6 and 750k for the metro demo), before buildings; keep Layout Preview on while tuning large maps.

## Growth and driving circuits

1. Place the center and primary district locations.
2. Route arterial links, favouring existing corridors.
3. Extend highway corridors to opposite map boundaries (At Grade). A raised
   highway's line is kept clear of streets instead; they cross it.
4. Connect secondary destinations; lay out the raised highway's
   interchanges.
5. Add highway entry → district streets → highway exit → return circuits.
6. Grow local streets, reserve circulation space and populate blocks.

Circuits are closed simple paths: no repeated intermediate node or retraced edge. Each includes highway and non-highway roads, spans at least six block edges, and has a distinct edge set. On a raised highway a circuit leaves at one interchange and comes back on at the next (or the same one); its `freeway` lists the two, and its nodes end with the highway's leg along its line. Circuits can share sections. The default is three, even with Local Road Density zero. Loop nodes, lengths and tiers are serialized in the plan. These are topology guarantees, not vehicle-physics certification.

Edge topology is grouped into continuous same-tier **routes**, preferring a straight continuation at each junction. Every interior corner of a route becomes a circular fillet (tangent-capped at 45% of each adjacent block edge), so a circuit turns through an arc rather than a square corner. Junctions are not hand-built: they are the union of the curved corridors, which gives each intersection its own shape from the incident widths and angles. Route centrelines are serialized under `paths`, separate from the lattice `roads` used for topology and parcels.

The target is a network of connected driving circuits that change road type and district along the way.

## Small town

**Preset: Small Town** makes a rural town instead of a city. Choosing it sets
radius 5 (about 560 m across), 5 primary and 6 secondary locations, core
density 0.95, outskirts density 0.45, local roads 0.7, one driving circuit and
a 250-building budget. All of them stay editable, and choosing **City** puts
the city's values back. Scripts work the same way: sizes passed to the
operator override the preset's.

- **Districts.** An old-town main street at the centre, whose district
  reaches less far than the others, with residential and suburban districts
  round it and an industrial edge. There is no downtown and no brutalist
  district.
- **Heights.** Old town and residential 1–3 floors, suburban 1–2, industrial
  sheds one storey. With a single **Architecture** style, downtown is 2–4
  floors and brutalist 2–3.
- **Sites.** Gas stations, fast food, auto repair, a motel, a school, police
  and fire stations, parks, a parking lot, strip malls, a palace or twin
  cinema on the main street, and a drive-in where one fits. Schools and cinemas take a
  single block. A town has no mall, shopping plaza, hospital, parking garage,
  transit station or hotel, so the retail is not pulled round a mall.
- **Streets.** The suburbs get cul-de-sacs, as in a city.

Over twelve seeds a town has 140–180 buildings and 11–15 sites, and 10 of the
12 got a drive-in. The plan's settings and the metadata's `city` record the
`preset`.

## City shape

With **City Shape: Square** the streets fill the whole map, and the city
thins out toward its edges only through the density settings. **Organic**
gives the city a seeded, irregular edge, and nothing but the highways
crosses it:

- **The edge.** Its reach along each bearing is a base of 0.74 of the map's
  half-width, plus a few seeded waves (lobes and notches), two to four
  fingers where the town has grown out along a road, and a stretch along the
  highway. Value noise frays it block by block. **Irregularity** scales all
  of these; at 0 the city is round. The edge never comes nearer than 0.3 of
  the half-width, nor passes the map.
- **Inside it.** Districts are seeded inside the edge, local streets grow
  only within it, and routes between districts stay inside (a link leaves
  only when there is no way round; driving circuits never do). Density fades
  from the core to the edge rather than to the map's border, and nothing is
  built past it. Buildings in edge blocks may stand a little past the line.
- **Highways** still run from the map's sides through the centre and out
  into the wasteland. A raised highway's interchanges stand inside the
  edge.

An organic city covers about half the map, and on average has 57–71% of the
buildings a square city of the same radius has (fewer at small radii). Raise
the radius by about 1.4× for a city of similar size. Shapes read best from
radius 8 up; at radius 6 the 12-block lattice leaves little room for lobes.
**Core Radius Fraction** is measured to the edge on each bearing. The plan's
settings and the metadata's `city` record the `shape`.

## Terrain

With **Terrain: Rolling Hills** the city stands on gentle seeded hills.

- **Hills.** Every lattice node (street corner) gets a height from smooth
  noise, up to **Relief** metres from the lowest to the highest. The hills
  fade to level over the outermost two blocks, so the wasteland and the
  highways leaving the city stay level with the map's edge.
- **Grades.** The node heights are then graded until no street is steeper
  than its tier allows: highways 4%, arterials 5%, collectors 6%, local
  streets 8%. Open ground without a street is held to 12%. A site's block
  is level, with all its corners within 0.25 m.
- **One surface.** Between the nodes the road-level surface is a smoothstep
  blend of each block's four corners. Along a street that is the street's own
  profile, flat at both junctions, and steepest mid-block at 1.5 times the
  straight grade (the limits above already allow for it). Carriageways,
  footways, curbs, lane paint and the ground all ride on it.
- **Level pads.**
  - Every building and site stands on a level pad at the height of the road
    in front of its middle, so its front door is at street level.
  - The ground is graded to the foundation: it stays 0.1 m under the pad
    and level with it for 1.5 m all round, then climbs back to the natural
    ground no steeper than 0.6 (a cut) or falls to it no steeper than 0.4
    (a fill), so a building stands in its ground rather than on a plinth.
    Between two buildings at different levels the nearer one's grading wins.
  - Near a building the ground also meets the footways at those slopes, so
    its front yard runs from the footway to the door. A building's paved
    approach slopes from the footway to its pad.
  - A house (not a downtown tower) whose foundation stands further off a
    footway beside it than its graded ground can make up is not built, with
    the rest of its row: it would stand along a retaining wall.
- **Retaining curbs.** On terrain the curbs reach 2.5 m down. Where the
  ground lies below its street away from the buildings, the curb shows as a
  concrete wall holding up the footway.
- **How high.** The map's level edge and the highway's 4% through the centre
  hold small maps lower than the setting. At the default 30 m, typical hills
  are about 12 m on a radius-6 map, 18 m at radius 8 and 24 m at radius 12.

The plan records every node's height, and each lot, site and stop's
`level`. The metadata's positions carry the heights, and the exporter can
write the graded ground as a heightmap (see [Unity export](#unity-export)).

### Terraced

**Terrain: Terraced** puts the same hills under raised terraces of whole
blocks, walled on some sides and falling naturally to the hills on others:

- **The plateau** rises **Plateau Height** metres (default 9), over about
  15% of the city's blocks (6 to 40).
- **Podiums** rise 4.2 m (one storey), over three to six blocks each.
- **Where.** Terraces stand only in the downtown and residential districts,
  at the city's edge, preferring the built-up blocks there.
- **Built up.** A terrace's top is a full district: every street across it
  is laid and every block is built on.
- **Natural sides.** Each terrace meets the land round the city on two or
  three of its sides, chosen at random among those facing out of the city,
  so it sits where the city's edge turns a corner (a podium with no such
  spot left is not built).
  A terrace is a bench on the lower flank of a hill there: one block of
  open hillside (no buildings) leads from the terrace's edge up into the
  hill, which climbs on past the terrace's top (to 1.6 times its rise,
  three blocks out) and then falls away over about five more. Where two natural sides meet at a
  corner, a faceted (octagonal) slope joins them. The other sides are
  retaining walls; they fade into the hill where it wraps round a corner.
- **Wild land.** A terraced city stands in hilly wild land rather than on a
  flat plain: the city's hills (and valleys) carry on for about 1.1 km past
  the map's edge, as flat facets two triangles a block, then level off to
  the flat far wasteland. Each highway leaves along a level valley floor
  about a block either side of it.
- **Low-poly hills.** Under a terraced city the hills are flat facets too:
  each block is two triangles through its corners' heights.
- **Benches.** The hills under a terrace, and out to the junctions round
  it, are graded nearly level, so it stands its full height all round. A
  terrace's edge follows block edges, so every block is on one level.
- **Edge streets on top.** The streets round a terrace's edge run along its
  top, with the wall beyond their outer footway, so the buildings at the
  edge face a street, not a drop. The blocks below never face those
  streets.
- **Ramps.** Two ramps climb to the plateau; every street onto a podium is
  one. A ramp is a street straight out from the terrace (or turning at most
  twice). It turns on a wide curve (about 25 m radius) in 30° chords, and
  climbs at a steady grade of no more than 10% along its route, easing flat
  where it meets the streets at either end. A ramp is one road class all
  the way. Its top always meets a street on the terrace: where none would,
  a street is laid across the top, or (none there) the ramp goes. A 9 m plateau's ramps run three blocks; the side streets
  along them are closed, and no building faces them. Where the lattice has
  no street, the ramp is a new one. Ramps keep raised footways (with curbs)
  on both sides all the way up.
- **Viaducts.** Where a ramp stands more than 4.5 m clear of the ground on
  both sides for 20 m or more, it runs on a viaduct instead of an
  embankment, with the ground running on under it:
  - a 1.2 m deck with parapets;
  - piers about 18 m apart, each a column under a cap beam;
  - a flat abutment at each end, kept just under the road so the deck can
    be driven onto.
- **Stairs.** Any other street up a terrace's face is a stair (none runs
  down a natural side, which stays open hillside): 6 m wide, from the
  upper street's footway to the lower's, in equal steps of at most 0.17 m,
  cut into the terrace between walls.
- **Retaining walls.**
  - **Where they stand:** wherever the ground meets a footway or a stair at
    another height, and along a terrace's edge where no street runs.
  - **Gap at the foot:** a wall holding ground up above a street stands
    2.5 m back from the footway, behind a verge at the footway's level.
    Ground less than about 1 m above the footway slopes up across the verge
    instead.
  - **Clear of buildings:** buildings below a wall keep 3.5 m from its foot;
    buildings on top keep 6 m from a wall standing on the block line (where
    no street runs along the edge).
  - **Parapets:** walls dropping more than 1.5 m carry a 1 m parapet on
    their upper side.
  - **No pockets:** dead-end streets at a terrace's foot are taken away, so
    their turning ends do not cut into it.
- **Transit stops** never stand on a ramp or where their street climbs more
  than 4% (on Rolling Hills too).
- **Network.** Terraces are laid out on the main streets, before the
  driving circuits and the local streets. Circuits keep to the streets at a
  terrace's foot, and every street stays reachable.
- **Exact seams.** Near the streets the ground is cut at the footways' edge
  on the street mesh's own sample grid, so the ground, the walls and the
  footways share their edges. A terrace's edge lies on that grid, within
  0.75 m of the block line.

`City_Retaining_Walls`, `City_Stairs` and `City_Viaducts` are separate
objects (`surface_role` `retaining_walls`, `stairs` and `viaducts`). The
metadata lists `terraces`, `ramps` and `stairs` (see below), and the
heightmap holds the stairs' pitch.

## Districts

With **Mixed Districts**, the centre and the closest primary form the downtown core; the outermost primary anchors the industrial edge and the primary farthest from it anchors the suburbs on the opposite side; the remaining primaries cycle old town, residential and brutalist. Every lot inherits the style of its nearest centre/primary, so districts form contiguous areas rather than a per-building mix. Choosing a single **Architecture** style overrides the assignment and therefore also the district-driven street network.

Each district changes all of the following, not just the material colour:

| District | Parcels per block | Footprint | Density | Extra setback | Local streets | Corner radius | Damage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Downtown | Built out (below) | 100% to the building line | ×1.25 | 0.5 m | ×1.2 | ×0.5 | ×1.0 |
| Old town | 2×2 | 80–100% | ×1.0 | 0 m | ×1.0 | ×1.0 | ×1.0 |
| Residential | 2×2 | 80–100% | ×1.0 | 0 m | ×1.0 | ×1.0 | ×0.9 |
| Brutalist | 2×2 | 85–100% | ×0.95 | 0.5 m | ×0.85 | ×0.8 | ×0.8 |
| Industrial | 1 | 75–95% | ×0.8 | 2 m | ×0.6 | ×1.3 | ×1.2 |
| Suburban | Rows along its streets | 85–100% of a 10 m plot | ×1.6, whole blocks | 1 m | ×0.5 | ×1.4 | ×0.3 |

"Footprint" is the fraction of the parcel the shell may occupy; the remainder becomes the yard, plaza or hardstanding. Industrial gets one wide shed per block. Suburbs are built in tracts: a block is built out or left empty (the density times 1.6 is the chance it is built), and a built block is lined with houses along each of its streets, on plots about 10 m wide with 3 m between houses and up to 11 m deep. The rows along the side streets fit between the end rows, and about one plot in ten stays empty. Local street growth multiplies the road-density probability, so downtown is a tighter grid while the industrial and suburban edges have fewer, longer blocks. Corner radii scale the per-tier fillet, which makes suburban bends wider and downtown corners tighter. Damage scales the city setting, so the suburbs stay mostly intact.

### District superblocks

Outside downtown, blocks of one old town, residential, brutalist or
industrial district join into superblocks, so the districts do not read as
a regular grid. Windows of 2 x 2, 2 x 1 and 1 x 2 blocks are taken in seeded
order; each becomes a superblock with the **District Superblocks** chance
(default 0.5) times the district's factor (old town 1.0, residential 0.9,
brutalist 1.1, industrial 1.0; industrial joins at most 2 x 1). A window
closes every local street inside it, or none if the road network would come
apart; windows never overlap, cross the raised highway's line or come near a
terrace. Blocks already joined because no street ran between them are laid
out the same way. Each district lays its superblocks out in its own manner:

- **Old town and residential: perimeter blocks.** Plots line the outside of
  the joined blocks, each facing the street it stands on, in uneven widths;
  on a 2 x 2 the inner plots are a courtyard.
- **Brutalist: estates.** Slab blocks 12-16 m deep stand along each long
  side, facing its street, with open ground between them (one slab row down
  the middle of a 2 x 1). Rows longer than 64 m (and some over 40 m) split
  into slabs with an 8-12 m gap, and slabs stop short of the ends at random.
  On a 2 x 2 a point tower 16-20 m square stands in the open ground between
  the rows, facing a street at one end of it. (In a terraced city, where a
  pad takes the level of the street it faces, brutalist superblocks are
  perimeter blocks instead.)
- **Industrial: compounds.** One big shed on the joined blocks.

Lots of a superblock have ids with `_sb_<x>_<y>_<wx><wy>_` in them.

**Yards.** The open ground inside a superblock is laid out too (`yards` in
the plan, `sites.compose_yard`), as a level pad at the ground's height in its
middle (on a plinth on hills):

- **Courtyard** (a 2 x 2 perimeter block's inner plots): lawn, a ring path,
  paths in to a garden plaza with benches round a tree, or to a playground,
  and trees round them.
- **Grounds** (between an estate's slab rows, or behind a single row): lawn,
  a main path along them, cross paths to the slabs either side, a ball court
  or a playground, lamps, benches and trees. A point tower and its way out
  to the street stay bare (`keep_out`).

Trees, benches, lamps and play equipment are game markers, as on the sites;
each yard and its markers are listed in the metadata (`yards`).

Ordinary blocks (outside superblocks) also cut their 2 x 2 plots at uneven
widths (0.7-1.3 of the average), so no two blocks repeat the same grid.

### Dense downtown

Downtown blocks are built out to a building line 0.5 m behind the footway and
filled with towers that share party walls:

- **Superblocks.** A share of the local streets between downtown blocks
  (**Downtown Superblocks**, default 0.35) is closed. A street closes only if
  the road network stays connected, only between downtown blocks, and only
  while the joined blocks fit in 2 x 2. Blocks joined across a closed or
  streetless edge are laid out as one 2 x 1 or 2 x 2 superblock, like the
  school and hospital sites.
- **Rows.** Each block or superblock faces a long side, then its best
  street. Plots are at most 40 m deep. With a street behind as well and
  enough depth, it holds two rows back to back, or either side of a 6 m
  service alley (30% of the time), or round a courtyard when deeper than two
  plots. A block on one street keeps a yard behind its row.
- **Frontages.** Each row is cut into frontages 12–48 m wide (18–30 m
  typical). Narrow plots stay lower: floors are capped at 0.9 x the plot's
  shorter side plus 4.
- **Party walls.** Sides that touch a neighbour are party walls, listed per
  lot as `party_walls`. They are blank (no windows, doors, damage holes or
  projecting cornices and pilasters), and debris stays on the building's own
  side. A tower above its podium either rises flush with the party wall or
  sets back from it, leaving a light gap. Towers with neighbours never stand
  on pilotis.
- **Budget.** The buildings of one block are kept or dropped together by the
  building budget.

The default city (radius 6) gets about 50 downtown towers, and a radius-8 city
about 165.

## Building conditions

### How these buildings fail

A neglected tower fails from the envelope inward and from the top down. Roof
membranes, parapets and window seals go first; water and freeze–thaw rot the top
slabs until one drops, its debris load takes the next, and rubble accumulates
inside the facade. Corners and facade bays fail as vertical slices (two free
edges, wind and water), and a lost slice takes its support above with it, so
failures run out through the roof rather than leaving floating holes. The
perimeter usually outlives the floor plates, and the ground floor is the last
part to go, acting as the plinth that holds the pile.

The broken top is a ragged parapet at most **one storey above the break line**: the floors below keep their windows, and deeper damage comes from the collapse archetypes. This avoids tall blank fins that do not read as floors. Windows the break passes through are notched rather than filled, so the window grid runs up to the broken top.

The condition set follows those stages:

- **Weathered** — envelope and top slabs degraded; floors keep their windows up to the break, with a ragged parapet at most one storey above it. Towers of ten floors or more often also lose a piece (a sawtooth, blowout or corner collapse).
- **Semi-collapsed** — a collapse through the top: a corner, stepped storeys, a sheared or cleaved side, roofline bites, a gutted middle or blown-out storeys.
- **Rubble-filled** — top floors pancaked; the interior is a solid fill behind the facade, opened by a ground-floor bay and upper cut.
- **Partial-filled** — only the lower floors pancaked; upper floors are open.
- **Lower floors only** — the upper structure is gone, leaving one to three enterable storeys.
- **Shell** — roof gone, floor slabs exposed, the facade standing with a collapse cut.
- **Wall ring** — only a low perimeter stands, with a rubble mound inside.
- **Collapsed** — nothing but a mound.

Every lot receives a condition from its district weights. The condition sets a
minimum damage and the geometry treatment:

| Condition | Treatment |
| --- | --- |
| Intact | Clean shell; a fitted interior when the lot is in the interior budget |
| Weathered | Fine irregular collapsed top (median-smoothed, slope-limited, no needles); interiors only below the damage line |
| Semi-collapsed | One of seven collapse archetypes by seed (corner, stepped, shear, cleave, sawtooth, gutted, blowout; see ARCHITECTURE.md). Facades break in diagonals, steps or blast holes, slabs step back along broken edges, debris where the building came down |
| Rubble-filled | Interior packed solid up to the break; a jagged ground-floor breach and a crater expose the fill; storeys above the fill are gutted |
| Partial-filled | Lower floors packed with rubble, upper floors gutted; jagged breach and crater |
| Lower floors only | Full damage so the cut lands in the first few storeys; enterable |
| Shell | No roof; floor slabs exposed; a collapse cut with debris; gutted |
| Wall ring | Low perimeter walls (2–4 storeys), no roof or upper slabs, rubble mound inside |
| Collapsed | No shell; a low faceted rubble mound on the pad |

`Interior Ratio` (default 0.25) is the fraction of enterable conditions (intact,
weathered, semi-collapsed, lower floors) that get a full interior layout. The
flag is stored per lot in the plan, so a regenerated city is deterministic.
Rubble-filled, partial-filled, shell, wall-ring and collapsed lots never get
interiors; the filled states are solid or half-solid by design.

A building without a fitted interior still has its structure: its
program's stair to every storey (with the opening in each floor above) and
either its partitions (flats, house rooms, offices off a corridor) or only
its bearing walls (the stair and lift cores, the corridor spine and the walls
between flats). Gutted buildings have rubble on the floors: low ridges where
the partitions came down, heaps against the walls and pieces strewn over each
room, clear of stairs, doorways, corridors and the space inside street doors.
Which one is seeded per lot by condition:

| Condition | Partitions | Gutted |
| --- | --- | --- |
| Intact | 70% | 30% |
| Weathered | 50% | 50% |
| Semi-collapsed, lower floors only | 35% | 65% |
| Shell; the storeys above a rubble fill | | all |
| Wall ring, collapsed | (no floors) | |

Storeys a rubble fill buries get no stairs or walls. Offices, towers and sheds
show their frame either way: rows of columns down the middle of open floors
deeper than 6 m, about 7.5 m apart. The metadata lists each building's
`structure` (`FITTED`, `PARTITIONS`, `BEARING` or `NONE`).

Condition weights per district (percent; `CONDITION_WEIGHTS` in `city_plan.py`):

| District | Intact | Weathered | Semi | Filled | Partial | Lower | Shell | Ring | Collapsed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Downtown | 8 | 20 | 28 | 10 | 10 | 6 | 12 | 3 | 3 |
| Old town | 36 | 28 | 10 | 8 | 8 | 4 | 3 | 2 | 1 |
| Residential | 42 | 28 | 8 | 7 | 7 | 4 | 2 | 1 | 1 |
| Brutalist | 28 | 28 | 14 | 9 | 8 | 6 | 5 | 1 | 1 |
| Industrial | 32 | 24 | 8 | 8 | 8 | 4 | 10 | 4 | 2 |
| Suburban | 58 | 24 | 5 | 4 | 4 | 2 | 1 | 1 | 1 |

## Street patterns

- **Cul-de-sacs.** In the suburbs, a lattice node that no street reaches,
  with suburban blocks on all four sides, may get a short local street from
  a neighbouring road node. Its end is a turning circle with a 10 m
  carriageway radius, ringed by the footway. Only houses stand round it:
  sites keep out of those four blocks. The houses either side face the new
  street, and a ring of up to seven houses faces the circle across a 4 m
  front yard, each with a path to the footway. Other lots keep clear of the
  circle. Each one is listed in the plan's `culdesacs` and, in the metadata,
  as a junction with `cul_de_sac` set.
- **Plazas and strip malls repeat round their district centres.** Parks in
  old town and downtown are laid out as plazas and are drawn toward those
  districts' centres; strip malls are drawn toward suburban and industrial
  centres, and there are a few more of them.

## Raised highway

With **Highway: Raised** (the default) the highway crosses the city on a
viaduct along the lattice line through the centre, straight from one side
to the other: no turns. Every street meeting that line passes under it
(one that would stop under the deck goes on through, or ends a block
short).

- **Deck.** A 25 m deck (two 4.65 m lanes each way, a median barrier and
  2.5 m shoulders) with parapets, on hammerhead piers about every 30 m that
  keep clear of the streets under it. Its top stays at least 6.5 m above
  the ground and every street under it (about 5 m of headroom), climbs no
  more than 3%, and rounds its crests and sags over about 100 m. Out in
  the wasteland beyond the map it comes down to grade (an embankment
  between walls where it is too low to stand open) and the outer highway
  carries on from there.
- **Interchanges.** Diamonds at main street crossings, as many as fit
  (one on a radius-6 map; ten blocks apart, spread evenly along the city;
  on hills where the ramps climb least). Traffic keeps right: eastbound on
  the south side, which leaves before the cross street and joins after it,
  and westbound the other way round. Each ramp runs alongside the deck: at
  grade from the cross street for about 10 m past its footway (where the
  street's footways end and its road carries straight on into the ramp),
  then climbing at 6% (eased at both ends; up to 10%, as a terrace's ramps,
  on hills) to the deck's level, where its lane narrows into the deck over
  40 m. Ramps stand on single columns where high and on fill where low,
  with a parapet along their outer edge.
- **Streets near it.** No street crosses under a ramp's low end: the two
  crossings either side of an interchange (three on hills) are closed, and
  the network is joined up again round them. No street runs along the
  line, no cul-de-sac ends under it, terraces keep a block off it (and no
  stair or street comes down from one to it), and no superblock or site
  spans it. Buildings and site pads keep 3.5 m clear of every deck, and
  beside a ramp as far as from a street.
- **Grading.** On hills the ground along the line is graded as for a
  highway at grade (4%), so the deck follows the land. Under every deck the
  ground stays 0.3 m below the road (beside a ramp in a cutting it climbs
  back at 0.6), and no retaining wall stands up through a deck.

The decks are one object, `City_Freeway` (`surface_role` `freeway`;
asphalt on top, concrete elsewhere); its lane paint is part of
`City_LanePaint`. The plan's `freeway` holds the interchanges, the closed
crossings, the deck profile (`mainline`: x and road level every 8 m), the
`touchdown` ends and each ramp (kind, side, foot, its run at grade and its
centreline points). **Highway: At Grade** gives the earlier layout, plan
for plan.

## Highways beyond the city

The highway runs from map edge to map edge through the centre (raised: from
where its deck comes down). At each end it continues straight on across the
wasteland for **Highway Reach** metres past the map's edge
(`City_Highway_Outskirts`, a child of `City_Streets`).

- **Join.** The city street mesh carries the highway, footways and all, 40 m
  past the edge, clear of any junction at the end node. The outer road takes
  over there from the street mesh's own cut-line vertices, so there is no
  crack. The footways ramp down onto the shoulders over 2 m.
- **Fade.** The road keeps its carriageway and shoulders until the last 40%.
  There the surface breaks up into patches, from the edges inward, using
  seeded value noise on 4 m rows, and the patches thin out to bare ground
  before the end. Worn lane dashes run on and stop where the surface goes.
- **Ground.** Breaks show the ground material at road level; the edges and the
  far end drop to the curb bottom. The wasteland ground leaves a gap for the
  road, so no two surfaces overlap.

Each end is listed in the plan's `outer_roads` (start node, direction, width,
length, fade). One leaving a raised deck has `deck` set: it starts where the
deck meets the ground, with its shoulders flush and no street mesh to meet.

## Points of interest

Before the lot pass, the plan reserves whole blocks for sites, laid out by
`sites.py`. Big sites take 2 x 1 or 2 x 2 superblocks where no street runs
between the blocks.

- **Quotas.** Each kind has a quota per 100 built-up blocks, with at least one
  per city, and district weights. The enclosed mall goes by map size instead:
  one from radius 6, two from radius 12. A city has one drive-in at most.
  - suburbs favour the mall, gas stations, fast food, strip malls and the
    shopping plaza;
  - industrial districts favour auto repair, and with the suburbs motels and
    the drive-in;
  - old town and downtown favour hotels and cinemas (grand hotels there,
    budget hotels in the suburbs; cinemas below);
  - downtown favours garages and the transit station;
  - brutalist districts favour the hospital;
  - residential districts favour schools and parks.

  Blocks the lot pass would leave sparse are preferred. Sites of a kind keep
  a minimum spacing.
- **Retail cluster.** The mall is placed first. The shopping plaza (within
  5 blocks), strip malls (4), cinemas (4) and fast food (3) are drawn toward
  it, so they gather round the mall at the suburban edge.
- **Fronts and pads.** A site faces its best allowed road; gas stations, fast
  food, malls, the hospital and the transit station need an arterial or
  collector. The pad keeps a 1 m verge to the footway, is pushed back where a
  route fillet cuts the corner, and gets a paved approach in front.
- **Conditions.** Sites take a condition from their district like any lot.
  Props fixed to a building go with it.
- **Transit stops.** Shelters, or a pole and bench, stand mid-block on
  arterial and collector footways, clear of lot and site fronts.

The radius-6 default city gets 13–15 sites over about 20 blocks, which costs
it about a fifth of its lots. A radius-8 city gets about 30 sites, every kind
at least once.

| Site | Layouts | Pad (min) |
| --- | --- | --- |
| Gas station | Back, Side (car wash) | 24 x 22 m |
| Fast food | Mansard, Box, Diner | 26 x 24 m |
| School | Bar, Wing (courtyard on shallow pads) | 40 x 32 m |
| Hospital | Tower, Slab | 44 x 32 m |
| Police station | Civic, Modern | 28 x 26 m |
| Fire station | Classic, Modern | 28 x 26 m |
| Transit station | Terminal, Hub | 28 x 24 m |
| Park | Green, Playground, Plaza, Sports | 16 x 16 m |
| Parking lot | Rows, Angled | 20 x 20 m |
| Parking garage | Decks, Tall | 30 x 26 m |
| Strip mall | Row, L | 30 x 26 m |
| Shopping plaza | Pair, Anchor | 80 x 70 m |
| Auto repair | Bays (bay doors on the street), Yard (bays on a side forecourt, fenced yard) | 30 x 28 m |
| Enclosed mall | Dumbbell (two anchors), Junior (a big and a junior anchor) | 90 x 80 m |
| Hotel | Grand (7 floors, corniced), Budget (4 floors, plainer) | 30 x 28 m |
| Motel | Strip (one row of rooms), Court (a side wing and a pool) | 36 x 28 m |
| Cinema | Palace (one tall hall, marquee and blade sign), Twin (two screens behind a shared lobby, marquee and parapet sign; needs 34 m of width), Multiplex (a row of screens off a corridor; needs 40 m, and stands behind its parking on a pad 61 m deep). All fill their pad, and every auditorium has stadium seating | 32 x 30 m |
| Drive-in cinema | Single, Twin (two screens) | 80 x 40 m |

**Cinemas** pick the layout that suits their district: palace or twin in old
town, palace or multiplex downtown, twin or palace in residential districts,
twin or multiplex in brutalist ones, multiplex in the suburbs and industrial
districts. A layout too wide for its pad steps down (multiplex to twin to
palace). **Stadium seating:** each auditorium's screen is on the wall it is
entered by. Its floor is flat for 4 m in front of the screen, where the doors
and the side exits are, then rises in 1 m tiers of 0.3 m (under the player's
0.4 m step offset, so the aisles are walked straight up) to the back wall,
keeping 2.6 m of headroom over the top tier. The tiers are modelled; the
seats are `seat` markers, 0.6 m apart in rows on every tier with 1 m side
aisles and a centre aisle in wide rooms. A palace seats about 500–1,500; a
terraced auditorium lists no wall runs.

Each site is a `<id>_Grounds` mesh (pad, paint, lawns, walks, canopies,
pumps, signs, benches, play equipment, using 13 `Site_*` material slots).
Trees, chain-link fences and flagpoles are game assets, so the grounds only
mark where they go:
- concrete post footings (0.3 m, at most 2.5 m apart) along each fence line;
- a 0.7 m plinth for each flagpole;
- planters and planted parking islands for trees.

A site's buildings are shells parented to the grounds, with the grounds origin
at the pad centre. Transit stops of one kind share a mesh.

## Street-level geometry

- Carriageways: 20 m highway, 12 m arterial, 8 m collector, 6 m local. Corner fillets default to 0.6 × the tier radius (15.6 m highway, 10.8 m arterial, 7.2 m collector, 4.8 m local), scaled again by district.
- The surface is a distance field: `A(p)` is the nearest centreline distance minus that road's half width. Carriageway is `A ≤ 0`, footway `0 < A ≤ sidewalk width`. Both are extracted per 1.5 m cell by clipping two triangles against those iso-levels, so neighbouring cells share every crossing vertex.
- There is no boolean union: junctions are the natural union of the corridors, faces never overlap, and the only boundary edges are the open bottoms of the outer curb skirt. Curved boundaries deviate by at most ~0.5 m from the analytic envelope, at concave junction corners; road edges, fillets and curbs otherwise follow the centreline to centimetre accuracy.
- Footway height ramps smoothly at intersections; the feet are flush where the two roads meet. The maximum 0.25 m curb gives an intended rise/run of 0.125, about 7.1°.
- Frontages use adjacent road widths instead of one city-wide highway setback. Doors face non-highway streets; shells occupy disjoint parcels. Parcel margins exceed the maximum fillet intrusion, so buildings never intersect a curved corridor or its footway.
- Each lot has a foundation and paved approach at footway elevation. In Detailed Shells mode, the foundation under the ground storey drops to the underside of the building's ground slab, so it never shares the floor plane (before v0.11 every ground floor z-fought with it).
- Lane paint follows each route's tangent, so dashes curve through bends and stop short of junctions. Terrain is cut only under sample cells that the footway fully covers, which keeps the unpaved surface continuous. Beyond the city the same ground continues as a flat wasteland frame out to the **Wasteland Extent** (default 12000 m), so the horizon reads as open ground while the game keeps the player inside invisible walls. New surfaces have metre-scaled planar UVs and material slots.
- Exterior rubble remains disabled in city recipes so it cannot obstruct circulation.

The referenced Ares capsule is 2 m high, radius 0.4 m, with a 0.4 m step offset and 45° slope limit. Its 1.5 m camera-pivot height is used in the street preview. Actual collision/navigation behaviour still needs Unity play tests.

## Game data: city metadata

Each city run stores its metadata with the city collection (compressed, in the
hidden `_metadata_json_zlib` custom property; with interiors it runs to
megabytes, which Blender's text editor handles badly), and **File → Export →
Generated City for Unity** writes it beside the FBX as `<name>.city.json`
(**Write City Metadata**, on by default). The exporter
checks every object the metadata names still exists, and lists any that
don't in `missing_objects`.

**Coordinates.** Metres, Unity world space by default, matching the
GameObjects the FBX import creates. A Blender point (x, y, z) becomes
(−x, z, −y); the exporter writes Y-up axes in centimetres, and Unity's
default import converts to metres and mirrors X. Every entry has `position`,
a unit `forward` vector and `yaw`: the rotation about +Y (degrees) that turns
an asset modelled facing +Z to face `forward`. Use `yaw` rather than the
imported GameObject rotations, which carry the FBX axis correction. With
**Metadata Space** set to Blender, positions are Blender world space and
`yaw` turns a −Y-facing asset about +Z.

The layout suits `JsonUtility`: no dictionaries, nested arrays or nulls.
Point lists are flat `[x, y, z, x, y, z, …]`. The C# data classes are in
`docs/unity/CityMetadata.cs` (checked by compiling them and parsing a real
file). The file is written without indentation; with interiors listed, a
radius-8 city's is about 13 MB.

**Building space.** A building's `rooms`, `lifts` and `railings` are given
relative to the building, which keeps the file small: offsets from its
`position` in the same axes, rotated by its `yaw` about up. In Unity a point
is `position + Quaternion.Euler(0, yaw, 0) * local`; `normal` vectors rotate
the same way.

| Field | Contents |
| --- | --- |
| `city` | Preset, shape, terrain, relief, plateau height and podiums, seed, origin, extent, block size, wasteland, curb height, sidewalk width, whether small props were modelled, interiors listed and water modelled |
| `districts` | District seeds: id, role, style, position |
| `roads` | Every route: tier, width, lattice nodes, centreline points at carriageway level (footways run along both sides) |
| `junctions` | Lattice nodes with roads: position, radius (widest half-width plus footway, or the turning circle plus footway), number of roads, `cul_de_sac` |
| `driving_loops`, `outer_roads` | The driving circuits; the highways beyond the city edge (start, forward, length, fade) |
| `freeway` | A raised highway (null at grade): width, interchanges (cross-street node and position), the deck's centreline at road level (`mainline`, every 8 m) and its two `touchdown` ends, each ramp (kind `on` or `off`, interchange, side, width, climb and taper lengths, centreline from the cross street) and the pier feet |
| `terraces`, `ramps`, `stairs` | Terraced terrain: each terrace's kind (`plateau`, `podium`), rise, lattice blocks on top and `slope_blocks` (its natural sides); each ramp's terrace, lattice nodes from the top down, their positions and `viaducts` (deck ends at road level and pier feet); each stair's terrace, top and foot (the middle of the top and bottom steps' outer edges, at the footways), width, step count and riser. Empty on other terrain |
| `buildings` | One per lot: object name, style, district, condition, damage, floors, height, interiors, `structure` (`FITTED`, `PARTITIONS`, `BEARING` or `NONE`), enterable floors, party walls, block group, footprint (position at the base, forward = front, width, depth), and `entrances` (each street door's position, outward forward and width) |
| `sites` | Points of interest: grounds object, kind, variant, condition, pad; their buildings with the same fields as above |
| `yards` | Courtyards and estate grounds: grounds object, kind (`COURTYARD` or `GROUNDS`), variant, district, seed, pad centre and size; their trees, benches, lamps and play equipment are markers whose `site` is the yard's id |
| `rooms` (per building) | Rooms to furnish: name, kind (bedroom, living, kitchen, bath, hall, corridor, lobby, office, open, shop, storage, bar, plant, stair, landing), floor, flat or shop unit, open-plan group, centre of the clear floor, clear width, depth and height, the share of floor still standing and still roofed, `doors` (position, normal into the room, width, height, the room on the other side or `street`), `windows` (sill centre, outward normal, width, sill and head above the floor, broken) and `wall_runs` (blank wall at least 2 m high: start, end, normal into the room) |
| `lifts` (per building) | One per shaft: centre at its lowest stop, clear size, height, the floors it still serves, a door per floor (position, normal out of the shaft, size) and the `car` at the lowest of them |
| `railings` (per building) | Base lines on the walking surface (flat points) with a rail height: `stair` handrails along the well side of each switchback, `guard` rails at the stair opening of the top floor, `ramp` rails along parking ramps |
| `transit_stops` | Shelters and stops: object, variant, road edge |
| `markers` | Placements for game assets: every small prop (`bench`, `lamp`, `bollard`, `gas_pump`, `dumpster`, `table`, `booth`, `play_structure`, `swings`, `goal`, `trash_bin`, `air_pump`, `hydrant`, `cart_corral`, `tyre_stack`, `speaker_post`; `modelled` says whether the city mesh has it), `tree` spots, `flagpole` plinths, `fence` lines (post line points and a suggested height) and `parking_stall`s (centre and nose-in direction, for wrecked cars), fixtures inside buildings (`reception_desk`, `shop_counter`, `service_counter`, `bar_counter`, facing the customers, and cinema `seat`s on their tier, facing the screen; with `building` and `floor`; never modelled), and `water` surfaces (centre at the surface, `shape`, `size` = width, depth and water depth; modelled only with **Water** on). Each has its site id and, where it applies, `size` (width, depth, height), `height`, `scale` (trees), `umbrella` or `barrier` |
| `counts` | Totals per section and per marker type |

Objects also carry custom properties that the FBX passes to Unity as user
properties, such as `condition`, `party_walls`, `entrances` (object space)
and `addon_version`.

## Unity export

Use **File → Export → Generated City for Unity (.fbx)** and choose the root city collection. This exports only its mesh objects, triangulates them, preserves UV/material assignments, and uses metre scale with Y-up axis conversion. It restores selection and active object. Hidden/excluded city objects and non-unit scene scales are rejected instead of silently omitted/rescaled. Editable source objects are not joined or destructively triangulated.

**Heightmap.** With **Write Heightmap** on (the default), the exporter
also writes `<name>.heightmap.raw` and `<name>.heightmap.json`:

- **What it holds:** the graded ground, with every building and site pad at
  its top and the streets at road level (on terraces, the streets, ramps and
  stairs at their walking surface). It covers the city ground (the map
  plus 20 m) at 513, 1025 (the default) or 2049 samples a side.
- **Format:** the RAW is 16-bit little-endian, row by row from row 0.
- **Layout:** as in the metadata. In Unity space the columns run along +X
  and the rows along +Z.
- **The JSON gives:**
  - the origin of sample (0, 0) at the lowest height;
  - the spacing, size, and lowest and highest heights;
  - for Unity, the Terrain's position and size, ready for **Import Raw**
    (Windows byte order, no flip).
- **When it is written:** the heightmap is computed from the city's plan,
  regenerated from its stored settings. A city made by another version of
  the add-on gets a warning instead.

Output stays as separate meshes for culling and future chunk/LOD work. No texture baking, Unity materials, colliders, NavMesh or static flags are generated; the metadata's markers say where game assets go. `City_LanePaint` is tagged `decoration_no_collision`; exclude it from collision generation. Route guide curves are omitted from FBX.

For scale: a radius-8 city with every building detailed has about 490 buildings and 1,070 mesh objects; its street mesh is about 345k polygons. A radius-14 metro is about 1.85M polygons in 1,700 objects, with ground spanning about 25.6 km.

## Plan data

A JSON text datablock (`<collection>_plan.json`) stores the versioned plan. Coordinates are relative to the collection's stored `origin`; road nodes multiply by `block_size`, while lot positions/dimensions and path points are metres. Schema version 20 adds `yards` (courtyards and estate grounds: `id`, `kind`, `center`, `width`, `depth`, `style`, `district`, `seed`, `keep_out`, `level`). Version 19 adds `district_superblocks` to the settings. Version 18 adds `highway` to the settings (`RAISED` or `GRADE`), `freeway` to the plan (a raised highway's layout and heights; empty at grade), `deck` to an outer road leaving a raised deck and `freeway` (the interchanges it leaves and rejoins at) to a driving circuit on one. Version 17 grades the wild land round a terraced city with it: `terraces` gains `wild` (blocks of it beyond the map's edge) and its `ground` covers them. Version 16 raised every corner of a terrace's blocks (the streets round its edge run along the top) and keeps terraces in the downtown and residential districts at the city's edge. Version 15 gave a ramp one road class and its junctions' heights along its curved route. Version 14 added each terrace's natural sides: `slopes` (`axis`, downhill `sign`, crest lattice `line`, `cells`) and `corners` (a `cell` joining two slopes, with each slope's `line` and `sign` along `x` and `y`). Version 13 added `plateau_height` and `podiums` to the settings and `terraces` to the plan: `regions` (each terrace's `cells`, `step` and `kind`), `ramps` (lattice `nodes` from the top down and each one's `raises` above the hills), `stairs` (`low` and `high` lattice nodes, `width`) and `ground` (the hills' node heights under the terraces; `heights` are then the road level). Version 12 added `terrain` and `relief` to the settings, `heights` (each lattice node's graded height, where it is not zero) to the plan, and `level` (pad or road height) to every lot, site and stop. Version 11 added `shape` and `irregularity` to the settings. Version 10 added `bulb` to each lot: the cul-de-sac node a house round a turning circle faces (empty for the rest). Those houses are turned to face the circle, so a lot's `rotation` is no longer always a quarter turn. Version 9 added `preset` to the settings (`CITY` or `SMALL_TOWN`). Version 8 added `culdesacs` (turning-circle node and radius). Version 7 added `party_walls` and `group` to each lot (downtown towers built against neighbours). Version 6 added `outer_roads`. Version 5 added `pois` (kind, centre, width along the frontage, depth, rotation, frontage edge, blocks, seed, condition, damage, approach) and `shelters` (position, rotation, variant, road edge); a site's layout is chosen by `sites.compose` from its seed. Version 4 added `kind`, `condition`, `interiors` and `damage` to each lot alongside the version-3 `paths`: one entry per continuous same-tier route with its lattice `nodes`, flattened metre-space `points` and `width`. Locations and lots carry their district `style`; the per-style profile table is code (`STYLE_PROFILE`), not part of the file. No legacy-plan importer is included.

## Code and verification

`city_plan.py`: pure settings, district assignment, seeded routing, route grouping and corner fillets, circuits, points of interest, parcels, transit stops. `streets.py`: pure distance-field surface and terrain tessellation. `styles.py`: district building recipes (massing, openings, roofs, conditions). `sites.py`: point-of-interest layouts. `metadata.py`: the game metadata. The building core (`spec`, `layouts`, `damage`, `solids`, `shell`, `rubble`) is described in [ARCHITECTURE.md](ARCHITECTURE.md). `building_assets.py`: shell, rubble, site and transit-stop objects. `city_operators.py`: Blender adapter. `city_export.py`: city-only FBX export.

The project's tests (not yet published here) cover planning, district assignment, condition weights and the interior budget, circuit closure and tier diversity across seeds, route coverage and fillet continuity, parcel clearance against curved corridors, distance-field classification, crack and overlap topology, curb heights, terrain coverage, the style recipes, point-of-interest placement and every site layout, and the metadata. In Blender they cover registration, every operator, mesh validation and rollback, UVs, city-only export, selection restoration, triangulation and world bounds after FBX reimport. They run on Blender 5.1; the declared Blender 4.5 minimum is not tested separately, and Unity import and play-mode tests are pending.

## Next milestones and limits

See [ROADMAP.md](ROADMAP.md) for what is planned.

1. **Parcels and block structure:** parcels are still axis-aligned sub-cells of a square lattice, so block edges and building rows remain rectilinear even though the streets curve. Downtown blocks are now built out with party-walled towers and superblocks, the other districts join blocks into superblocks of their own, and the suburbs set houses well back, but L/U/courtyard footprints, curved frontages and irregular block subdivision are the next step.
2. **Vertical routes and terrain:** rail and subway lines, tunnel entrances and an optional river or dried coastline with a port (see ROADMAP "Later"). The raised highway is the only road bridging others; it still runs straight along the lattice.
3. **Asset variety:** the six archetypes cover massing and roofs, and v0.11 adds the common sites (hospital, schools, stations, malls, parking); a courthouse or city hall, auto repair, an enclosed mall, authored facade kits, rooftop clutter and per-district palettes remain.
4. **Game delivery:** chunk/LOD export, collision proxies, navigation checks, vehicle swept-clearance tests and connected ruin/vegetation dressing.

Limits:

- Street surfaces have open bottoms below ground; they are not watertight solids.
- The 1.5 m surface sampling is a fixed budget decision: a tighter grid would reduce the ~0.5 m concave-corner deviation at the cost of roughly quadratic triangle growth.
- Collapses are ruin silhouettes, not structural simulations.
- Choosing a single architecture style changes the street network, because district road factors no longer vary.
- Generation is synchronous; use Layout Preview and a conservative building budget for large maps.
