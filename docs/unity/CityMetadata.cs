// Ares city metadata ("ares.city.metadata", schema 2): data classes for
// UnityEngine.JsonUtility. Copy into the Unity project, then:
//
//     var city = JsonUtility.FromJson<Ares.CityGen.CityMetadata>(File.ReadAllText(path));
//
// Positions are float[3] in Unity world space, matching the GameObjects of the
// FBX exported beside the JSON; "yaw" turns an asset modelled facing +Z to face
// "forward". Point lists are flat (x, y, z, x, y, z, ...); lattice nodes are
// flat (x, y, x, y, ...). Unknown numbers are 0 and unknown strings empty.
//
// Interiors (a building's rooms, lifts and railings) are in building space:
//
//     Vector3 World(Building b, float[] p) =>
//         new Vector3(b.position[0], b.position[1], b.position[2]) +
//         Quaternion.Euler(0, b.yaw, 0) * new Vector3(p[0], p[1], p[2]);
//
// Directions ("normal") rotate the same way. Furniture, railings, lift doors
// and lift cars are game assets: the city mesh has none of them.
using System;

namespace Ares.CityGen
{
    [Serializable]
    public class CityMetadata
    {
        public string format;
        public int schema;
        public string addon_version;
        public int plan_version;
        public string collection;
        public SpaceInfo space;
        public CityInfo city;
        public District[] districts;
        public Road[] roads;
        public Junction[] junctions;
        public DrivingLoop[] driving_loops;
        public OuterRoad[] outer_roads;
        public Terrace[] terraces;      // Terraced terrain: raised blocks behind retaining walls.
        public Ramp[] ramps;
        public Stair[] stairs;
        public Freeway freeway;         // A raised highway (null when it runs at grade).
        public Ditch[] ditches;         // Along the rural streets, beyond their gravel shoulders.
        public Culvert[] culverts;      // Where each ditch ends (two per ditch).
        public Building[] buildings;
        public Site[] sites;
        public Yard[] yards;
        public TransitStop[] transit_stops;
        public Marker[] markers;
        public Counts counts;
        public string[] missing_objects;
    }

    [Serializable]
    public class SpaceInfo
    {
        public string name;
        public string units;
        public string up;
        public string from_blender;
        public string yaw;
        public string interiors;
    }

    [Serializable]
    public class CityInfo
    {
        public string preset;           // CITY or SMALL_TOWN.
        public string shape;            // SQUARE or ORGANIC (an irregular edge).
        public int seed;
        public float[] origin;
        public float extent;
        public float block_size;
        public float wasteland;
        public float curb_height;
        public float sidewalk_width;
        public bool small_props_modelled;
        public bool interiors_listed;   // False: rooms, lifts and railings left out.
        public bool water_modelled;     // False: basins are dry; fill them from "water" markers.
        public string terrain;          // FLAT, ROLLING or TERRACED; heights are in every position.
        public float relief;            // Hills: the setting, metres low to high.
        public float wild_extent;       // Hills: half-side of the graded wild land round the map (0: none); level beyond.
        public string rural_streets;    // AUTO (on hills), ON or OFF: shoulders and ditches on suburban streets.
        public float plateau_height;    // Terraced: the plateau's rise (setting).
        public int podiums;             // Terraced: how many podiums were asked for.
        public string highway;          // RAISED (on a viaduct) or GRADE.
    }

    [Serializable]
    public class District
    {
        public string id;
        public string role;
        public string style;
        public float[] position;
    }

    [Serializable]
    public class Road
    {
        public string id;
        public string tier;       // HIGHWAY, ARTERIAL, COLLECTOR or LOCAL
        public float width;       // Carriageway width; footways run along both sides.
        public int[] nodes;       // Lattice nodes along the route.
        public float[] points;    // Centreline at carriageway level.
        public int[] rural_edges; // k: nodes k to k+1 have a gravel shoulder and ditches, no curbs.
    }

    [Serializable]
    public class Junction
    {
        public int[] node;
        public float[] position;
        public float radius;      // Widest road half-width plus the footway.
        public int roads;         // Road segments meeting here.
        public bool cul_de_sac;   // A dead end with a turning circle (radius above).
    }

    [Serializable]
    public class DrivingLoop
    {
        public string id;
        public int[] nodes;
        public string[] tiers;
        public float length_m;
    }

    [Serializable]
    public class OuterRoad
    {
        public string id;
        public float width;
        public float[] start;
        public float[] forward;
        public float length;      // Beyond the city edge.
        public float fade;        // Last stretch where the surface breaks up.
    }

