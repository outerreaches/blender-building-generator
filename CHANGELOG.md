# Changelog

## v0.21.0: Rolling hills and a heightmap export

- **Terrain: Rolling Hills** in Generate City puts the city on gentle seeded
  hills. **Relief** sets the height from the lowest ground to the highest:
  up to 40 m, default 30.
  - The hills fade to level at the map's edge, so the wasteland and the
    highways leaving the city stay level. On small maps that holds them
    lower: typically about 12 m at radius 6, 18 m at radius 8 and 24 m at
    radius 12.
  - **Flat**, the default, is unchanged.
- **Graded streets.** No street is steeper than its tier allows: highways
  4%, arterials 5%, collectors 6%, local streets 8%. Between junctions a
  street eases out flat at both ends. Carriageways, footways, curbs, lane
  paint and route guides follow the surface. Site blocks are level.
- **Level pads.**
  - Every building and site stands on a level pad at the height of the road
    in front of its middle, so front doors are at street level.
  - Downhill, the foundation (or a site's plinth) reaches down to the ground.
  - Uphill, the ground is cut back from the pad.
  - Paved approaches slope from the footway to the pad.
  - On terrain the curbs reach 2.5 m down, so a footway above a lower lot is
    held up by a concrete curb wall.
- **Heights in the metadata.** Buildings, sites, stops, road points and
  junctions carry their heights, and `city` records `terrain` and `relief`.
- **Heightmap export.** The FBX exporter can also write the graded ground as
  a 16-bit RAW heightmap, at 513, 1025 or 2049 samples a side. A JSON beside
  it gives the layout and, for Unity, the Terrain's position and size.
- Plan schema 12: `terrain` and `relief` settings, node `heights`, and
  `level` on lots, sites and stops.

## v0.20.0: Cinemas with stadium seating; cul-de-sacs among houses only

- **Stadium seating.** Every cinema auditorium has a stepped floor: flat for
  4 m in front of the screen, where its doors and exits are, then 1 m tiers
  of 0.3 m (walked straight up; the player's step offset is 0.4 m) to the
  back wall, with 2.6 m of headroom over the top. Seats are `seat` markers on
  the tiers, facing the screen, with side and centre aisles; damage takes
  pieces of the tiers and their seats with them.
- **Three cinemas, filling their pads.** *Palace* (one tall hall), the new
  *Twin* (two screens behind a shared lobby) and *Multiplex* (a row of
  screens off a corridor, with exits at its ends) now fill their pads;
  a multiplex no longer needs a deep pad (it stands behind its parking only
  on one). Districts pick between two layouts where both suit them. Fixed:
  the planner matched side-wall piers by exact float equality, so
  multiplexes always fell back to one auditorium.
- **Cul-de-sacs only among houses.** A turning circle needs suburban blocks
  on all four sides, and sites keep out of those blocks.
- **One drive-in per city** at most.

## v0.19.0: Organic city shape

- **City Shape: Organic** in Generate City gives the city a seeded,
  irregular edge instead of filling the square map: lobes and notches, two
  to four fingers where it has grown out along a road, a stretch along the
  highway, and a frayed line block by block. **Irregularity** (0 to 1,
  default 0.6) scales it; 0 is round.
- Districts, local streets and the routes between districts stay inside the
  edge, density fades toward it, and nothing is built past it; the highways
  still cross it and run out into the wasteland. Driving circuits leave and
  rejoin the highway inside the city.
- An organic city covers about half the map; raise the radius by about 1.4×
  for a city of similar size. **Square** (the default) is unchanged.
- The plan's settings (schema 11) and the metadata's `city` record the
  `shape`.

## v0.18.1: Built-out suburbs, houses round cul-de-sacs, drive-in fixes

- **Suburbs are built out.** Suburban blocks are built in tracts, whole or
  not at all, and a built block is lined with houses along each of its
  streets: plots about 10 m wide, 3 m between houses, houses filling most of
  the plot. A town's suburbs have about twice as many houses as before.
- **Houses round cul-de-sacs.** Up to seven houses ring each turning circle,
  facing it across a 4 m front yard, each with a 3 m path to the footway.
- **Drive-in cinema.** The concession stand is in a back corner: beside the
  screen in a deep lot (twin screens move over to make room), at the far
  end of the field in a shallow one. The ticket booth faces into the lot and
  its barrier reaches across the way in (it pointed away from the lane).
- Plan schema 10: lots gain `bulb`, and houses round a turning circle have
  rotations other than quarter turns.

## v0.18.0: Small-town preset

- **Preset: Small Town** in Generate City builds a rural town: an old-town
  main street at the centre, residential and suburban districts round it and
  an industrial edge, with no downtown or brutalist district. Buildings stay
  at 1–3 floors (suburban 1–2, industrial sheds one storey).
- A town has gas stations, fast food, auto repair, a motel, a school, police
  and fire stations, parks, a parking lot, strip malls, a palace cinema on
  the main street and, where one fits, a drive-in. It has no mall, shopping
  plaza, hospital, parking garage, transit station or hotel.
- Choosing the preset sets a town's size and densities (radius 5, about
  560 m across, 250-building budget); they stay editable, and **City** puts
  the city's values back. A town has about 90–125 buildings and 11–15 sites.
- The plan's settings (schema 9) and the metadata's `city` record the
  `preset`. City plans are unchanged.

## v0.17.0: Cul-de-sacs, plazas and strip malls

- **Cul-de-sacs.** Suburbs get short dead-end streets into blocks that no
  street reached, each ending in a turning circle (10 m carriageway radius,
  ringed by the footway). The houses either side face the new street; lots
  and site pads keep clear of the circle. The plan lists them in
  `culdesacs` (plan schema 8), and the metadata marks their junctions with
  `cul_de_sac`.
- **Plazas and strip malls repeat round their district centres.** Parks in
  old town and downtown are plazas and gather near those districts' centres;
  strip malls gather near suburban and industrial centres, and there are a
  few more of them.

## v0.16.0: Hotels, motels, cinemas and drive-ins

- **Hotel.** Guest-room floors (entry passage, en-suite bath, bedroom off a
  corridor) over a lobby with a reception desk, a dining room, a kitchen and
  offices; a canopy over the main door, flags, a sign on the parapet and
  parking behind. *Grand* (7 floors, corniced) suits old town and downtown,
  *Budget* (4 floors) the suburbs.
- **Motel.** One-storey rooms behind a covered walk, each with its own door
  onto the parking and a bath at the back; the office at one end and a tall
  sign by the road. *Court* adds a wing down the side and a pool (dry unless
  **Water** is on).
- **Cinema.** *Palace*: a tall single-screen hall on the street with a
  marquee over the doors and a blade sign. *Multiplex*: a box of screens
  behind a glazed lobby, with exits at the back and parking in front. Both
  have a ticket desk and a concession counter; auditoriums are listed as
  rooms of kind `auditorium`.
- **Drive-in cinema.** A big screen at the far end (*Twin*: two), curved rows
  of stalls facing it with speaker posts between the cars, a concession
  stand in the field, a ticket booth at the gate and a fence round the lot.
- In a city, cinemas and hotels pick the layout that suits their district,
  and cinemas join the retail round the mall.
- New small prop: `speaker_post`.

## v0.15.0: Auto repair, enclosed malls, water switch

- **Auto repair.** A new site: a workshop with roll-up bay doors and a
  reception counter beside it, a concrete apron, customer stalls, tyre stacks
  and an air pump. *Bays* puts the bay doors on the street; *Yard* turns them
  to a side forecourt with a fenced yard of cars at the back. Placed mostly
  in industrial districts.
- **Enclosed mall.** A new site on a 2 x 2 superblock: one long building with
  an anchor store at each end (*Dumbbell*: two equal anchors, *Junior*: a big
  and a junior one), a concourse lined with shop units, an entrance hall and
  a food court, all open to each other, with restrooms, stock rooms and
  loading doors. Parking wraps the front, with cart corrals and a tall pylon.
  One per city from radius 6, two from radius 12.
- **Retail gathers round the mall.** The shopping plaza, strip malls and fast
  food are drawn toward it, so the suburban edge reads as one retail district.
- **Water switch** on Generate City and Generate Site, off by default: the
  park fountain's basin is dry, and its water is listed as a `water` marker
  (surface height, size, depth) for the game to fill. On: the water is
  modelled.
- **Fixed: rooms with their own street door had no way into the building.**
  Back rooms of shops, stock rooms and some kitchens could only be entered
  from outside. Such a room now keeps its door into the building; a
  single-room shop unit stays on its own. In a sweep of district buildings
  and site layouts, 109 rooms had no way into the rest of their building;
  none do now.
- **Fixed: overlapping doors.** Designed doors could snap to overlapping bays
  (the hospital's ambulance doors on a small pad); doors now never share a
  bay. Tests check that no facade has overlapping openings.
- New small prop: `tyre_stack`.

## v0.14.0: Interiors for the game

- **Furniture, railings and lifts are game assets.** None of them is
  modelled. The city metadata lists, for every building and site building:
  - **Rooms to furnish:** kind (bedroom, kitchen, office, shop and so on),
    floor, flat or shop unit, clear size and height, doors (with the room on
    the other side), windows (sill and head), and wall runs: blank wall at
    least 2 m high, with no door, window or hole, for furniture to stand
    against. Damaged rooms say how much floor and ceiling is left; rooms with
    almost no floor are left out.
  - **Lifts:** one per shaft, with the floors it still serves, a door per
    floor and the car at its lowest stop.
  - **Railings:** handrails along each stair's well side, a guard rail at the
    stair opening on the top floor a stair reaches, and rails along parking
    ramps.
- **Counters and desks are markers.** Shop, service and bar counters and lobby
  reception desks are no longer modelled; they are listed with the other
  markers, with their building and floor.
- **Building space.** Interiors are given relative to their building, which
  keeps the file small. In Unity a point is
  `position + Quaternion.Euler(0, yaw, 0) * local`. The C# classes in
  `docs/unity/CityMetadata.cs` cover the new fields (schema 2).
- **Interior Metadata** switch on Generate City (on by default).
- **Metadata storage.** The metadata is kept compressed on the city collection
  instead of in a text datablock (Blender writes large text datablocks very
  slowly), and the exported file has no indentation. With interiors, the base
  city's `.city.json` is about 12.8 MB.
- **Same rules as the mesh.** Interiors are worked out with the shell's own
  damage tests, so a room, rail or lift door is listed only where the mesh
  keeps what it stands on. New tests check every fact against the mesh.

## v0.13.1: Walkable stairs, no floating floors, windows through damage

- **Fixed: blocked stairs.** Each step of a stair flight was a solid block
  down to the floor, so the flights of the storey above filled the headroom
  over the flights below. Stacked stairs, as in towers, could not be climbed.
  Flights now have a 0.3 m waist under the treads and the turning landing is
  a 0.25 m slab. A new test walks the player capsule up every stair of 100
  buildings: 90 had a blocked stair before, none do now.
- **Fixed: floating pieces of floor.** Where damage cuts a slab, the
  broken edge could leave small pieces or islands with nothing under them. A
  piece is now dropped when it is smaller than 1.5 m² or touches neither a
  wall nor a stair or shaft enclosure.
- **Windows stay windows near damage.** Windows that the broken top passed
  through, or that touched a blast hole, used to be filled in, which broke up
  the window grid.
  - **Broken tops:** a window the break crosses now loses everything above
    its broken sill. The piers between neighbouring broken windows are
    either gone or broken off at different heights, and the wall slopes down
    into the gap at each end, so the top storey reads as ruined masonry
    rather than battlements.
  - **Blast holes:** a hole now takes in the windows it touches.
  - **Below the damage:** the windows keep their full grid.

## v0.13.0: Small-props switch, city metadata for Unity

- **Small Props switch.** A new switch on Generate City and Generate Site
  covers the props the game will replace with destructible assets: benches,
  gas pumps, lamps, bollards, trash bins, dumpsters, tables, play equipment,
  goals, booths, hydrants, air pumps and cart corrals. With it off they are
  not modelled, but every one is still recorded.
- **City metadata.** Each city records game data. The FBX export writes it
  next to the FBX as `<name>.city.json`. It holds:
  - roads, junctions, driving loops and outer highways;
  - buildings and site buildings, with their street entrances, condition,
    floors and party walls;
  - sites and transit stops;
  - markers: every small prop, tree spot, flagpole, fence line and parking
    stall, where the game places its own assets.

  Coordinates are Unity world space, checked against the FBX the exporter
  writes. Objects are referred to by name, so the Unity side can bind
  entries to the imported meshes. C# data classes for `JsonUtility` are in
  `docs/unity/CityMetadata.cs`.
- **Tree spots** removed in v0.11.1 are back as markers (no mesh).

## v0.12.3: Downtown plot depth, add-on updates take effect

- **Downtown plots stay at most 40 m deep.** A 2 x 1 superblock could be cut
  across its short side into towers 20 m wide and 100 m deep. Downtown
  blocks now face a long side of the pad.
  - **Two streets:** a block with a street behind it holds two rows back to
    back, or with a courtyard between them when it is deeper than two plots.
  - **One street:** a block with a street on one side only keeps a yard
    behind its row.
- **Updating the add-on now updates all of it.** Blender only reloads an
  add-on's main file when it is installed over an enabled copy and switched
  off and on (or after **Reload Scripts**); the other modules kept running
  the old code. This is why rubble fixed in v0.12.1 could still appear after
  an update. The add-on now reloads all its modules.
  - **Version stamp:** each city collection and building records
    `addon_version`, so you can see which version made a file.
  - **Restart:** to be safe, restart Blender after installing a new version.

## v0.12.2: Weathered one-storey roofs, school proportions

- **Fixed: floating roofs on weathered one-storey buildings.** This affected
  industrial sheds, the fire station's engine hall and one-storey houses.
  Weathering cut their walls down flat against the protected ground-floor
  height while the roof stayed up, floating above them. Now the ragged wall
  tops spread over the whole allowed range, so they look weathered rather
  than flat. The roof stays only while every wall still reaches its
  underside; otherwise it has fallen in. Multi-storey buildings already
  behaved this way.
- **Fixed: stretched schools.** Schools on 2-block superblocks had a
  classroom block up to 66 m long and a court and pitch stretched to fill
  the yard. Classroom blocks now stop at 54 m.
  - **Real-size grounds:** courts are full (28 x 15 m) or half (15 x 14 m),
    the play pad is 14 x 10 m, and the pitch keeps real proportions
    (length:width 1.45–1.7, 30–90 m long), centred in its space.
  - **Spare space:** it becomes open playground or a staff car park.
  - **Shallow lots:** on a shallow 2 x 1 lot, the sports ground sits at the
    end of the lot instead of in a thin strip behind the buildings.
- **New tests.** Two tests check these fixes; both fail on the old code.

## v0.12.1: Rubble stays inside towers

- **Fixed: rubble fill on podium towers.** In filled and partly filled
  buildings the rubble fill was sized to the ground-floor footprint all the
  way up. On towers with a wider podium, it stuck out past the set-back
  tower's faces. The fill now follows each tier's walls and changes width
  inside the slab where the tower steps in.
- **Fixed: debris in blast holes.** Debris on the floor of a blown-out
  storey could hang out through the blast hole. It now stays inside that
  storey.
- **Unchanged: street spill.** Ground-level debris spilling onto the street
  from a collapse is deliberate and still there.
- **New test.** Above the ground storey, rubble must stay inside the
  building or rest on a lower roof. The old code failed it.

## v0.12.0: Dense downtown

- **Built out to the street.** Downtown blocks fill out to a building line
  0.5 m behind the footway, instead of one tower standing back in each block.
- **Shared blocks.** Each block holds a row of towers that share party walls,
  or two rows back to back or across a service alley.
- **Superblocks.** Some downtown local streets close (**Downtown
  Superblocks**, default 0.35), so blocks join into 2 x 1 and 2 x 2
  superblocks, like the school and hospital sites. Streets close only while
  the road network stays connected.
- **Party walls.** Party walls are blank. Damage leaves them whole and debris
  stays on its own side; nothing projects into the neighbour. Towers rise
  flush with a party wall or set back from it above their podium.
- **Transit stops.** Stops may stand in front of buildings, clear of their
  entrances.
- **Base demo city (radius 8).** Downtown goes from 65 to about 150 towers; the scene
  has 471 buildings, 30 sites and 27 stops, a 55 MB `.blend` and a 73 MB FBX.
- **Plan schema 7.** Adds `party_walls` and `group` to each lot.

## v0.11.1: Highways out of the city, game-asset props

- **Highways leave the city.** The main highway continues straight out of
  both ends of the city across the wasteland, 3 km by default (**Highway
  Reach** in Generate City; never past the ground).
  - Over its last 40% the surface breaks up from the edges inward into
    thinning patches until only ground is left.
  - Lane dashes wear away with it.
  - It is a separate `City_Highway_Outskirts` mesh joined crack-free to the
    city streets 40 m past the edge; the footways ramp down onto its shoulders.
  - The wasteland ground is cut around it, so nothing overlaps.
  - Plan schema 6 adds `outer_roads`.
- **Game-asset props.** Sites no longer model trees, chain-link fences or
  flagpoles; the game places its own assets:
  - fence lines keep 0.3 m concrete post footings every 2.5 m or less;
  - flagpoles keep a 0.7 m plinth;
  - planters and parking islands stay as tree spots.
- **The base demo city is twice as wide.** It is now radius 8 (about 900 m
  across, was 450 m): 383 buildings, 30 sites and 27 transit stops; the
  `.blend` is 36 MB, the FBX 47 MB.

## v0.11.0: Points of interest

Cities now set whole blocks aside for points of interest, or 2 x 1 and 2 x 2
superblocks where no street crosses between the blocks. Each kind has two to
four layouts, and the new pure-Python `sites.py` lays them out:

| Site | Layouts | Contents |
| --- | --- | --- |
| Gas station | Back, Side | Kiosk shop, canopy over pump islands with bollards, price pylon, parking stalls; Side adds a car wash |
| Fast food | Mansard, Box, Diner | Restaurant (dining room, kitchen) with a mansard roof, a raised entrance box or a hipped diner roof; curbed drive-through lane with a window and menu board, patio, pole sign, bin enclosure |
| School | Bar, Wing | 2-3 storey classroom block and gym, entrance canopy, flagpole, fenced yard with a court, playing field and play area; Wing adds a second block joined by a covered walk, or a courtyard plan on shallow pads |
| Hospital | Tower, Slab | Podium and setback tower, or a long slab with an outpatient block; grand lobby, drive-under emergency canopy at the ambulance doors, drop-off island, parking, rooftop helipad |
| Police station | Civic, Modern | Masonry station with a portico or canopy, flagpoles, bollards, fenced back lot with a sally-port garage, roof mast |
| Fire station | Classic, Modern | Drive-through apparatus hall (2-4 bays) with living quarters, apron, sign band; Classic adds a drill tower |
| Transit station | Terminal, Hub | Station hall with a canopy; raised platforms under shelters (Terminal), or a bus island and a clock tower (Hub) |
| Park | Green, Playground, Plaza, Sports | Paths to a fountain; play equipment and picnic tables; planters and a monument; a pitch with goals, stands and floodlights |
| Parking lot | Rows, Angled | Painted stalls, planted end islands with trees or lamps, booth and barrier |
| Parking garage | Decks, Tall | Open decks (4-6 or 7-9 levels) linked by ramps, vehicle entrances, booth |
| Strip mall | Row, L | Shop units with front and back doors, arcade on columns, unit signs, parking, pylon |
| Shopping plaza | Pair, Anchor | Two big boxes with shops between them, or an anchor and junior box with a shop wing; entrance portals, loading doors, an outparcel restaurant, cart corrals, a tall pylon |

Transit stops (a shelter, or a pole and bench) stand mid-block on arterial and
collector footways.

- Site buildings are ordinary generator shells with their own floor plans
  (shop units, dining room and kitchen, classrooms, apparatus bays), so they
  are enterable and take damage like any other building.
- Sites take a condition from their district. Props fixed to a building, such
  as canopies, signs and porticos, go with it: they are dropped when the
  building collapses, and where its wall broke below them. A collapsed site
  keeps its pad and free-standing props, with a rubble heap scaled to the
  building's height. Damaged sites have some dead trees.
- New operator **Shift+A > Mesh > Generate Site (Point of Interest)**: kind,
  layout, pad size, seed and condition.
- The city has a **Points of Interest** switch. Plan schema 5 adds `pois` and
  `shelters`.
- Fixed: every city building's ground floor shared its plane with the lot
  foundation, so the floors z-fought. Under the ground storey, the foundation
  now drops to the underside of the ground slab.
- Tests check every kind, layout, pad size and condition:
  - the grounds are closed with no coplanar overlaps, including against the
    buildings;
  - buildings fit the pad and plans are reachable;
  - no prop covers a door or window, and no window faces a neighbour flush
    against it;
  - every kind is placed in the default city, clear of footways.

## v0.10.1: Collapse variety

Collapsed buildings now pick one of seven archetypes by seed: corner, stepped
(breaking storey by storey), shear (a side sliced off on a diagonal), cleave
(split along a plan diagonal), sawtooth (several roofline bites), gutted
(facades standing, floors fallen in) and blowout (multi-storey holes blown
through mid-height with the floors above intact). Collapses land on the tier
standing at their height, so setback towers break where their walls are.
Blast holes have ragged edges and spill debris to the street. Everything stays
watertight; every archetype is tested on four styles.

## v0.10.0: Closed-solid geometry, polygonal collapses, real floor plans

The geometry pipeline is rebuilt (see [ARCHITECTURE.md](ARCHITECTURE.md) for
the audit and design). Every wall, slab, partition and stair is now built as a
closed solid from its final outline, so damage of any shape cannot leave holes,
and no two faces z-fight. Tested on every style and condition: no open edges,
no flipped faces, no coplanar overlaps.

- **Damage.** Collapses are polygonal craters with sloped, jagged sides: facades
  break in diagonals and steps, floor slabs step back storey by storey along
  broken edges, and walls, slabs, partitions and stairs agree on what is
  missing. Exposed fills get jagged breaches; weathered facades get blast holes.
  Windows the break passes through are filled so ruins read as masonry.
- **Interiors.** Real floor plans: corridor apartment blocks with flats (hall,
  bath, kitchen, living room, bedroom), town-house walk-ups, shops either side
  of a stair hall, houses, office floors around a stair-and-lift core, warehouses
  and bars. Every room is reachable through a door the player fits through;
  partitions never land on a window.
- **Scale.** Sized for the Ares player: 1.2 x 2.3 m interior doors (were
  0.9 m and, upstairs, 1.95 m clear), 1.8 m corridors, 1.3 m stair flights,
  0.25 m slabs, taller ground floors for shops and lobbies, believable window
  heads, thick masonry for old town.
- **Towers.** Lobby types (grand double-height lobby with desk and canopy,
  retail podium, colonnade arcade, pilotis), curtain/ribbon/punched facades,
  podium and setback tiers, plant floors, stepped crowns, masts and plant rooms.
- **Operators.** The single-building operator adds Lobby, Facade, Taller Ground
  Floor, Cornices, Tower Core and the Office/House profiles; Generate Building
  by Style adds a Lobby override and up to 40 floors.
- Gable houses get a ceiling under the roof (the sky no longer shows through).
- Generation is pure Python up to the Blender adapter, so real buildings can
  be tested without Blender.

## v0.9.9: Skyscraper cores

DOWNTOWN office towers now use a centered service core: two elevator shafts
at the front, a rear switchback stair, core doors, and stair/elevator slab
cutouts. Floor slabs support multiple openings. The core and stairs are built
even for shell-only skyscrapers; furnished office floors add the meeting room
and open plate around it. Wall tops and wall ends are capped at floor lines
and on weathered roof spikes.

## v0.9.8: Floor plates and wall tops

Non-interior lots now get solid floor plates instead of stair cutouts, while
interior lots get capped floor-cutout sides. Wall cells are capped at every
floor, vertical wall ends and spike tips are paired into caps, and small open
top loops are closed.

## v0.9.7: Wall shell repair

Damage and chunk cuts could remove a wall's inner facade while leaving the
outer face, opening the wall cavity to the interior. Surviving outer wall faces
are now mirrored inward wherever the inner face is missing, and the remaining
top edges are paired into wall caps.

## v0.9.6: Capped chunk cuts

Chunk removals are bisected exactly at their cut planes. Exposed floor-slab
edges, interior partitions and stair sections get cut caps; the exterior wall
thickness keeps its shelf cap, while open rooms intentionally stay open.

## v0.9.5: Window-clear interiors

Stair cores keep a 1 m aisle from side facades and stop 0.6 m clear of the
front/back window planes. Interior partitions are pulled 0.6 m clear of every
exterior opening, so office and storefront walls no longer sit in or directly
behind window reveals.

## v0.9.4: Interior fit-out

Interiors now use solid, capped wall boxes with real door openings and headers.
Apartment, office, house, storefront, warehouse and bar profiles place their own
walls on every floor; the stair core gets a double-flight switchback with a
turning landing, solid steps and a matching floor-slab opening. Partitions that
would land in an exterior door or window are pulled clear instead of vanishing,
and the stair treads and wall caps survive mesh cleanup.

## v0.9.3: Ragged parapets

A broken top is now a ragged parapet at most one storey above the break line,
so the floors below keep their windows; deeper damage comes from whole cuts.

## v0.9.2: Capped chunk-cut walls

Walls are capped where a chunk cut removes them, so cuts show a broken wall top
instead of an open edge.

## v0.9.1: Rubble mounds

Loose debris is replaced by rubble mounds at cut bases and inside wall rings,
and tall towers take heavier damage.

## v0.9.0: Failure-model ruins

Buildings fail the way neglected towers do: weathered tops, vertical corner and
bay slices, solid rubble fills behind standing facades (exposed through a
ground-floor bay and an upper cut), half-filled lower floors, roofless shells,
and low wall rings with a mound inside.

## v0.8.2: Facade detail on ruins

Damaged buildings keep their facade detail; broken tops are smoothed and whole
upper chunks are cut away.

## v0.8.1: Chunked damage

Weathered walls lose large polygonal chunks, and collapsed lots become rubble
mounds.

## v0.8.0: Building conditions and interior budget

Every city building gets a condition (intact, weathered, semi-collapsed,
rubble-filled, lower floors only, roofless shell or collapsed) from its
district's weights, and **Interior Ratio** sets the share of enterable
buildings that get full interiors.

## v0.7.0: Metro scale and open wasteland

The radius control scales the city from a district to a metro, the ground runs
on past the city as open wasteland, and the suburbs are denser.

## v0.6.0: City districts

Six district archetypes: downtown towers, old town, residential and brutalist
blocks, industrial sheds and suburban houses. Districts also change parcel
size, density, local street growth, corner radii and damage.

## v0.5.0: Curved roads

Road centrelines curve through filleted junctions. Streets are tessellated
from a distance field, so junctions are the union of the curved corridors with
no overlapping faces.

## v0.4.0: Street-level city

Connected road tiers, driving circuits, sidewalks, curb ramps and foundations,
and **File > Export > Generated City for Unity (.fbx)** for the static city
meshes.

## v0.3.0: City generation prototype

New **Generate City** and **Generate Building by Style** commands: seeded city
growth, four architecture recipes, road tiers, district assignment, density
controls, and preview or detailed output.

## v0.2.0

- Added **Bulk Generate Buildings** operator
  - Row, Grid, and Random layouts
  - Parameter ranges for width, depth, floors, floor height
  - Generates buildings into a named collection
- Added **wall top caps** when roof is disabled
- Improved geometry cleanup (edge dissolution for cleaner meshes)
- Fixed floor connection seams

## v0.1.0

- Initial release
- Procedural wall generation with window/door cutouts
- Storefront mode for ground floor
- Configurable damage system
- Material slot creation
- Full operator UI with organized parameter groups
