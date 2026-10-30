// Ares city metadata ("ares.city.metadata", schema 1): data classes for
// UnityEngine.JsonUtility. Copy into the Unity project, then:
//
//     var city = JsonUtility.FromJson<Ares.CityGen.CityMetadata>(File.ReadAllText(path));
//
// Positions are float[3] in Unity world space, matching the GameObjects of the
// FBX exported beside the JSON; "yaw" turns an asset modelled facing +Z to face
// "forward". Point lists are flat (x, y, z, x, y, z, ...); lattice nodes are
// flat (x, y, x, y, ...). Unknown numbers are 0 and unknown strings empty.
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
        public Building[] buildings;
        public Site[] sites;
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
    }

    [Serializable]
    public class CityInfo
    {
        public int seed;
        public float[] origin;
        public float extent;
        public float block_size;
        public float wasteland;
        public float curb_height;
        public float sidewalk_width;
        public bool small_props_modelled;
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
    }

    [Serializable]
    public class Junction
    {
        public int[] node;
        public float[] position;
        public float radius;      // Widest road half-width plus the footway.
        public int roads;         // Road segments meeting here.
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
        public string[] party_walls;
        public string group;
        public int seed;
        public float width;       // Along the front.
        public float depth;
        public float height;
        public int enterable_floors;
        public Entrance[] entrances;
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
        // swings, goal, trash_bin, air_pump, hydrant, cart_corral (small props),
        // tree, flagpole, fence, parking_stall.
        public string type;
        public string site;
        public bool modelled;     // True when the city mesh already has this prop.
        public float[] size;      // Width, depth[, height] where it applies.
        public float height;      // Lamps, flagpoles, fences.
        public float scale;       // Trees: relative size, about 1.
        public bool umbrella;     // Tables.
        public float[] barrier;   // Booths: direction of the barrier arm.
        public float[] points;    // Fences: post line (flat x, y, z).
    }

    [Serializable]
    public class Counts
    {
        public int buildings;
        public int sites;
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