    [Serializable]
    public class Terrace
    {
        public string id;
        public string kind;       // plateau or podium.
        public float rise;        // Metres above the hills round it.
        public int[] blocks;      // Lattice blocks on top (x, y pairs, flattened).
        public int[] slope_blocks; // Blocks where it falls naturally to the ground round it.
    }

    [Serializable]
    public class Ramp
    {
        public string id;
        public string terrace;
        public int[] nodes;       // Lattice junctions from the top down (x, y pairs).
        public float[] points;    // Their positions (x, y, z triples).
        public Viaduct[] viaducts; // Stretches standing on piers.
    }

    [Serializable]
    public class Viaduct
    {
        public float[] start;     // Deck centreline at each end, at road level.
        public float[] end;
        public float[] piers;     // Pier foot centres (x, y, z triples).
    }

    [Serializable]
    public class Freeway
    {
        public float width;
        public FreewayInterchange[] interchanges;
        public float[] mainline;  // Deck centreline at road level (x, y, z triples), west to east.
        public float[] touchdown; // Where it meets the ground: the mainline's two ends.
        public FreewayRamp[] ramps;
        public float[] piers;     // Pier foot centres (x, y, z triples).
    }

    [Serializable]
    public class FreewayInterchange
    {
        public int[] node;        // The cross street's lattice node on the highway's line.
        public float[] position;
    }

    [Serializable]
    public class FreewayRamp
    {
        public string id;
        public string kind;       // off or on.
        public int interchange;   // Index into interchanges.
        public string side;       // south (eastbound) or north (westbound).
        public float width;
        public float climb;       // Metres from its foot to the deck's level...
        public float taper;       // ...then this far while its lane joins the deck.
        public float[] points;    // Centreline from the cross street (x, y, z triples).
    }

    [Serializable]
    public class Stair
    {
        public string id;
        public string terrace;
        public float[] top;       // Centre of the top step's edge, at the upper footway.
        public float[] bottom;    // ...and of the foot, at the lower footway.
        public float width;
        public int steps;
        public float riser;
    }

    [Serializable]
    public class Pose
    {
        public float[] position;
        public float[] forward;
        public float yaw;
    }

    [Serializable]
    public class Entrance : Pose
    {
        public float width;
    }

    [Serializable]
    public class Building : Pose
    {
        public string id;
        public string @object;    // GameObject name.
        public string kind;
        public string style;
        public string district;
        public string condition;
        public int floors;
        public float damage;
        public bool interiors;
        public string structure;  // FITTED, PARTITIONS, BEARING (gutted, rubble on the floors) or NONE.
        public string footprint;  // RECT, L, T, U or O (courtyard).
        public float[] wings;     // Two opposite ground corners (x, y, z) per wing, building space.
        public string[] party_walls;
        public string group;
        public int seed;
        public float width;       // Along the front.
        public float depth;
        public float height;
        public int enterable_floors;
        public Entrance[] entrances;
        public Room[] rooms;
        public Lift[] lifts;
        public Railing[] railings;
    }

    [Serializable]
    public class SiteBuilding : Pose
    {
        public string @object;
        public string role;
        public string name;
        public int floors;
        public float height;
        public int enterable_floors;
        public float width;
        public float depth;
        public Entrance[] entrances;
        public Room[] rooms;
        public Lift[] lifts;
        public Railing[] railings;
    }

    // -- interiors (building space) -------------------------------------------

    [Serializable]
    public class Room
    {
        public string name;       // Unique within its floor.
        // bedroom, living, kitchen, bath, hall, corridor, lobby, office, open,
        // shop, storage, bar, auditorium, plant, stair, landing, ...
        public string kind;
        public int floor;
        public string unit;       // Flat or shop unit it belongs to ("" if none).
        public string group;      // Open-plan group: rooms of one group share a space.
        public float[] position;  // Centre of the clear floor.
        public float width;       // Clear size along the building's width,
        public float depth;       // and along its depth.
        public float height;      // Clear height to the ceiling.
        public float standing;    // Share of the floor still there (damage), 0-1.
        public float ceiling;     // Share still roofed by the storey above, 0-1.
        public RoomDoor[] doors;
        public RoomWindow[] windows;
        public WallRun[] wall_runs;
    }

    [Serializable]
    public class RoomDoor
    {
        public float[] position;  // Centre of the opening at floor level.
        public float[] normal;    // Into the room.
        public float width;
        public float height;
        public string to;         // Room on the other side, "street", or "".
    }

    [Serializable]
    public class RoomWindow
    {
        public float[] position;  // Centre of the sill on the inner wall face.
        public float[] normal;    // Out of the building.
        public float width;
        public float sill;        // Above the floor.
        public float head;        // Above the floor.
        public bool broken;       // The wall above broke off with it.
    }

    [Serializable]
    public class WallRun
    {
        public float[] start;     // At floor level, on the clear wall face.
        public float[] end;
        public float[] normal;    // Into the room. Blank wall: no door, window or hole,
                                  // at least 2 m of it standing.
    }

    [Serializable]
    public class Lift
    {
        public string name;
        public float[] position;  // Centre of the shaft floor (its lowest stop).
        public float width;       // Clear shaft size.
        public float depth;
        public float height;      // Shaft height above its lowest stop.
        public int[] floors;      // Floors it still serves.
        public LiftDoor[] doors;
        public LiftCar car;
    }

    [Serializable]
    public class LiftDoor
    {
        public int floor;
        public float[] position;  // Centre of the opening at floor level.
        public float[] normal;    // Out of the shaft.
        public float width;
        public float height;
    }

    [Serializable]
    public class LiftCar
    {
        public int floor;         // Where the car waits.
        public float[] position;  // Centre of its floor.
        public float width;
        public float depth;
        public float height;
    }

    [Serializable]
    public class Railing
    {
        public string kind;       // stair (handrail), guard (floor edge) or ramp
        public int floor;
        public float[] points;    // Base line on the walking surface (flat x, y, z).
        public float height;      // Rail height above the base line.
    }

    // -------------------------------------------------------------------------

    // A courtyard or estate grounds inside a superblock: a level pad (position
    // at its centre, pad level); its trees, benches and play equipment are
    // markers whose `site` is the yard's id.
    [Serializable]
    public class Yard : Pose
    {
        public string id;
        public string @object;
        public string kind;       // COURTYARD or GROUNDS.
        public string variant;    // GARDEN, PLAY or COURT.
        public string district;
        public int seed;
        public float width;       // Along world x (Blender); the pad is axis-aligned.
        public float depth;
    }

    // A V-ditch beside a rural street: start and end along its bottom (the
    // ground's level there, less depth), `outward` from the street to it.
    [Serializable]
    public class Ditch
    {
        public string id;
        public float[] start;
        public float[] end;
        public float width;
        public float depth;
        public float[] outward;
    }

    // A culvert's headwall across a ditch's end: position at the bottom of
    // its face (the pipe's opening), `facing` into the ditch.
    [Serializable]
    public class Culvert
    {
        public string id;
        public string ditch;
        public float[] position;
        public float[] facing;
    }

    [Serializable]
    public class Site : Pose
    {
        public string id;
        public string @object;    // Grounds GameObject; its buildings are children.
        public string kind;
        public string variant;
        public string condition;
        public string district;
        public int seed;
        public float width;
        public float depth;
        public SiteBuilding[] buildings;
    }

    [Serializable]
    public class TransitStop : Pose
    {
        public string id;
        public string @object;
        public string variant;    // SHELTER or STOP
        public int[] road;        // Lattice edge (x, y, x, y).
    }

    [Serializable]
    public class Marker : Pose
    {
        // bench, lamp, bollard, gas_pump, dumpster, table, booth, play_structure,
        // swings, goal, trash_bin, air_pump, hydrant, cart_corral, tyre_stack, speaker_post
        // (small props),
        // tree, flagpole, fence, parking_stall; bar_counter, reception_desk,
        // service_counter, shop_counter, seat (fixtures inside buildings; a seat
        // stands on its cinema tier and faces the screen); water
        // (position = centre of the surface, size = width, depth, water depth).
        public string type;
        public string site;
        public string building;   // Fixtures: the building's GameObject name.
        public int floor;         // Fixtures: the floor they stand on.
        public bool modelled;     // True when the city mesh already has this prop.
        public float[] size;      // Width, depth[, height] where it applies.
        public float height;      // Lamps, flagpoles, fences.
        public float scale;       // Trees: relative size, about 1.
        public bool umbrella;     // Tables.
        public float[] barrier;   // Booths: direction of the barrier arm.
        public float[] points;    // Fences: post line (flat x, y, z).
        public string shape;      // Water: "circle" or "rect".
    }

    [Serializable]
    public class Counts
    {
        public int buildings;
        public int sites;
        public int yards;
        public int ditches;
        public int culverts;
        public int transit_stops;
        public MarkerCount[] markers;
    }

    [Serializable]
    public class MarkerCount
    {
        public string type;
        public int count;
    }
}
