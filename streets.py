# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure street surface tessellation for curved road paths.

The network is described by a scalar field ``A(p)``: the smallest distance from
``p`` to any centreline segment minus that road's half width. Carriageway is
``A <= 0``, footway is ``0 < A <= sidewalk_width``.

Both regions are extracted per sample cell by clipping its two triangles against
those two iso-levels. Interpolation is linear per triangle, so every crossing
vertex is shared by the neighbouring cell and by the adjacent region: no boolean
geometry, no cracks and no overlapping faces, while junctions become the natural
union of the curved corridors. Road corners are fillets, so their bend radius is
explicit in the centreline rather than an artefact of the grid.
"""
from collections import defaultdict
import bisect
import math

SAMPLE = 1.5          # Metres per surface sample cell.
GROUND_CELL = 12.0    # Metres per terrain cell; a multiple of SAMPLE.
CURB_BOTTOM = -0.2
GROUND_Z = -0.02
FIELD_CELL = 40.0     # Metres per spatial-hash cell for centreline segments.
# On terrain: a finer ground grid (its error against the smooth road-level
# surface stays a few centimetres), set lower so it never shows through the
# asphalt, cut back round every building pad and held up under the curbs.
GROUND_CELL_TERRAIN = 3.0
GROUND_Z_TERRAIN = -0.06
CURB_BOTTOM_TERRAIN = -2.5   # Curb skirts on terrain: walls retaining the footway above lower pads.
PAD_CLEAR = .1        # Ground stays this far under a pad's top.
PAD_CUT_SLOPE = .6    # Cut slope back up from a pad to the natural ground.
PAD_FILL_SLOPE = .4   # Fill slope down from a pad to the natural ground.
PAD_SHOULDER = 1.5    # Level ground round a pad before its cut or fill slope.
PAD_REACH = 20.0      # How far round a pad its cut and fill slopes are looked for.
PAD_CELL = 24.0       # Metres per spatial-hash cell for pads.
# Terraced cities: stairs up a terrace's face, and the walls.
STAIR_RISE = .17      # Most a step rises.
STAIR_LANDING = 3.0   # Landing under each street's footway.
STAIR_INSET = .02     # Steps stand this far inside the stair's walls.
STAIR_BASE = .5       # Steps are solid this far below the stair's foot.
# Retaining walls stand back from the footway they face by a verge
# WALL_GAP wide, at the footway's level less CURB_DROP. Ground up to the
# first RETAIN figure above the verge slopes up to it across the verge; past
# the second it stands behind a wall; between, partly.
WALL_GAP = 2.5
CURB_DROP = .1
RETAIN = (1.0, 2.0)
PARAPET = (1.5, .3, 1.0)   # Walls dropping more than this get a parapet this thick and high.
# Ramps high enough over the ground run on a viaduct: a deck DECK_DEPTH deep
# with VIADUCT_CLEARANCE under it at least, for VIADUCT_SPAN or more, on
# piers about PIER_SPACING apart (the first PIER_END from each end).
DECK_DEPTH = 1.2
ABUTMENT_DROP = .02        # An abutment's wall stops this far under the road.
RAMP_REACH = 12.0          # A ramp's route stays this near its lattice edges.
VIADUCT_CLEARANCE = 4.5
VIADUCT_SPAN = 20.0
PIER_SPACING = 18.0
PIER_END = 6.0
PIER_SIZE = (1.4, 2.2)     # Along the deck, across it.
PIER_CAP = (1.8, 1.0)      # Cap beam: along the deck, depth.
OUTER_STUB = 60.0     # Field segment past the map edge so a highway runs straight out.
OUTER_CUT = 40.0      # The street mesh hands over to the outer road this far out.
OUTER_RAMP = 2.0      # Footways ramp down to the shoulders over this length.
OUTER_SOLID_ROW = 30.0  # Metres between cross-sections of an outer road...
OUTER_FADE_ROW = 4.0    # ...and where it breaks up.
# On hills an outer road follows its own level (graded as a highway through
# the wild land) at stations OUTER_STATION apart, the cross-fall it has at
# the city's edge eased out over OUTER_TWIST; the ground meets its edges
# (out to the ground grid's next line) and climbs or drops from them at
# OUTER_SLOPE (1:2) to the hills: cuttings and embankments. The wild land's
# ground is fine-grained OUTER_CORRIDOR either side of it.
OUTER_STATION = 10.0
OUTER_TWIST = 30.0
OUTER_SLOPE = .5
OUTER_CORRIDOR = 60.0
# In a cutting a ditch (width, depth) runs at the foot of the cut slope, faded
# in as the cutting deepens past OUTER_DITCH_CUT; its lines fall on the
# ground grid's.
OUTER_DITCH = (6.0, .8)
OUTER_DITCH_CUT = (.1, .5)
TAIL_END = 'cut'        # A raised highway ramp's run at grade meets its deck.


def junctions(plan):
    result = {}
    for road in plan.roads:
        for node in (road.a, road.b):
            result[node] = max(result.get(node, 0), road.width / 2)
    return result


def flush_junctions(plan):
    """Junctions whose footways come down flush with the carriageway: every
    street node but a ramp's own raised junctions (no street crosses there)."""
    nodes = junctions(plan)
    for ramp in (getattr(plan, 'terraces', None) or {}).get('ramps', ()):
        for node in ramp['nodes'][1:-1]:
            nodes.pop(tuple(node), None)
    return nodes


def pavement_height(plan, x, y, nodes=None):
    """Flush corners with a 2 m transition to the raised footway on each approach."""
    size = plan.settings.block_size
    nodes = flush_junctions(plan) if nodes is None else nodes
    node = (round(x / size), round(y / size))
    if node not in nodes:
        return plan.settings.curb_height
    distance = max(abs(x - node[0] * size), abs(y - node[1] * size))
    ramp_start = nodes[node] + plan.settings.sidewalk_width
    return plan.settings.curb_height * min(1, max(0, (distance - ramp_start) / 2))


def lot_approach(lot, plan):
    """Distance from a lot's centre, along its facing, to the back of the
    footway it fronts (a turning circle's for a house round one)."""
    size = plan.settings.block_size
    if lot.bulb:
        radius = next(b['radius'] for b in plan.culdesacs if tuple(b['node']) == tuple(lot.bulb))
        centre = (lot.bulb[0] * size, lot.bulb[1] * size)
        return math.dist(centre, lot.center) - radius - plan.settings.sidewalk_width
    road = next(r for r in plan.roads if (r.a, r.b) == lot.frontage)
    mid = ((road.a[0] + road.b[0]) * size / 2, (road.a[1] + road.b[1]) * size / 2)
    facing = (math.sin(lot.rotation), -math.cos(lot.rotation))
    distance = sum((mid[i] - lot.center[i]) * facing[i] for i in range(2))
    return distance - road.width / 2 - plan.settings.sidewalk_width


def lot_yard(lot, plan):
    """World corners of a lot's foundation: the building and its approach
    out to the footway."""
    end = lot_approach(lot, plan)
    depth = lot.depth / 2 + end
    c, s = math.cos(lot.rotation), math.sin(lot.rotation)
    shift = (lot.depth / 2 - end) / 2          # Local y of the combined centre.
    centre = (lot.center[0] - shift * s, lot.center[1] + shift * c)
    return footprint(centre, lot.width, depth, lot.rotation)


BULB_PATH = 3.0          # Width of the path from a house round a turning circle to its footway.
DRIVEWAY = 3.5           # ...and of the driveway over a rural street's ditch (by style).
DRIVEWAYS = {'INDUSTRIAL': 8.0}
# A rural street (``plan.rural``): a gravel shoulder flush with the road where
# a footway would be, then a V-ditch DITCH_WIDTH wide and DITCH_DEPTH deep.
# Each ditch stops DITCH_END short of where a cross street's would be and at
# a pad in its way (a driveway, a site's approach), at a culvert's headwall
# (HEADWALL: thickness, height over the ground) with a pipe's opening
# (CULVERT_PIPE: width, height); none shorter than DITCH_LEAST.
DITCH_WIDTH = 3.0
DITCH_DEPTH = .7
RURAL_RAMP = 2.0         # A footway rises from a rural shoulder's level over this.
DITCH_END = 1.0
DITCH_LEAST = 4.0
HEADWALL = (.3, .15)
CULVERT_PIPE = (.6, .45)


class Sections:
    """The streets' cross-sections: which have a rural one (``plan.rural``),
    and how high the footway stands over the road (none on a rural
    street's shoulder)."""

    def __init__(self, plan):
        self.plan = plan
        self.size = plan.settings.block_size
        self.nodes = flush_junctions(plan)
        self.edges = {tuple(sorted((tuple(a), tuple(b)))) for a, b in getattr(plan, 'rural', ())}
        rows = []
        if self.edges:
            for path in plan.paths:
                half = path['width'] / 2
                for a, b in zip(path['points'], path['points'][1:]):
                    if self.edge_of((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) in self.edges:
                        rows.append((a[0], a[1], b[0], b[1], half))
            # A turning circle at the end of a rural street is one too.
            for bulb in getattr(plan, 'culdesacs', ()):
                node = tuple(bulb['node'])
                if any(node in edge for edge in self.edges):
                    x, y = node[0] * self.size, node[1] * self.size
                    rows.append((x, y, x, y, bulb['radius']))
        self.field = Field(plan) if rows else None
        self.rural = Field(plan, rows=rows) if rows else None

    def edge_of(self, x, y):
        """The lattice edge nearest a point on a street's centreline."""
        u, v = x / self.size, y / self.size
        if abs(v - round(v)) <= abs(u - round(u)):
            k = math.floor(u)
            return ((k, round(v)), (k + 1, round(v)))
        k = math.floor(v)
        return ((round(u), k), (round(u), k + 1))

    def rural_at(self, x, y):
        """Whether the street nearest (x, y) is a rural one."""
        return self.rural is not None and self.rural.value(x, y) <= self.field.value(x, y) + 1e-6

    def pavement(self, x, y):
        """Footway height over the road at (x, y) (``pavement_height``): none
        on a rural shoulder, and rising from it over RURAL_RAMP where a
        footway meets one."""
        if self.rural is None:
            return pavement_height(self.plan, x, y, self.nodes)
        beyond = self.rural.value(x, y) - self.field.value(x, y)
        if beyond <= 1e-6:
            return 0.0
        return pavement_height(self.plan, x, y, self.nodes) * min(1.0, beyond / RURAL_RAMP)


def sections(plan):
    """The plan's ``Sections`` (made once)."""
    found = plan.__dict__.get('_sections')
    if found is None:
        found = plan.__dict__['_sections'] = Sections(plan)
    return found


def approach_reach(lot, plan):
    """Half the width of a lot's approach from its footway: a path to a
    turning circle, a driveway over a rural street's ditch; None: the lot's
    whole width."""
    if lot.bulb:
        return BULB_PATH / 2
    if tuple(sorted(tuple(n) for n in lot.frontage)) in sections(plan).edges:
        return min(lot.width, DRIVEWAYS.get(lot.style, DRIVEWAY)) / 2
    return None
FORECOURT_APRON = 1.5    # Shortest apron from a forecourt to its building's floor.
FORECOURT_GRADE = .5     # Steepest an apron climbs or drops (1:2).
FORECOURT_STEP = 3.0     # Most metres between a forecourt's samples.


class Forecourt:
    """The paving from a footway to a building's front on terrain, in the
    lot's frame (x along the front, y toward the back: the door faces -y).

    It follows the street-level surface back from the footway (at the
    footway's own height at its front edge), so forecourts side by side meet
    level; only an apron at the building, FORECOURT_APRON long or more,
    climbs or drops to the floor, no steeper than FORECOURT_GRADE (the whole
    of a forecourt too short for that). ``top`` is triangulated as ``mesh``.
    """

    def __init__(self, center, rotation, xs, profile, front, back, floor):
        """``profile(x, y)``: the surface the outer part follows."""
        self.center, self.rotation = center, rotation
        self.xs, self.floor = list(xs), floor
        apron = FORECOURT_APRON
        for _ in range(12):
            start = back - apron
            if start <= front + 1e-6:
                break
            rise = max(abs(profile(x, start) - floor) for x in self.xs)
            need = max(FORECOURT_APRON, rise / FORECOURT_GRADE)
            if abs(need - apron) < 1e-3:
                break
            apron = need
        start = back - apron
        if start <= front + 1e-6:
            self.ys = [front]
        else:
            count = max(1, math.ceil((start - front) / FORECOURT_STEP))
            self.ys = [front + (start - front) * k / count for k in range(count + 1)]
        self.rows = [[profile(x, y) for x in self.xs] for y in self.ys]
        self.ys.append(back)
        self.rows.append([floor] * len(self.xs))
        self.polygon = [self.world(x, y) for x, y in ((xs[0], front), (xs[-1], front),
                                                      (xs[-1], back), (xs[0], back))]

    def world(self, x, y):
        c, s = math.cos(self.rotation), math.sin(self.rotation)
        return (self.center[0] + x * c - y * s, self.center[1] + x * s + y * c)

    def local(self, x, y):
        c, s = math.cos(self.rotation), math.sin(self.rotation)
        dx, dy = x - self.center[0], y - self.center[1]
        return dx * c + dy * s, dy * c - dx * s

    def top(self, x, y):
        """Top at a local point (or at the nearest point of the forecourt)."""
        xs, ys = self.xs, self.ys
        x, y = min(max(x, xs[0]), xs[-1]), min(max(y, ys[0]), ys[-1])
        i = min(max(bisect.bisect_right(xs, x) - 1, 0), len(xs) - 2)
        r = min(max(bisect.bisect_right(ys, y) - 1, 0), len(ys) - 2)
        u = (x - xs[i]) / (xs[i + 1] - xs[i])
        v = (y - ys[r]) / (ys[r + 1] - ys[r])
        z00, z10 = self.rows[r][i], self.rows[r][i + 1]
        z01, z11 = self.rows[r + 1][i], self.rows[r + 1][i + 1]
        if u >= v:
            return z00 + u * (z10 - z00) + v * (z11 - z10)
        return z00 + u * (z11 - z01) + v * (z01 - z00)

    def at(self, x, y):
        """Top at the forecourt's nearest point to a world point."""
        return self.top(*self.local(x, y))

    def lowest(self, x0, y0, x1, y1):
        """The lowest top over a world box (inf off the forecourt): of its
        triangles, each clipped to the box (to the box's bounds in the
        forecourt's frame, if that is turned other than square to it)."""
        corners = [self.local(x, y) for x in (x0, x1) for y in (y0, y1)]
        lx0, lx1 = min(p[0] for p in corners), max(p[0] for p in corners)
        ly0, ly1 = min(p[1] for p in corners), max(p[1] for p in corners)
        xs, ys, rows = self.xs, self.ys, self.rows
        best = math.inf
        for r in range(max(bisect.bisect_right(ys, ly0) - 1, 0),
                       min(bisect.bisect_left(ys, ly1), len(ys) - 1)):
            for i in range(max(bisect.bisect_right(xs, lx0) - 1, 0),
                           min(bisect.bisect_left(xs, lx1), len(xs) - 1)):
                a, b = (xs[i], ys[r], rows[r][i]), (xs[i + 1], ys[r], rows[r][i + 1])
                c, d = (xs[i + 1], ys[r + 1], rows[r + 1][i + 1]), (xs[i], ys[r + 1], rows[r + 1][i])
                for polygon in ([a, b, c], [a, c, d]):
                    for axis, value, below in ((0, lx0, False), (0, lx1, True),
                                               (1, ly0, False), (1, ly1, True)):
                        polygon = _halfplane(polygon, axis, value, below) if polygon else polygon
                    if polygon:
                        best = min(best, min(p[2] for p in polygon))
        return best

    def mesh(self, base):
        """The forecourt as a closed solid down to ``base`` (lot frame)."""
        xs, ys, n = self.xs, self.ys, len(self.xs)
        vertices = [(x, y, z) for y, row in zip(ys, self.rows) for x, z in zip(xs, row)]
        b = len(vertices)
        vertices += [(xs[0], ys[0], base), (xs[-1], ys[0], base),
                     (xs[-1], ys[-1], base), (xs[0], ys[-1], base)]
        faces = []
        for r in range(len(ys) - 1):
            for i in range(n - 1):
                a, c = r * n + i, (r + 1) * n + i
                faces += [(a, a + 1, c + 1), (a, c + 1, c)]
        last = (len(ys) - 1) * n
        faces.append((b, b + 3, b + 2, b + 1))
        faces.append((b, b + 1) + tuple(range(n - 1, -1, -1)))
        faces.append((b + 1, b + 2) + tuple(r * n + n - 1 for r in range(len(ys) - 1, -1, -1)))
        faces.append((b + 2, b + 3) + tuple(last + i for i in range(n)))
        faces.append((b + 3, b) + tuple(r * n for r in range(len(ys))))
        return vertices, faces


def forecourt(lot, plan, surface, nodes=None):
    """A lot's ``Forecourt`` on terrain (``surface``: the street level), or
    None where its building stands at the footway. It narrows to a path or
    a driveway where ``approach_reach`` says so."""
    end = lot_approach(lot, plan)
    back = -lot.depth / 2
    if -end >= back - .05:
        return None
    reach = approach_reach(lot, plan) or lot.width / 2
    nodes = flush_junctions(plan) if nodes is None else nodes
    pavement = sections(plan).pavement
    count = max(1, math.ceil(2 * reach / FORECOURT_STEP))
    xs = [-reach + 2 * reach * k / count for k in range(count + 1)]
    c, s = math.cos(lot.rotation), math.sin(lot.rotation)
    # Where the footway drops flush toward a junction, its kinks too.
    a = (lot.center[0] - reach * c + end * s, lot.center[1] - reach * s - end * c)
    b = (lot.center[0] + reach * c + end * s, lot.center[1] + reach * s - end * c)
    for t in _pavement_breaks(plan, nodes, a, b):
        x = -reach + 2 * reach * t
        if min(abs(x - v) for v in xs) > .05:
            bisect.insort(xs, x)
    curb = {}

    def profile(x, y):
        wx, wy = lot.center[0] + x * c - y * s, lot.center[1] + x * s + y * c
        if x not in curb:
            # The footway's own height above the street where the forecourt
            # meets it (flush at a junction's corner), carried back.
            fx, fy = lot.center[0] + x * c + end * s, lot.center[1] + x * s - end * c
            curb[x] = pavement(fx, fy)
        return surface(wx, wy) + curb[x]
    return Forecourt(lot.center, lot.rotation, xs, profile, -end, back,
                     plan.settings.curb_height + lot.level)


def _pavement_breaks(plan, nodes, a, b):
    """Fractions along a straight footway edge a-b (along the lattice) where
    ``pavement_height`` changes slope: a flush junction's ramp ends, and
    where the nearest side of its square turns."""
    size, walk = plan.settings.block_size, plan.settings.sidewalk_width
    axis = 0 if abs(b[0] - a[0]) >= abs(b[1] - a[1]) else 1
    if abs(b[1 - axis] - a[1 - axis]) > 1e-6 or abs(b[axis] - a[axis]) < 1e-6:
        return []
    found = []
    for node, half in nodes.items():
        n = (node[0] * size, node[1] * size)
        across = abs(a[1 - axis] - n[1 - axis])
        start = half + walk
        if across > start + 2 + size:
            continue
        for v in (start, start + 2, across):
            for at in (n[axis] - v, n[axis] + v):
                t = (at - a[axis]) / (b[axis] - a[axis])
                if 1e-6 < t < 1 - 1e-6:
                    found.append(t)
    return found


def approach_polygon(lot, plan):
    """World corners of a lot's approach from its footway to its front (as
    ``forecourt``), or None where it stands at the footway."""
    end, back = lot_approach(lot, plan), -lot.depth / 2
    if -end >= back - .05:
        return None
    reach = approach_reach(lot, plan) or lot.width / 2
    c, s = math.cos(lot.rotation), math.sin(lot.rotation)
    return [(lot.center[0] + x * c - y * s, lot.center[1] + x * s + y * c)
            for x, y in ((-reach, -end), (reach, -end), (reach, back), (-reach, back))]


class Ditch:
    """One run of a rural street's ditch, along one side of it: the street
    runs along ``axis`` (0: x) on ``line`` (its centreline's other
    coordinate), ``half`` wide each way; the ditch lies on ``side`` (+1 or
    -1) of it from ``start`` to ``end`` along it, from the shoulder's outer
    edge (``inner``) past its bottom to ``outer``."""

    def __init__(self, axis, line, half, side, start, end, walk):
        self.axis, self.line, self.half, self.side = axis, line, half, side
        self.start, self.end = start, end
        self.inner = line + side * (half + walk)
        self.bottom = line + side * (half + walk + DITCH_WIDTH / 2)
        self.outer = line + side * (half + walk + DITCH_WIDTH)

    def depth(self, x, y):
        """How far the ditch sinks the ground at (x, y) (none off it)."""
        a, b = (x, y) if self.axis == 0 else (y, x)
        t = (b - self.inner) * self.side / DITCH_WIDTH
        if not (self.start - 1e-9 <= a <= self.end + 1e-9 and -1e-9 <= t <= 1 + 1e-9):
            return 0.0
        return DITCH_DEPTH * max(0.0, 1 - abs(2 * t - 1))

    def contains(self, x, y):
        a, b = (x, y) if self.axis == 0 else (y, x)
        lo, hi = sorted((self.inner, self.outer))
        return self.start < a < self.end and lo < b < hi

    def rect(self, margin=0.0):
        """World rectangle of the ditch (grown by ``margin``)."""
        lo, hi = sorted((self.inner, self.outer))
        a0, a1, b0, b1 = self.start - margin, self.end + margin, lo - margin, hi + margin
        return (a0, b0, a1, b1) if self.axis == 0 else (b0, a0, b1, a1)

    def cuts(self):
        """Lines (axis, value) the ground is cut along: the bottom, the outer
        edge and the two ends (the inner edge is the footway's iso-line)."""
        across = 1 - self.axis
        return ((across, self.bottom), (across, self.outer),
                (self.axis, self.start), (self.axis, self.end))


def ditches(plan):
    """The ditches along the rural streets (``Ditch``; made once): each side
    of a street between its junctions, stopping short of each junction's
    corners and of any pad, approach or pier in the ditch's way."""
    found = plan.__dict__.get('_ditches')
    if found is not None:
        return found
    found = []
    section = sections(plan)
    if section.edges:
        size, walk = plan.settings.block_size, plan.settings.sidewalk_width
        halves = junctions(plan)
        bulbs = {tuple(b['node']): b['radius'] for b in getattr(plan, 'culdesacs', ())}
        widths = {}
        for path in plan.paths:
            nodes = [tuple(n) for n in path['nodes']]
            for a, b in zip(nodes, nodes[1:]):
                widths[tuple(sorted((a, b)))] = path['width'] / 2
        blocks = [footprint(lot.center, lot.width, lot.depth, lot.rotation) for lot in plan.lots]
        blocks += [polygon for polygon in (approach_polygon(lot, plan) for lot in plan.lots)
                   if polygon]
        blocks += [site_footprint(poi) for poi in plan.pois]
        blocks += [footprint(yard.center, yard.width, yard.depth, 0.0)
                   for yard in getattr(plan, 'yards', ())]
        if getattr(plan, 'freeway', None):
            for x, y, along, across, *_rest in freeway_stations(plan)['piers']:
                cap = max(across, _rest[-1]) / 2
                blocks.append([(x - along / 2, y - cap), (x + along / 2, y - cap),
                               (x + along / 2, y + cap), (x - along / 2, y + cap)])

        def zone(node):
            # Clear of a cross street's footway and ditch, and of a turning
            # circle's footway.
            return max(halves.get(node, 0.0) + DITCH_WIDTH, bulbs.get(node, 0.0)) + walk + DITCH_END
        for a, b in sorted(section.edges):
            if (a, b) not in widths:
                continue
            axis = 0 if a[1] == b[1] else 1
            line, half = a[1 - axis] * size, widths[a, b]
            low, high = (a, b) if a[axis] < b[axis] else (b, a)
            start, end = low[axis] * size + zone(low), high[axis] * size - zone(high)
            for side in (-1, 1):
                lo, hi = sorted((line + side * (half + walk), line + side * (half + walk + DITCH_WIDTH)))
                runs = [(start, end)]
                for polygon in blocks:
                    along = [p[axis] for p in polygon]
                    across = [p[1 - axis] for p in polygon]
                    if max(across) <= lo + 1e-6 or min(across) >= hi - 1e-6:
                        continue
                    if max(along) <= start or min(along) >= end:
                        continue
                    c0, c1 = min(along) - HEADWALL[0], max(along) + HEADWALL[0]
                    runs = [piece for s0, s1 in runs
                            for piece in ((s0, min(s1, c0)), (max(s0, c1), s1)) if piece[1] > piece[0]]
                found += [Ditch(axis, line, half, side, s0, s1, walk)
                          for s0, s1 in runs if s1 - s0 >= DITCH_LEAST]
    plan.__dict__['_ditches'] = found
    return found


def culverts(plan, ground=None):
    """Where each ditch ends: (ditch, end, direction) with ``end`` along the
    street and ``direction`` (+1/-1) the way the headwall stands from it."""
    return [(ditch, end, direction) for ditch in ditches(plan)
            for end, direction in ((ditch.start, -1), (ditch.end, 1))]


def build_culvert_mesh(plan, grading=None):
    """The culverts where the ditches end (closed boxes): a concrete
    headwall across the ditch, HEADWALL[1] over the ground, and on its face
    toward the ditch a pipe's dark opening at the bottom. Materials: 0
    concrete, 1 the pipe's opening."""
    found = culverts(plan)
    vertices, faces, materials = [], [], []
    if not found:
        return vertices, faces, materials
    if plan.heights:
        grading = grading or Grading(plan)

        def ground(x, y):
            return grading.ground(x, y)
    else:
        def ground(x, y):
            return GROUND_Z

    def box(axis, a0, a1, b0, b1, z0, z1, material):
        # Along the street a0-a1, across it b0-b1 (world x, y swapped on axis 1).
        def world(a, b):
            return (a, b) if axis == 0 else (b, a)
        corners = [world(a, b) for a, b in ((a0, b0), (a1, b0), (a1, b1), (a0, b1))]
        if axis == 1:
            corners.reverse()
        base = len(vertices)
        vertices.extend([(x, y, z) for z in (z0, z1) for x, y in corners])
        for f in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            faces.append(tuple(base + i for i in f))
            materials.append(material)
    for ditch, end, direction in found:
        lo, hi = sorted((ditch.inner, ditch.outer))
        a0, a1 = sorted((end, end + direction * HEADWALL[0]))

        def at(b):
            return ground(*((end, b) if ditch.axis == 0 else (b, end)))
        rims = [at(ditch.inner), at(ditch.outer)]
        bottom = at(ditch.bottom) - DITCH_DEPTH
        box(ditch.axis, a0, a1, lo, hi, bottom - .3, max(rims) + HEADWALL[1], 0)
        m0, m1 = sorted((end, end - direction * .03))
        half = CULVERT_PIPE[0] / 2
        box(ditch.axis, m0, m1, ditch.bottom - half, ditch.bottom + half,
            bottom - .05, bottom + CULVERT_PIPE[1], 1)
    return vertices, faces, materials


def _ditch_cells(plan, cell):
    """Ground cells (``cell`` metres) near a ditch, whose ground is made on
    the street mesh's sample grid instead (``_ditch_ground``)."""
    found = set()
    for ditch in ditches(plan):
        x0, y0, x1, y1 = ditch.rect(SAMPLE)
        found |= {(i, j) for i in range(math.floor(x0 / cell), math.floor(x1 / cell) + 1)
                  for j in range(math.floor(y0 / cell), math.floor(y1 / cell) + 1)}
    return found


def _ditch_ground(plan, cells, cell, field, vertex):
    """Faces of the ground over ``cells`` on the street mesh's sample grid:
    cut at the footways' outer edge as the street mesh is (sharing those
    vertices' positions) and along each ditch's lines; ``vertex(x, y,
    ditch)`` makes a vertex (sunk into ``ditch``, or None)."""
    walk = plan.settings.sidewalk_width
    per = int(round(cell / SAMPLE))
    near = defaultdict(list)
    for ditch in ditches(plan):
        x0, y0, x1, y1 = ditch.rect(SAMPLE)
        for i in range(math.floor(x0 / SAMPLE), math.floor(x1 / SAMPLE) + 1):
            for j in range(math.floor(y0 / SAMPLE), math.floor(y1 / SAMPLE) + 1):
                near[i, j].append(ditch)
    faces = []
    for ci, cj in sorted(cells):
        for i in range(ci * per, ci * per + per):
            for j in range(cj * per, cj * per + per):
                x0, y0 = i * SAMPLE, j * SAMPLE
                corners = tuple((x, y, field.value(x, y)) for x, y in
                                ((x0, y0), (x0 + SAMPLE, y0), (x0 + SAMPLE, y0 + SAMPLE),
                                 (x0, y0 + SAMPLE)))
                for triangle in _cell_triangles(corners, field, walk):
                    pieces = [_clip(triangle, walk, False)]
                    for ditch in near.get((i, j), ()):
                        for axis, value in ditch.cuts():
                            pieces = [half for piece in pieces
                                      for half in (_halfplane(piece, axis, value, True),
                                                   _halfplane(piece, axis, value, False))
                                      if len(half) >= 3]
                    for piece in pieces:
                        piece = _clean(piece)
                        if len(piece) < 3:
                            continue
                        cx = sum(p[0] for p in piece) / len(piece)
                        cy = sum(p[1] for p in piece) / len(piece)
                        owner = next((d for d in near.get((i, j), ()) if d.contains(cx, cy)), None)
                        ids = list(dict.fromkeys(vertex(x, y, owner) for x, y, _ in piece))
                        if len(ids) >= 3:
                            faces.append(tuple(ids))
    return faces


def _city_ground(plan, extent, cell, covered, field, vertex):
    """Faces of the ground over the city: cells of ``cell`` metres but those
    under the paving (all of their sample cells ``covered``), and round each
    ditch on the street mesh's sample grid; ``vertex(x, y, depth=...)``
    makes a vertex (sunk by ``depth``)."""
    per = int(round(cell / SAMPLE))
    count = defaultdict(int)
    for i, j in covered:
        count[i // per, j // per] += 1
    paved = {key for key, n in count.items() if n == per * per}
    finer = _ditch_cells(plan, cell) - paved
    fine = set()

    def sunk(x, y, ditch):
        # (On the finer grid the ground's own level shoulder round each pad
        # keeps it under the pad, which the cells' caps do on the coarser:
        # only where the two meet do those apply.)
        fine.add((x, y, 0.0))
        edge = any((math.floor((x + dx) / cell), math.floor((y + dy) / cell)) not in finer
                   for dx in (-1e-7, 1e-7) for dy in (-1e-7, 1e-7))
        return vertex(x, y, depth=ditch.depth(x, y) if ditch else 0.0, capped=edge)
    faces = _ditch_ground(plan, finer, cell, field, sunk)
    rim = _rim(fine, cell)
    for _, ring in _cell_rings(extent, cell, paved, finer, rim):
        ids = [vertex(x, y) for x, y in ring]
        if len(ids) == 4:
            faces.append(tuple(ids))
            continue
        xs, ys = [p[0] for p in ring], [p[1] for p in ring]
        middle = vertex((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
        faces += [(middle, a, b) for a, b in zip(ids, ids[1:] + ids[:1])]
    return faces


def _cell_rings(extent, cell, skip, finer, rim):
    """Each ground cell of ``cell`` metres over the city (clipped to
    ``extent``) but those in ``skip`` (under paving) or ``finer`` (made on a
    finer grid): its corners, and along a side shared with a finer cell the
    finer grid's vertices there (``rim``: {(axis, line): positions}), so
    they meet with no cracks. Yields ((i, j), ring)."""
    for i in range(math.floor(-extent / cell), math.ceil(extent / cell)):
        for j in range(math.floor(-extent / cell), math.ceil(extent / cell)):
            if (i, j) in skip or (i, j) in finer:
                continue
            x0, y0 = max(-extent, i * cell), max(-extent, j * cell)
            x1, y1 = min(extent, (i + 1) * cell), min(extent, (j + 1) * cell)
            if x1 <= x0 or y1 <= y0:
                continue

            def side(fixed, axis, a, b, neighbour):
                if neighbour not in finer:
                    return []
                lo, hi = min(a, b), max(a, b)
                inside = sorted(v for v in rim.get((axis, round(fixed, 8)), ())
                                if lo + 1e-6 < v < hi - 1e-6)
                inside = inside if a < b else inside[::-1]
                return [(v, fixed) if axis == 1 else (fixed, v) for v in inside]
            ring = [(x0, y0)] + side(y0, 1, x0, x1, (i, j - 1))
            ring += [(x1, y0)] + side(x1, 0, y0, y1, (i + 1, j))
            ring += [(x1, y1)] + side(y1, 1, x1, x0, (i, j + 1))
            ring += [(x0, y1)] + side(x0, 0, y1, y0, (i - 1, j))
            yield (i, j), ring


def _rim(vertices, cell):
    """{(axis, line): positions} of the vertices lying on a ``cell`` grid's
    lines (axis 0: x = line; 1: y = line)."""
    rim = defaultdict(set)
    for x, y, _ in vertices:
        for axis, (a, b) in enumerate(((x, y), (y, x))):
            if abs(a / cell - round(a / cell)) < 1e-7:
                rim[axis, round(round(a / cell) * cell, 8)].add(b)
    return rim


def _pad_top(top, x, y):
    """A pad's top at (x, y): a level pad's own, or a forecourt's there."""
    return top.at(x, y) if isinstance(top, Forecourt) else top


def _pad_lowest(top, x0, y0, x1, y1):
    """At most the lowest top of a pad over a world box."""
    return top.lowest(x0, y0, x1, y1) if isinstance(top, Forecourt) else top


def frontage_rectangle(lot, plan):
    """World XY foundation/approach envelope, used to cut the underlying terrain."""
    roads = {(r.a, r.b): r for r in plan.roads}
    road = roads[lot.frontage]
    size = plan.settings.block_size
    mid = ((road.a[0] + road.b[0]) * size / 2, (road.a[1] + road.b[1]) * size / 2)
    sin, cos = math.sin(lot.rotation), math.cos(lot.rotation)
    distance = (mid[0] - lot.center[0]) * sin - (mid[1] - lot.center[1]) * cos
    end = distance - road.width / 2 - plan.settings.sidewalk_width
    corners = [(lot.center[0] + x * cos - y * sin, lot.center[1] + x * sin + y * cos)
               for x in (-lot.width / 2, lot.width / 2) for y in (-end, lot.depth / 2)]
    return (min(p[0] for p in corners), min(p[1] for p in corners),
            max(p[0] for p in corners), max(p[1] for p in corners))


def _polyline_pieces(points, spans):
    """The parts of a polyline outside the arc-length intervals ``spans``."""
    pieces, current, along = [], [tuple(points[0])], 0.0
    cuts = sorted(spans)

    def inside(s):
        return any(s0 < s < s1 for s0, s1 in cuts)
    for a, b in zip(points, points[1:]):
        length = math.dist(a, b)
        marks = sorted({0.0, length} | {c - along for s0, s1 in cuts for c in (s0, s1)
                                        if 0 < c - along < length})
        for m0, m1 in zip(marks, marks[1:]):
            t0, t1 = m0 / length, m1 / length
            p0 = (a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0)
            p1 = (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)
            if inside(along + (m0 + m1) / 2):
                if len(current) > 1:
                    pieces.append(current)
                current = [p1]
            else:
                if not current:
                    current = [p0]
                current.append(p1)
        along += length
    if len(current) > 1:
        pieces.append(current)
    return pieces


def _point_at(points, target):
    along = 0.0
    for a, b in zip(points, points[1:]):
        length = math.dist(a, b)
        if length and target <= along + length:
            t = (target - along) / length
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        along += length
    return tuple(points[-1])


def _segments(plan, cut=None):
    """Field rows for every street; ``cut`` ({path id: spans}) leaves the
    viaducts out (the ground runs on under them). The street then ends
    square under each end of the deck (a flat-ended row), so the abutment
    there is a flat wall."""
    rows = []
    walk = plan.settings.sidewalk_width
    for path in plan.paths:
        half = path['width'] / 2
        spans = cut.get(path['id']) if cut else None
        if not spans:
            for a, b in zip(path['points'], path['points'][1:]):
                rows.append((a[0], a[1], b[0], b[1], half))
            continue
        reach = half + walk
        total = sum(math.dist(a, b) for a, b in zip(path['points'], path['points'][1:]))
        trimmed = [(max(0.0, s0 - reach), min(total, s1 + reach)) for s0, s1 in spans]
        for points in _polyline_pieces(path['points'], trimmed):
            for a, b in zip(points, points[1:]):
                rows.append((a[0], a[1], b[0], b[1], half))
        for s0, s1 in spans:
            for a, b in ((s0 - reach - 1.0, s0 - walk), (s1 + walk, s1 + reach + 1.0)):
                if b > a and a >= 0 and b <= total:
                    pa, pb = _point_at(path['points'], a), _point_at(path['points'], b)
                    rows.append((pa[0], pa[1], pb[0], pb[1], half, 'square'))
    for road in getattr(plan, 'outer_roads', ()):
        if road.get('deck'):
            continue
        (x, y), (dx, dy) = road['start'], road['direction']
        rows.append((x, y, x + dx * OUTER_STUB, y + dy * OUTER_STUB, road['width'] / 2))
    freeway = getattr(plan, 'freeway', None) or {}
    for ramp in freeway.get('ramps', ()):
        # A ramp's run at grade, from the cross street to its foot, where the
        # ramp's deck takes over: the road runs straight on, with no footway
        # round its end ('cut').
        (x0, y0), (x1, y1) = ramp['tail']
        rows.append((x0, y0, x1, y1, freeway['ramp_half'], TAIL_END))
    size = plan.settings.block_size
    for bulb in getattr(plan, 'culdesacs', ()):
        # A turning circle: a zero-length segment as wide as the circle.
        x, y = bulb['node'][0] * size, bulb['node'][1] * size
        rows.append((x, y, x, y, bulb['radius']))
    return rows


class _Outer:
    """An outer road in its own frame: ``along`` from the city edge, ``lateral``
    to the left of the direction of travel."""

    def __init__(self, plan, road):
        self.road = road
        (self.x, self.y), (self.dx, self.dy) = road['start'], road['direction']
        self.axis = 0 if abs(self.dx) > .5 else 1
        self.sign = (self.dx, self.dy)[self.axis]
        self.half = road['width'] / 2
        self.band = self.half + plan.settings.sidewalk_width
        start = (self.x, self.y)[self.axis]
        centre = (self.y, self.x)[self.axis]
        # The street mesh carries the highway, footways and all, OUTER_CUT
        # metres past the end node (clear of any junction there) and stops on a
        # sample-grid line; the outer road takes over across its band.
        handover = start + self.sign * OUTER_CUT
        self.cut = (math.ceil(handover / SAMPLE - 1e-9) if self.sign > 0
                    else math.floor(handover / SAMPLE + 1e-9)) * SAMPLE
        # Coming down off a raised highway's deck: no street mesh to meet.
        self.deck = bool(road.get('deck'))
        if self.deck:
            self.cut = start
        self.lo = math.floor((centre - self.band) / SAMPLE + 1e-9) * SAMPLE
        self.hi = math.ceil((centre + self.band) / SAMPLE - 1e-9) * SAMPLE
        self.centre = centre
        self.start = start
        self.end = start + self.sign * road['length']
        # Its level along its centreline, and its cross-fall at the cut.
        surface = plan.surface()
        count = max(1, math.ceil(self.length / OUTER_STATION - 1e-9))
        self.stations = [min(self.length, k * OUTER_STATION) for k in range(count + 1)]
        self.levels = [surface(*self.world(a, centre, 0.0)[:2]) for a in self.stations]
        self.surface = surface
        self.fall = {}

    def level(self, along):
        """The road's level on its centreline ``along`` metres past the cut."""
        if along <= 0:
            return self.levels[0]
        k = min(int(along / OUTER_STATION), len(self.stations) - 2)
        a0, a1 = self.stations[k], self.stations[k + 1]
        if a1 - a0 < 1e-9:
            return self.levels[k]
        return self.levels[k] + (self.levels[k + 1] - self.levels[k]) * (along - a0) / (a1 - a0)

    def cross_fall(self, lateral):
        """How far the road at the cut stands above its centreline's level at
        ``lateral`` (none off a deck)."""
        key = round(lateral, 8)
        if key not in self.fall:
            self.fall[key] = 0.0 if self.deck else (
                self.surface(*self.world(0.0, lateral, 0.0)[:2]) - self.levels[0])
        return self.fall[key]

    def twist(self, along):
        """Share of the cut's cross-fall left ``along`` metres past it (eased
        out over OUTER_TWIST, straight between the stations)."""
        def ease(a):
            t = max(0.0, 1.0 - a / OUTER_TWIST)
            return t * t * (3 - 2 * t)
        if along >= OUTER_TWIST:
            return 0.0
        a0 = math.floor(max(along, 0.0) / OUTER_STATION) * OUTER_STATION
        a1 = a0 + OUTER_STATION
        return ease(a0) + (ease(a1) - ease(a0)) * (max(along, 0.0) - a0) / OUTER_STATION

    def top(self, along, lateral):
        """The carriageway's (and shoulders') top at ``along``, ``lateral``."""
        return self.level(along) + self.cross_fall(lateral) * self.twist(along)

    def bends(self):
        """Stations where the road's level or twist bends (rows of its mesh)."""
        found = [a for k, a in enumerate(self.stations[1:-1], 1)
                 if abs((self.levels[k + 1] - self.levels[k]) * (a - self.stations[k - 1]) -
                        (self.levels[k] - self.levels[k - 1]) * (self.stations[k + 1] - a)) > 1e-9]
        if any(abs(self.cross_fall(b)) > 1e-9 for b in (self.lo, self.centre, self.hi)):
            found += [a for a in self.stations if a <= OUTER_TWIST]
        return found

    def drops(self, x0, y0):
        """True for street-mesh cells the outer road replaces."""
        if self.deck:
            return False
        a, b = (x0, y0) if self.axis == 0 else (y0, x0)
        beyond = a >= self.cut - 1e-9 if self.sign > 0 else a + SAMPLE <= self.cut + 1e-9
        return beyond and self.lo - 1e-9 <= b and b + SAMPLE <= self.hi + 1e-9

    def world(self, along, lateral, z):
        """Point at ``along`` metres past the cut and absolute ``lateral`` coordinate."""
        a = self.cut + self.sign * along
        return (a, lateral, z) if self.axis == 0 else (lateral, a, z)

    @property
    def length(self):
        return abs(self.end - self.cut)

    def rect(self, start):
        """Axis-aligned world rectangle of the road band from ``start`` (absolute)."""
        a0, a1 = sorted((start, self.end))
        b0, b1 = self.centre - self.band, self.centre + self.band
        return (a0, b0, a1, b1) if self.axis == 0 else (b0, a0, b1, a1)


def outer_roads(plan):
    return [_Outer(plan, road) for road in getattr(plan, 'outer_roads', ())]


def _hash01(seed, i, j):
    h = (i * 374761393 + j * 668265263 + seed * 2246822519) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFFFF) / float(0x1000000)


def _value_noise(seed, x, y, scale):
    gx, gy = x / scale, y / scale
    i, j = math.floor(gx), math.floor(gy)
    fx, fy = gx - i, gy - j
    sx, sy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a, b = _hash01(seed, i, j), _hash01(seed, i + 1, j)
    c, d = _hash01(seed, i, j + 1), _hash01(seed, i + 1, j + 1)
    return (a + (b - a) * sx) * (1 - sy) + (c + (d - c) * sx) * sy


def outer_asphalt(outer, seed, along, lateral):
    """Whether the road surface survives here; it breaks up over the fade,
    from the edges inward, into patches that thin out to nothing."""
    fade = outer.road['fade']
    start = outer.length - fade
    if along <= start or fade <= 0:
        return True
    f = (along - start) / fade
    if f >= .97:
        return False
    x, y, _ = outer.world(along, lateral, 0.0)
    n = .7 * _value_noise(seed, x, y, 16.0) + .3 * _value_noise(seed + 1, x, y, 5.0)
    edge = min(1.0, abs(lateral - outer.centre) / outer.band) ** 2
    return n - .25 * edge > .15 + .7 * f


def _square_distance(px, py, row):
    """Signed distance from a point to a flat-ended row's strip (a box)."""
    x0, y0, x1, y1, half = row[:5]
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    along = (px - x0) * ux + (py - y0) * uy
    across = abs((px - x0) * uy - (py - y0) * ux)
    ex, ey = abs(along - length / 2) - length / 2, across - half
    return math.hypot(max(ex, 0.0), max(ey, 0.0)) + min(max(ex, ey), 0.0)


def _cut_distance(px, py, row, walk):
    """A flat-ended row (as ``_square_distance``) whose second end opens onto
    something else's paving: past that end the field is unpaved at once, so
    no footway wraps round it."""
    x0, y0, x1, y1, half = row[:5]
    length = math.hypot(x1 - x0, y1 - y0)
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    along = (px - x0) * ux + (py - y0) * uy
    if along > length + 1e-9:
        return walk + 1.0 + 100.0 * (along - length)
    # Up to that end only the sides (and the first end) bound it.
    ex, ey = -along, abs((px - x0) * uy - (py - y0) * ux) - half
    return math.hypot(max(ex, 0.0), max(ey, 0.0)) + min(max(ex, ey), 0.0)


def _distance(px, py, segment):
    x, y, qx, qy, _ = segment
    dx, dy = qx - x, qy - y
    length = dx * dx + dy * dy
    if length:
        t = max(0.0, min(1.0, ((px - x) * dx + (py - y) * dy) / length))
    else:
        t = 0.0
    return math.hypot(px - x - dx * t, py - y - dy * t)


class Field:
    """Distance to the carriageway, indexed so sample points touch few segments
    (``rows``: of these segments only)."""

    def __init__(self, plan, extra=(), cut=None, rows=None):
        self.segments = (_segments(plan, cut) if rows is None else list(rows)) + list(extra)
        self.walk = plan.settings.sidewalk_width
        self.grid = defaultdict(list)
        for segment in self.segments:
            x0, y0, x1, y1, half = segment[:5]
            padding = half + self.walk + 2
            for i in range(math.floor((min(x0, x1) - padding) / FIELD_CELL),
                           math.floor((max(x0, x1) + padding) / FIELD_CELL) + 1):
                for j in range(math.floor((min(y0, y1) - padding) / FIELD_CELL),
                               math.floor((max(y0, y1) + padding) / FIELD_CELL) + 1):
                    self.grid[i, j].append(segment)
        self.cache = {}

    def value(self, x, y):
        index = (round(x, 8), round(y, 8))
        cached = self.cache.get(index)
        if cached is not None:
            return cached
        i, j = math.floor(x / FIELD_CELL), math.floor(y / FIELD_CELL)
        best = math.inf
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for segment in self.grid.get((i + di, j + dj), ()):
                    candidate = (_cut_distance(x, y, segment, self.walk) if
                                 len(segment) > 5 and segment[5] == 'cut' else
                                 _square_distance(x, y, segment) if len(segment) > 5 else
                                 _distance(x, y, segment) - segment[4])
                    if candidate < best:
                        best = candidate
        self.cache[index] = best
        return best

    def covered_cells(self):
        """Sample cells wholly inside the carriageway or footway envelope."""
        covered = set()
        for i, j in self.active_cells():
            if all(self.value((i + di) * SAMPLE, (j + dj) * SAMPLE) <= self.walk
                   for di, dj in ((0, 0), (1, 0), (1, 1), (0, 1))):
                covered.add((i, j))
        return covered

    def active_cells(self):
        cells = set()
        for x0, y0, x1, y1, half, *_ in self.segments:
            padding = half + self.walk + 2 + SAMPLE
            for i in range(math.floor((min(x0, x1) - padding) / SAMPLE),
                           math.floor((max(x0, x1) + padding) / SAMPLE) + 1):
                for j in range(math.floor((min(y0, y1) - padding) / SAMPLE),
                               math.floor((max(y0, y1) + padding) / SAMPLE) + 1):
                    cells.add((i, j))
        return cells


def _clip(polygon, threshold, keep_below):
    """Sutherland-Hodgman clip of a triangle against one iso-level.

    Vertices are ``(x, y, field)``; crossings are inserted at exactly the
    threshold so the shared iso-edge can be recognised afterwards.
    """
    result = []
    for index, current in enumerate(polygon):
        following = polygon[(index + 1) % len(polygon)]
        inside = current[2] <= threshold if keep_below else current[2] >= threshold
        next_inside = following[2] <= threshold if keep_below else following[2] >= threshold
        if inside:
            result.append(current)
        if inside != next_inside:
            span = following[2] - current[2]
            factor = 0.0 if span == 0 else (threshold - current[2]) / span
            result.append((current[0] + (following[0] - current[0]) * factor,
                           current[1] + (following[1] - current[1]) * factor,
                           threshold))
    return result


def _clean(polygon):
    result = []
    for point in polygon:
        if not result or math.dist(result[-1][:2], point[:2]) > 1e-9:
            result.append(point)
    if len(result) > 1 and math.dist(result[0][:2], result[-1][:2]) <= 1e-9:
        result.pop()
    return result


def _cell_triangles(corners, field, walk):
    """Split a sample cell into two triangles, refining one that lies flat on
    an iso-level.

    Three corners of equal value cannot distinguish the region inside the
    triangle: a triangle whose corners all sit exactly on the carriageway
    edge is empty asphalt, but linear interpolation would fill it. A centre
    sample (and three sub-triangles) resolves it; this only happens where a
    road edge coincides with the sample grid.
    """
    for selection in ((0, 1, 2), (0, 2, 3)):
        triangle = [corners[index] for index in selection]
        values = [point[2] for point in triangle]
        flat = max(values) - min(values) <= 1e-9
        if flat and (abs(values[0]) <= 1e-9 or abs(values[0] - walk) <= 1e-9):
            x = sum(point[0] for point in triangle) / 3
            y = sum(point[1] for point in triangle) / 3
            triangle.append((x, y, field.value(x, y)))
            for index in range(3):
                yield [triangle[index], triangle[(index + 1) % 3], triangle[3]]
        else:
            yield triangle


def build_street_mesh(plan):
    """Return vertices, faces, material indices for road/footway/curb/rural
    shoulder (0/1/2/3)."""
    walk = plan.settings.sidewalk_width
    field = Field(plan)
    section = sections(plan)
    vertices, faces, materials = [], [], []
    ids = {}
    curbs = set()
    surface = plan.surface() if getattr(plan, 'heights', None) else None
    # On terraces the walls (``build_wall_mesh``) close the footways' outer
    # edges inside the city ground; past it the skirts stay.
    walled = (plan.settings.radius * plan.settings.block_size + 20
              if getattr(plan, 'terraces', None) else None)

    def vertex(co):
        co = (round(co[0], 8), round(co[1], 8), round(co[2], 8))
        if co not in ids:
            ids[co] = len(vertices)
            vertices.append(co)
        return ids[co]

    def face(points, material):
        face_ids = list(dict.fromkeys(vertex(point) for point in points))
        if len(face_ids) >= 3:
            faces.append(tuple(face_ids))
            materials.append(material)

    def emit(polygon, material, height):
        polygon = _clean(polygon)
        if len(polygon) < 3:
            return
        if surface is None:
            top = [(x, y, height(x, y) if material in (1, 3) else 0.0)
                   for x, y, _ in polygon]
            base = [0.0] * len(top)
        else:
            # On terrain everything rides on the road-level surface.
            base = [surface(x, y) for x, y, _ in polygon]
            top = [(x, y, z + (height(x, y) if material in (1, 3) else 0.0))
                   for (x, y, _), z in zip(polygon, base)]
        for index in range(1, len(top) - 1):
            face((top[0], top[index], top[index + 1]), material)
        if material not in (1, 3):
            return
        # Curbs: iso-edges of the footway polygon. Both sides share these
        # vertices, so the skirt closes the surface without cracks. An iso edge
        # that runs exactly along a sample grid line would otherwise be emitted
        # once per adjacent cell, so each curb is keyed and emitted once.
        for index, current in enumerate(polygon):
            following = polygon[(index + 1) % len(polygon)]
            a, b = top[index], top[(index + 1) % len(top)]
            za, zb = base[index], base[(index + 1) % len(top)]
            if current[2] <= 1e-9 and following[2] <= 1e-9:
                bottom = 0.0
            elif current[2] >= walk - 1e-9 and following[2] >= walk - 1e-9:
                bottom = CURB_BOTTOM
            else:
                continue
            if bottom == 0.0 and a[2] - za <= 1e-9 and b[2] - zb <= 1e-9:
                continue
            if bottom == CURB_BOTTOM and walled is not None and max(
                    abs(a[0]), abs(a[1]), abs(b[0]), abs(b[1])) < walled - 1e-6:
                continue
            key = (tuple(sorted((vertex(b), vertex(a)))), bottom)
            if key in curbs:
                continue
            curbs.add(key)
            if surface is not None and bottom != 0.0:
                bottom = CURB_BOTTOM_TERRAIN
            face(((b[0], b[1], b[2]), (a[0], a[1], a[2]),
                  (a[0], a[1], za + bottom if surface is not None else bottom),
                  (b[0], b[1], zb + bottom if surface is not None else bottom)), 2)

    outers = outer_roads(plan)
    mouths = _ramp_mouths(plan)
    for i, j in sorted(field.active_cells()):
        x0, y0 = i * SAMPLE, j * SAMPLE
        if any(outer.drops(x0, y0) for outer in outers):
            continue
        if any(mouth(x0, y0) for mouth in mouths):
            continue
        corners = ((x0, y0, field.value(x0, y0)),
                   (x0 + SAMPLE, y0, field.value(x0 + SAMPLE, y0)),
                   (x0 + SAMPLE, y0 + SAMPLE, field.value(x0 + SAMPLE, y0 + SAMPLE)),
                   (x0, y0 + SAMPLE, field.value(x0, y0 + SAMPLE)))
        for polygon in _cell_triangles(corners, field, walk):
            emit(_clip(polygon, 0.0, True), 0, None)
            footway = _clip(_clip(polygon, walk, True), 0.0, False)
            rural = footway and section.rural_at(sum(p[0] for p in footway) / len(footway),
                                                 sum(p[1] for p in footway) / len(footway))
            emit(footway, 3 if rural else 1, section.pavement)
    return vertices, faces, materials


def _ramp_mouths(plan):
    """For each raised highway ramp, a test for the street-mesh cells just
    past its foot (the column of cells on its band beyond the foot line): the
    ramp's deck carries the road on from there. Further out the field is
    open ground anyway, and any street crossing under the ramp keeps its own."""
    freeway = getattr(plan, 'freeway', None) or {}
    band = freeway.get('ramp_half', 0.0) + plan.settings.sidewalk_width + SAMPLE
    tests = []
    for ramp in freeway.get('ramps', ()):
        foot, sign, y = ramp['foot'], ramp['reach'], ramp['y']
        start = foot if sign > 0 else foot - SAMPLE

        def past(x0, y0, start=start, y=y):
            return abs(x0 - start) < 1e-6 and y - band <= y0 + SAMPLE / 2 <= y + band
        tests.append(past)
    return tests


def build_ground_mesh(plan):
    """Unpaved terrain under and around the city, out to the wasteland edge."""
    if getattr(plan, 'terraces', None):
        return _terraced_ground(plan)[0]
    if getattr(plan, 'heights', None):
        return _terrain_ground_mesh(plan)
    settings = plan.settings
    extent = settings.radius * settings.block_size + 20
    far = extent + settings.wasteland
    covered = Field(plan).covered_cells()
    vertices, faces, ids = [], [], {}

    def vertex(x, y, depth=0.0, capped=True):
        co = (round(x, 8), round(y, 8), round(GROUND_Z - depth, 8) if depth else GROUND_Z)
        if co not in ids:
            ids[co] = len(vertices)
            vertices.append(co)
        return ids[co]

    faces += _city_ground(plan, extent, GROUND_CELL, covered, Field(plan), vertex)
    if settings.wasteland > 0:
        # Flat framing quads far outside the detailed city ground; the game
        # keeps the player in with invisible walls while the horizon stays
        # open. Outer highways run through gaps cut in them.
        holes = []
        for outer in outer_roads(plan):
            a0 = max(extent, abs(outer.start)) * (1 if outer.sign > 0 else -1)
            holes.append(outer.rect(a0))
        for rect in ((-far, -far, -extent, far), (extent, -far, far, far),
                     (-extent, extent, extent, far), (-extent, -far, extent, -extent)):
            for x0, y0, x1, y1 in _subtract(rect, holes):
                faces.append((vertex(x0, y0), vertex(x1, y0), vertex(x1, y1), vertex(x0, y1)))
    return vertices, faces


def _terrain_ground_mesh(plan):
    """The graded ground (``Grading``) on a finer grid, and round it the wild
    land (on a coarser one, out to where it levels off); the far wasteland
    beyond stays level."""
    settings = plan.settings
    extent = settings.radius * settings.block_size + 20
    far = extent + settings.wasteland
    grading = Grading(plan)
    covered = grading.field.covered_cells()
    per = int(round(GROUND_CELL_TERRAIN / SAMPLE))
    vertices, faces, ids = [], [], {}
    cell = GROUND_CELL_TERRAIN
    # A cell that overlaps a pad keeps all four corners under the pad's top,
    # so no triangle across the pad's edge lifts the ground into the building.
    caps = {}
    for polygon, top in grading.pads:
        xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
        for i in range(math.floor(min(xs) / cell), math.floor(max(xs) / cell) + 1):
            for j in range(math.floor(min(ys) / cell), math.floor(max(ys) / cell) + 1):
                low = _pad_lowest(top, i * cell, j * cell, (i + 1) * cell, (j + 1) * cell)
                caps[i, j] = min(caps.get((i, j), math.inf), low)

    def vertex(x, y, z=None, depth=0.0, capped=True):
        # (A vertex sunk into a ditch is apart from one at the same place
        # beside it: a ditch ends at a culvert's headwall.)
        key = (round(x, 8), round(y, 8)) + (('ditch',) if depth > 0 else ())
        if key not in ids:
            if z is None:
                # Under the tops over every cell it touches.
                cap = min(caps.get((math.floor((x + dx) / cell), math.floor((y + dy) / cell)),
                                   math.inf) for dx in (-1e-7, 1e-7) for dy in (-1e-7, 1e-7))
                z = grading.ground(x, y, cap if capped else math.inf) - depth
            ids[key] = len(vertices)
            vertices.append(key[:2] + (round(z, 8),))
        return ids[key]

    faces += _city_ground(plan, extent, cell, covered, grading.field, vertex)
    edge_line = extent
    if grading.wild and settings.wasteland > 0:
        edge_line = (settings.radius + grading.wild) * settings.block_size
        # Wild cells about a quarter block, a whole number of city cells (so
        # their corners on the seam are the city ground's vertices); city
        # cells along the outer roads, for their cuttings and embankments.
        coarse = cell * max(1, round(settings.block_size / 4 / cell))
        reach = coarse * math.ceil(OUTER_CORRIDOR / coarse - 1e-9)
        strips = []
        for outer in grading.outers:
            a0, a1 = sorted((outer.sign * extent, outer.sign * edge_line))
            b0, b1 = outer.centre - reach, outer.centre + reach
            strips.append((a0, b0, a1, b1) if outer.axis == 0 else (b0, a0, b1, a1))
        faces += _wild_ring(extent, edge_line, coarse, cell, vertex,
                            lambda x, y: grading.ground(x, y), strips)
    if settings.wasteland > 0:
        holes = []
        for outer in outer_roads(plan):
            a0 = max(edge_line, abs(outer.start)) * (1 if outer.sign > 0 else -1)
            holes.append(outer.rect(a0))
        far = max(far, edge_line + 1.0)
        # The ground's vertices along its edge: the framing is cut into long
        # quads there (a vertex in the middle of a quad's side leaves
        # pinholes).
        rim = defaultdict(set)
        for x, y, _ in vertices:
            for axis, (a, b) in enumerate(((x, y), (y, x))):
                if abs(abs(a) - edge_line) < 1e-6 and abs(b) < edge_line + 1e-6:
                    rim[axis, a > 0].add(round(b, 8))
        for rect, axis, positive in (((-far, -far, -edge_line, far), 0, False),
                                     ((edge_line, -far, far, far), 0, True),
                                     ((-edge_line, edge_line, edge_line, far), 1, True),
                                     ((-edge_line, -far, edge_line, -edge_line), 1, False)):
            # The city's (or the wild land's) edge is level (the surface is
            # zero off the lattice), so the framing quads meet it flush.
            lo, hi = (rect[1], rect[3]) if axis == 0 else (rect[0], rect[2])
            cuts = sorted({lo, hi} | rim[axis, positive])
            for a, b in zip(cuts, cuts[1:]):
                piece = ((rect[0], a, rect[2], b) if axis == 0 else (a, rect[1], b, rect[3]))
                for x0, y0, x1, y1 in _subtract(piece, holes):
                    faces.append(tuple(vertex(x, y, GROUND_Z_TERRAIN)
                                       for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))))
    return vertices, faces


def _wild_ring(inner, outer, coarse, fine, vertex, height, strips=()):
    """Faces of the ground between the squares of half-sides ``inner`` and
    ``outer``: on a ``coarse`` grid (a multiple of the ``fine`` one), but for
    ``strips`` (rectangles on the coarse grid's lines) on the fine one. A
    coarse piece along the inner square or a strip takes every fine vertex
    there, and every piece the corners of the pieces beside it, so they meet
    with no cracks (a piece with more than its corners is a fan round its
    middle)."""
    holes = [(-inner, -inner, inner, inner)] + list(strips)
    faces = []

    def side(a, b, fixed, axis):
        """Points strictly between a and b (either way) on a coarse piece's
        side (``axis`` 0: along x at y = ``fixed``): the holes' corners, and
        the fine grid's points where it runs along a hole's edge."""
        lo, hi = min(a, b), max(a, b)
        found = set()
        for hole in holes:
            c0, c1 = (hole[0], hole[2]) if axis == 0 else (hole[1], hole[3])
            e0, e1 = (hole[1], hole[3]) if axis == 0 else (hole[0], hole[2])
            found.update(v for v in (c0, c1) if lo + 1e-6 < v < hi - 1e-6)
            if min(abs(fixed - e0), abs(fixed - e1)) < 1e-6:
                s0, s1 = max(lo, c0), min(hi, c1)
                found.update(k * fine for k in range(math.ceil(s0 / fine - 1e-9),
                                                     math.floor(s1 / fine + 1e-9) + 1)
                             if lo + 1e-6 < k * fine < hi - 1e-6)
        points = sorted(found)
        return points if a < b else points[::-1]
    n = math.ceil(outer / coarse - 1e-9)
    for i in range(-n, n):
        for j in range(-n, n):
            box = (max(-outer, i * coarse), max(-outer, j * coarse),
                   min(outer, (i + 1) * coarse), min(outer, (j + 1) * coarse))
            if box[2] - box[0] < 1e-6 or box[3] - box[1] < 1e-6:
                continue
            for x0, y0, x1, y1 in _subtract(box, holes):
                ring = [(x0, y0)]
                ring += [(x, y0) for x in side(x0, x1, y0, 0)]
                ring.append((x1, y0))
                ring += [(x1, y) for y in side(y0, y1, x1, 1)]
                ring.append((x1, y1))
                ring += [(x, y1) for x in side(x1, x0, y1, 0)]
                ring.append((x0, y1))
                ring += [(x0, y) for y in side(y1, y0, x0, 1)]
                ids = [vertex(x, y) for x, y in ring]
                if len(ids) == 4:
                    faces.append(tuple(ids))
                    continue
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                middle = vertex(cx, cy, height(cx, cy))
                faces += [(middle, a, b) for a, b in zip(ids, ids[1:] + ids[:1])]
    for sx0, sy0, sx1, sy1 in strips:
        for i in range(math.floor(sx0 / fine), math.ceil(sx1 / fine)):
            for j in range(math.floor(sy0 / fine), math.ceil(sy1 / fine)):
                x0, y0 = max(sx0, i * fine), max(sy0, j * fine)
                x1, y1 = min(sx1, (i + 1) * fine), min(sy1, (j + 1) * fine)
                if x1 - x0 > 1e-6 and y1 - y0 > 1e-6:
                    faces.append((vertex(x0, y0), vertex(x1, y0), vertex(x1, y1), vertex(x0, y1)))
    return faces


def build_wall_mesh(plan):
    """Retaining walls of a terraced city: along the terraces' edges, and
    wherever the ground meets a footway or a stair at another height (a ramp
    on its embankment, a street at a terrace's foot)."""
    if not getattr(plan, 'terraces', None):
        return [], []
    return _terraced_ground(plan)[1]


def _halfplane(polygon, axis, value, keep_below):
    """Clip a convex polygon of (x, y, field) points at x or y = ``value``."""
    result = []
    for index, current in enumerate(polygon):
        following = polygon[(index + 1) % len(polygon)]
        inside = current[axis] <= value if keep_below else current[axis] >= value
        next_inside = following[axis] <= value if keep_below else following[axis] >= value
        if inside:
            result.append(current)
        if inside != next_inside:
            factor = (value - current[axis]) / (following[axis] - current[axis])
            point = [current[k] + (following[k] - current[k]) * factor for k in range(3)]
            point[axis] = value
            result.append(tuple(point))
    return result


def _terraced_ground(plan):
    """Ground and retaining walls of a terraced city, built together so the
    walls use the ground's own edge vertices.

    Near the streets the ground is cut at the footways' outer edge on the
    street mesh's sample grid (so it shares those vertices' positions) and
    round each stair; elsewhere it is a coarser grid, whose cells take the
    finer grid's vertices along their shared sides (no T-junctions). The
    ground splits along the terraces' edges into one sheet per level.

    A verge WALL_GAP wide runs beside every footway at its level: ground
    much higher than the footway stands behind a wall at the verge's far
    edge, never at the footway itself. Walls dropping more than PARAPET[0]
    carry a parapet on their upper side.
    Returns ((vertices, faces), (wall vertices, wall faces)).
    """
    cached = plan.__dict__.get('_terraced_ground')
    if cached is not None:
        return cached
    settings = plan.settings
    walk = settings.sidewalk_width
    verge = walk + WALL_GAP
    extent = settings.radius * settings.block_size + 20
    far = extent + settings.wasteland
    grading = Grading(plan)
    field = grading.field
    cell = 2 * SAMPLE
    FAR = 1e9            # Field value of the coarse cells, far from any street.
    reach = math.ceil((WALL_GAP + SAMPLE) / cell)
    active = {(i // 2, j // 2) for i, j in field.active_cells()}
    fine = {(i + di, j + dj) for i, j in active
            for di in range(-reach, reach + 1) for dj in range(-reach, reach + 1)}
    radius = settings.radius
    lines = {round(grading.line(k), 8) for k in range(-radius, radius + 1)}
    middles = {v for v in lines if round(v / SAMPLE) % 2}
    caps = defaultdict(list)
    for polygon, top in grading.pads:
        xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
        level = grading.level_at(sum(xs) / len(xs), sum(ys) / len(ys))
        for i in range(math.floor(min(xs) / cell), math.floor(max(xs) / cell) + 1):
            for j in range(math.floor(min(ys) / cell), math.floor(max(ys) / cell) + 1):
                low = _pad_lowest(top, i * cell, j * cell, (i + 1) * cell, (j + 1) * cell)
                if low < math.inf:
                    caps[i, j].append((low, level))
    vertices, faces, ids = [], [], {}
    iso_edges, verge_edges, line_edges = [], defaultdict(list), defaultdict(list)

    def cap_at(x, y, level):
        cells = {(math.floor((x + dx) / cell), math.floor((y + dy) / cell))
                 for dx in (-1e-7, 1e-7) for dy in (-1e-7, 1e-7)}
        return min((top for c in cells for top, pad in caps.get(c, ()) if pad == level),
                   default=math.inf)

    def paving(point):
        """Just under the road over a point beneath a street's own paving
        (where the ground runs on under a viaduct), else None."""
        x, y = point[0], point[1]
        if grading.streets.value(x, y) < walk - .25 and grading.stair_at(x, y) is None:
            return grading.paved(x, y) - ABUTMENT_DROP
        return None

    def decked(point):
        """How high a wall may stand under a raised highway's deck there."""
        return grading.under_decks(point[0], point[1], False)

    def strip_height(x, y, f, natural):
        """The verge between a footway and the ground beyond it."""
        if grading.stair_at(x, y) is not None:
            return natural
        low = min(natural, grading.wall_foot(x, y) - CURB_DROP)
        rise = natural - low
        retained = (0.0 if rise <= RETAIN[0] else rise if rise >= RETAIN[1] else
                    (rise - RETAIN[0]) / (RETAIN[1] - RETAIN[0]) * RETAIN[1])
        share = max(0.0, min(1.0, (f - walk) / WALL_GAP))
        return low + (rise - retained) * share

    def vertex(x, y, level, part, f, z=None):
        key = (round(x, 8), round(y, 8), level, part)
        if key not in ids:
            if z is None:
                z = grading.ground(x, y, cap_at(x, y, level), level)
                if part == 'verge':
                    z = strip_height(x, y, f, z)
                # Under a viaduct's start the ground stays beneath its road.
                road = paving((x, y))
                if road is not None:
                    z = min(z, road)
            ids[key] = len(vertices)
            vertices.append((key[0], key[1], round(z, 8)))
        return ids[key]

    def z_of(point, level, part):
        return vertices[ids[(round(point[0], 8), round(point[1], 8), level, part)]][2]

    def on_line(a, b):
        for axis in (0, 1):
            value = round(a[axis], 8)
            if value == round(b[axis], 8) and value in lines:
                return axis, value
        return None

    def emit(polygon, part):
        polygon = _clean(polygon) if polygon else polygon
        for axis in (0, 1):
            polygon = _halfplane(polygon, axis, -extent, False) if polygon else polygon
            polygon = _halfplane(polygon, axis, extent, True) if polygon else polygon
        polygon = _clean(polygon) if polygon else polygon
        if not polygon or len(polygon) < 3:
            return
        cx = sum(p[0] for p in polygon) / len(polygon)
        cy = sum(p[1] for p in polygon) / len(polygon)
        level = grading.level_at(cx, cy)
        face_ids = list(dict.fromkeys(vertex(x, y, level, part, f) for x, y, f in polygon))
        if len(face_ids) < 3:
            return
        faces.append(tuple(face_ids))
        for index, a in enumerate(polygon):
            b = polygon[(index + 1) % len(polygon)]
            if part == 'verge' and abs(a[2] - walk) <= 1e-6 and abs(b[2] - walk) <= 1e-6:
                iso_edges.append((a, b, level))
            if abs(a[2] - verge) <= 1e-6 and abs(b[2] - verge) <= 1e-6:
                verge_edges[tuple(sorted(((round(a[0], 6), round(a[1], 6)),
                                          (round(b[0], 6), round(b[1], 6)))))].append(
                    (level, part, a, b))
            line = on_line(a, b)
            if line is not None:
                along = 1 - line[0]
                span = tuple(sorted((round(a[along], 8), round(b[along], 8))))
                line_edges[line + span].append((level, part, a, b))

    count = math.ceil(extent / cell)
    for i in range(-count, count):
        for j in range(-count, count):
            if (i, j) in fine:
                for fi in (2 * i, 2 * i + 1):
                    for fj in (2 * j, 2 * j + 1):
                        x0, y0 = fi * SAMPLE, fj * SAMPLE
                        corners = ((x0, y0, field.value(x0, y0)),
                                   (x0 + SAMPLE, y0, field.value(x0 + SAMPLE, y0)),
                                   (x0 + SAMPLE, y0 + SAMPLE,
                                    field.value(x0 + SAMPLE, y0 + SAMPLE)),
                                   (x0, y0 + SAMPLE, field.value(x0, y0 + SAMPLE)))
                        if all(c[2] <= walk for c in corners):
                            continue
                        for triangle in _cell_triangles(corners, field, walk):
                            ground = _clip(triangle, walk, False)
                            emit(_clip(ground, verge, True), 'verge')
                            emit(_clip(ground, verge, False), 'ground')
                continue
            x0, y0 = i * cell, j * cell
            x1, y1, xm, ym = x0 + cell, y0 + cell, x0 + SAMPLE, y0 + SAMPLE
            split_x, split_y = round(xm, 8) in middles, round(ym, 8) in middles
            polygon = [(x0, y0, FAR)]
            if (i, j - 1) in fine or split_x:
                polygon.append((xm, y0, FAR))
            polygon.append((x1, y0, FAR))
            if (i + 1, j) in fine or split_y:
                polygon.append((x1, ym, FAR))
            polygon.append((x1, y1, FAR))
            if (i, j + 1) in fine or split_x:
                polygon.append((xm, y1, FAR))
            polygon.append((x0, y1, FAR))
            if (i - 1, j) in fine or split_y:
                polygon.append((x0, ym, FAR))
            pieces = [polygon]
            if split_x:
                pieces = [_halfplane(q, 0, xm, keep) for q in pieces for keep in (True, False)]
            if split_y:
                pieces = [_halfplane(q, 1, ym, keep) for q in pieces for keep in (True, False)]
            for piece in pieces:
                emit(piece, 'ground')

    walls, wall_faces, wall_ids = [], [], {}

    def wall_vertex(co):
        co = (round(co[0], 8), round(co[1], 8), round(co[2], 8))
        if co not in wall_ids:
            wall_ids[co] = len(walls)
            walls.append(co)
        return wall_ids[co]

    def solid(points):
        """A closed box from four base corners and their tops (8 points)."""
        bottom, top = points[:4], points[4:]
        area = sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(bottom, bottom[1:] + bottom[:1]))
        if area < 0:
            bottom, top = bottom[::-1], top[::-1]
        ids = [wall_vertex(p) for p in bottom + top]
        for face in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6),
                     (3, 0, 4, 7)):
            wall_faces.append(tuple(ids[k] for k in face))

    def wall(a, b, a_low, a_high, b_low, b_high, toward_left, parapet=True):
        """A wall over edge a-b of a ground sheet between two height profiles,
        facing the sheet's side (left of a-b) or the other, with a parapet on
        its upper side where it drops far enough."""
        da, db = a_high - a_low, b_high - b_low
        if abs(da) < 1e-6 and abs(db) < 1e-6:
            return
        if da < -1e-9 or db < -1e-9:
            if da * db < 0:
                # The profiles cross: two triangles either side.
                t = da / (da - db)
                m = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                zm = a_low + (b_low - a_low) * t
                wall(a, m, a_low, a_high, zm, zm, toward_left, False)
                wall(m, b, zm, zm, b_low, b_high, toward_left, False)
                return
            a_low, a_high, b_low, b_high = a_high, a_low, b_high, b_low
            toward_left = not toward_left
        points = [(a[0], a[1], a_high), (b[0], b[1], b_high), (b[0], b[1], b_low),
                  (a[0], a[1], a_low)]
        if not toward_left:
            points = [points[1], points[0], points[3], points[2]]
        face_ids = list(dict.fromkeys(wall_vertex(point) for point in points))
        if len(face_ids) >= 3:
            wall_faces.append(tuple(face_ids))
        length = math.dist(a[:2], b[:2])
        if parapet and length > 1e-6 and min(a_high - a_low, b_high - b_low) >= PARAPET[0]:
            # Behind the face, on the upper side.
            ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
            side = -1 if toward_left else 1
            ox, oy = -uy * side * PARAPET[1], ux * side * PARAPET[1]
            base = [(a[0], a[1], a_high), (b[0], b[1], b_high),
                    (b[0] + ox, b[1] + oy, b_high), (a[0] + ox, a[1] + oy, a_high)]
            solid(base + [(x, y, z + PARAPET[2]) for x, y, z in base])

    def under_road(a, b, a_low, a_high, b_low, b_high, toward_left):
        """A wall that stops just beneath the road where it runs under a
        street's paving (a viaduct's abutment), with no parapet there."""
        cap_a, cap_b = paving(a), paving(b)
        deck_a, deck_b = decked(a), decked(b)
        cap_a = min(deck_a, cap_a if cap_a is not None else math.inf)
        cap_b = min(deck_b, cap_b if cap_b is not None else math.inf)
        if cap_a < math.inf:
            a_low, a_high = min(a_low, cap_a), min(a_high, cap_a)
        if cap_b < math.inf:
            b_low, b_high = min(b_low, cap_b), min(b_high, cap_b)
        wall(a, b, a_low, a_high, b_low, b_high, toward_left,
             cap_a == math.inf and cap_b == math.inf)

    # Verge against the paving: the wall (a curb's face, or an embankment's
    # side) faces the street where the verge is higher, the verge where the
    # paving is.
    def foot(point):
        # Under a street's own paving (a viaduct's abutment) the wall stops
        # just beneath it, so nothing stands proud of the road.
        road = paving(point)
        if road is not None:
            return road, True
        return grading.wall_foot(point[0], point[1]), False
    for a, b, level in iso_edges:
        (fa, under_a), (fb, under_b) = foot(a), foot(b)
        za, zb = z_of(a, level, 'verge'), z_of(b, level, 'verge')
        # (Under a raised highway's deck it stops beneath the road too.)
        deck_a, deck_b = decked(a), decked(b)
        fa, za, fb, zb = min(fa, deck_a), min(za, deck_a), min(fb, deck_b), min(zb, deck_b)
        wall(a, b, fa, za, fb, zb, False,
             not (under_a or under_b) and deck_a == math.inf and deck_b == math.inf)
    # Verge against the ground beyond it: the retaining wall.
    for key in sorted(verge_edges):
        entries = verge_edges[key]
        strip = [e for e in entries if e[1] == 'verge']
        ground = [e for e in entries if e[1] == 'ground']
        if not strip or not ground:
            continue
        level, _, a, b = strip[0]
        other = ground[0][0]
        under_road(a, b, z_of(a, level, 'verge'), z_of(a, other, 'ground'),
                   z_of(b, level, 'verge'), z_of(b, other, 'ground'), True)
    # Ground against ground along a terrace's edge, facing the lower side.
    for key in sorted(line_edges):
        entries = line_edges[key]
        if len({(level, part) for level, part, _, _ in entries}) < 2:
            continue
        (level, part, a, b), (other, other_part, _, _) = entries[0], entries[1]
        under_road(a, b, z_of(a, level, part), z_of(a, other, other_part),
                   z_of(b, level, part), z_of(b, other, other_part), True)

    # The wild land round the city, out to where it levels off: its own
    # facets (each block two triangles), outside the city ground.
    wild = grading.wild
    edge_line = grading.line(radius + wild) if wild else extent
    if wild and settings.wasteland > 0:
        for i in range(-radius - wild, radius + wild):
            for j in range(-radius - wild, radius + wild):
                x0, x1 = grading.line(i), grading.line(i + 1)
                y0, y1 = grading.line(j), grading.line(j + 1)
                if max(abs(x0), abs(x1)) <= extent and max(abs(y0), abs(y1)) <= extent:
                    continue
                for triangle in ([(x0, y0, FAR), (x1, y0, FAR), (x1, y1, FAR)],
                                 [(x0, y0, FAR), (x1, y1, FAR), (x0, y1, FAR)]):
                    # Outside the city ground: four pieces round its square.
                    for piece in (_halfplane(triangle, 0, -extent, True),
                                  _halfplane(triangle, 0, extent, False),
                                  _halfplane(_halfplane(_halfplane(triangle, 0, -extent, False),
                                                        0, extent, True), 1, -extent, True),
                                  _halfplane(_halfplane(_halfplane(triangle, 0, -extent, False),
                                                        0, extent, True), 1, extent, False)):
                        piece = _clean(piece) if piece else piece
                        if piece and len(piece) >= 3:
                            face_ids = list(dict.fromkeys(
                                vertex(x, y, 0, 'wild', FAR,
                                       grading.natural(x, y, 0)) for x, y, _ in piece))
                            if len(face_ids) >= 3:
                                faces.append(tuple(face_ids))
    if settings.wasteland > 0:
        holes = []
        for outer in outer_roads(plan):
            a0 = max(edge_line, abs(outer.start)) * (1 if outer.sign > 0 else -1)
            holes.append(outer.rect(a0))
        far = max(far, edge_line + 1.0)
        for rect in ((-far, -far, -edge_line, far), (edge_line, -far, far, far),
                     (-edge_line, edge_line, edge_line, far),
                     (-edge_line, -far, edge_line, -edge_line)):
            for x0, y0, x1, y1 in _subtract(rect, holes):
                faces.append(tuple(vertex(x, y, 0, 'wild', FAR, GROUND_Z_TERRAIN)
                                   for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))))
    result = ((vertices, faces), (walls, wall_faces))
    plan.__dict__['_terraced_ground'] = result
    return result


def viaducts(plan, grading=None):
    """Each viaduct as built: its path, arc-length span, deck edges and piers.
    Returns [{'path', 'start', 'end', 'stations': [(along, centre, tangent,
    left top, right top, soffit)], 'piers': [(centre, tangent, foot, soffit)]}]."""
    if not getattr(plan, 'terraces', None):
        return []
    grading = grading or Grading(plan)
    walk = plan.settings.sidewalk_width
    found = []
    for path in plan.paths:
        for start, end in grading.spans.get(path['id'], ()):
            half = path['width'] / 2 + walk
            stations = []
            for along, (x, y), (tx, ty) in _walk_polyline(path['points'], 2.0):
                if start - 1e-6 <= along <= end + 1e-6:
                    nx, ny = -ty, tx
                    left, right = (x + nx * half, y + ny * half), (x - nx * half, y - ny * half)
                    stations.append((along, (x, y), (tx, ty),
                                     left + (grading.wall_foot(*left),),
                                     right + (grading.wall_foot(*right),),
                                     grading.surface(x, y) - DECK_DEPTH))
            if len(stations) < 2:
                continue
            length = end - start
            count = 1 if length < 2 * PIER_END else max(
                1, math.floor((length - 2 * PIER_END) / PIER_SPACING) + 1)
            spots = ([start + length / 2] if count == 1 else
                     [start + PIER_END + (length - 2 * PIER_END) * k / (count - 1)
                      for k in range(count)])
            # No pier in another street's paving (where a ramp leaves the
            # junction on a terrace's top): the next spot along that is clear.
            total = sum(math.dist(a, b) for a, b in zip(path['points'], path['points'][1:]))
            others = Field(plan, (), {path['id']: [(0.0, total)]})
            line = _walk_polyline(path['points'], 1.0)
            piers = []
            for spot in spots:
                clear = [item for item in line if start <= item[0] <= end and
                         others.value(*item[1]) >= walk + PIER_SIZE[1]]
                if not clear:
                    continue
                along, (x, y), (tx, ty) = min(clear, key=lambda item: abs(item[0] - spot))
                if abs(along - spot) > PIER_SPACING / 2:
                    continue
                nx, ny = -ty, tx
                foot = min(grading.natural(x + tx * a + nx * c, y + ty * a + ny * c)
                           for a in (-PIER_CAP[0] / 2, PIER_CAP[0] / 2)
                           for c in (-half, 0.0, half)) - .5
                piers.append(((x, y), (tx, ty), foot, grading.surface(x, y) - DECK_DEPTH))
            found.append({'path': path['id'], 'start': start, 'end': end, 'half': half,
                          'stations': stations, 'piers': piers})
    return found


def build_viaduct_mesh(plan):
    """Viaduct decks (soffit and fascias; each end meets a flat abutment),
    their parapets and piers with cap beams, for the stretches of ramp
    standing clear of the ground."""
    vertices, faces = [], []
    ids = {}

    def vertex(co):
        co = (round(co[0], 8), round(co[1], 8), round(co[2], 8))
        if co not in ids:
            ids[co] = len(vertices)
            vertices.append(co)
        return ids[co]

    def face(points, outward):
        face_ids = list(dict.fromkeys(vertex(p) for p in _oriented(points, outward)))
        if len(face_ids) >= 3:
            faces.append(tuple(face_ids))

    def box(centre, tangent, along, across, bottom, top):
        (x, y), (tx, ty) = centre, tangent
        nx, ny = -ty, tx
        base = [(x + tx * a + nx * c, y + ty * a + ny * c)
                for a, c in ((-along / 2, -across / 2), (along / 2, -across / 2),
                             (along / 2, across / 2), (-along / 2, across / 2))]
        offset = len(vertices)
        for z in (bottom, top):
            for px, py in base:
                vertices.append((round(px, 8), round(py, 8), round(z, 8)))
        faces.extend(tuple(offset + i for i in f) for f in
                     ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6),
                      (3, 0, 4, 7)))

    for viaduct in viaducts(plan):
        stations = viaduct['stations']
        for (_, c0, t0, l0, r0, s0), (_, c1, t1, l1, r1, s1) in zip(stations, stations[1:]):
            n0, n1 = (-t0[1], t0[0], 0.0), (-t1[1], t1[0], 0.0)
            normal = ((n0[0] + n1[0]) / 2, (n0[1] + n1[1]) / 2, 0.0)
            face([l0, l1, l1[:2] + (s1,), l0[:2] + (s0,)], normal)
            face([r0, r1, r1[:2] + (s1,), r0[:2] + (s0,)], tuple(-v for v in normal))
            face([l0[:2] + (s0,), l1[:2] + (s1,), r1[:2] + (s1,), r0[:2] + (s0,)],
                 (0.0, 0.0, -1.0))
            # Parapets on both edges, standing on the footway.
            for e0, e1, sign in ((l0, l1, -1), (r0, r1, 1)):
                o0 = (n0[0] * sign * PARAPET[1], n0[1] * sign * PARAPET[1])
                o1 = (n1[0] * sign * PARAPET[1], n1[1] * sign * PARAPET[1])
                base = [e0, e1, (e1[0] + o1[0], e1[1] + o1[1], e1[2]),
                        (e0[0] + o0[0], e0[1] + o0[1], e0[2])]
                top = [(x, y, z + PARAPET[2]) for x, y, z in base]
                area = sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(base, base[1:] + base[:1]))
                if area < 0:
                    base, top = base[::-1], top[::-1]
                offset = len(vertices)
                for x, y, z in base + top:
                    vertices.append((round(x, 8), round(y, 8), round(z, 8)))
                faces.extend(tuple(offset + i for i in f) for f in
                             ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                              (2, 3, 7, 6), (3, 0, 4, 7)))
        width = 2 * viaduct['half']
        for centre, tangent, foot, soffit in viaduct['piers']:
            box(centre, tangent, PIER_CAP[0], width - 1.0, soffit - PIER_CAP[1], soffit)
            box(centre, tangent, PIER_SIZE[0], min(PIER_SIZE[1], width / 3), foot,
                soffit - PIER_CAP[1])
    return vertices, faces


# A raised highway (``plan.freeway``): the mainline deck on hammerhead piers,
# with a median barrier, parapets and lane markings, and its ramps on single
# columns. Where a deck runs too near the ground for open space under it, it
# stands on solid fill between its fascias instead (an embankment).
FREEWAY_DEPTH = 1.6        # Mainline deck: top to soffit.
FREEWAY_RAMP_DEPTH = 1.1   # As city_plan's.
FREEWAY_OPEN = 1.0         # Least clear height under a soffit; lower is fill.
FREEWAY_PIERS = 30.0       # Mainline pier spacing (m); ramp piers half that.
FREEWAY_PIER = (2.0, 3.2)  # Column along the deck, across it.
FREEWAY_CAP = (2.4, 1.3)   # Cap beam along the deck, depth (it spans the deck).
FREEWAY_PIER_CLEAR = 2.5   # Piers keep this far from a street's footway.
FREEWAY_MEDIAN = (.6, .85)  # Median barrier width, height.
FREEWAY_MERGE = .3         # A ramp within this of the deck's level runs into it.
FREEWAY_LINE = .15         # Paint width.
FREEWAY_DASH = (3.0, 9.0)  # Lane dash, gap.
RAMP_TILT = 12.0           # A ramp's deck takes the street's cross-fall at its foot, level after this.
DECK_GROUND = .3           # The ground stays this far under a deck's top.
DECK_REACH = 12.0          # Beside a ramp the ground is cut back this far out.


def deck_profiles(plan):
    """The raised highway's decks as surfaces, for the mesh and for the
    ground under them: [(side, [(x, z top, inner |y|, outer |y|, cross-fall at
    the inner edge, at the outer)])], side 0 for the mainline, the stations
    in x order."""
    freeway = getattr(plan, 'freeway', None) or {}
    if not freeway:
        return []
    half, ramp_half = freeway['half'], freeway['ramp_half']
    decks = [(0, [(x, z, -half, half, 0.0, 0.0) for x, z in freeway['mainline']])]
    road = plan.surface()
    for ramp in freeway['ramps']:
        side = ramp['side']
        climb, taper = ramp['length'], ramp['taper']
        stations = []
        for x, y, z in ramp['points']:
            along = abs(x - ramp['foot'])
            width = 2 * ramp_half * max(0.0, min(1.0, (climb + taper - along) / taper))
            inner, outer = side * half, side * (half + width)
            # At its foot the deck takes the street's cross-fall (it meets
            # the road there edge to edge), levelling out over RAMP_TILT.
            share = max(0.0, 1.0 - along / RAMP_TILT)
            centre = road(x, y)
            stations.append((x, z, inner, outer) +
                            tuple((road(x, edge) - centre) * share for edge in (inner, outer)))
        decks.append((side, sorted(stations)))
    return decks


def _deck_cut(decks, x, y, beside=True):
    """How high the ground may stand at (x, y) under the decks: DECK_GROUND
    under one, and (``beside``) beside a ramp no higher than a cut slope back
    up from its edge (math.inf where no deck is near)."""
    best = math.inf
    for side, stations in decks:
        if not stations[0][0] <= x <= stations[-1][0]:
            continue
        k = max(0, min(len(stations) - 2, bisect.bisect_right([st[0] for st in stations], x) - 1))
        a, b = stations[k], stations[k + 1]
        t = (x - a[0]) / (b[0] - a[0]) if b[0] != a[0] else 0.0
        z, inner, outer, ti, to = (a[i] + (b[i] - a[i]) * t for i in range(1, 6))
        low, high = sorted((inner, outer))
        if abs(outer - inner) < 1e-6:
            continue
        if low <= y <= high:
            u = (y - inner) / (outer - inner)
            best = min(best, z + ti + (to - ti) * u - DECK_GROUND)
        elif side and beside:
            gap = low - y if y < low else y - high
            if gap < DECK_REACH:
                edge_z = z + (ti if abs((low if y < low else high) - inner) < 1e-6 else to)
                best = min(best, edge_z - DECK_GROUND + PAD_CUT_SLOPE * gap)
    return best


def _freeway_ground(plan):
    """Natural ground under a raised highway (at the surface it rides on)."""
    if getattr(plan, 'terraces', None):
        grading = Grading(plan)
        return lambda x, y: grading.natural(x, y)
    if getattr(plan, 'heights', None):
        surface = plan.surface()
        return lambda x, y: surface(x, y)
    return lambda x, y: 0.0


def freeway_stations(plan):
    """The raised highway as built: ('mainline' and each ramp) lists of
    stations (x, y centre, z top, inner edge |y|, outer edge |y|, bottom z,
    open), with open stations standing clear over the ground and the rest on
    fill. Returns {'mainline': [...], 'ramps': [[...]], 'piers': [(x, y, along,
    across, foot, cap bottom, cap top, cap across)]}."""
    freeway = getattr(plan, 'freeway', None) or {}
    if not freeway:
        return {}
    ground = _freeway_ground(plan)
    half, ramp_half = freeway['half'], freeway['ramp_half']
    walk = plan.settings.sidewalk_width
    size = plan.settings.block_size
    crossings = []
    for road in plan.roads:
        (ax, ay), (bx, by) = road.a, road.b
        if ax == bx and min(ay, by) <= 0 <= max(ay, by):
            crossings.append((ax * size, road.width / 2 + walk + FREEWAY_PIER_CLEAR))

    def under(x, y0, y1):
        samples = [ground(x, y0 + (y1 - y0) * k / 4) for k in range(5)]
        return min(samples), max(samples)
    mainline = []
    for x, z in freeway['mainline']:
        low, high = under(x, -half, half)
        bottom = z - FREEWAY_DEPTH
        open_ = bottom - high >= FREEWAY_OPEN
        # On fill (too near the ground to stand open) down into the ground,
        # which is cut back under the deck where it stood higher.
        mainline.append((x, 0.0, z, -half, half, bottom if open_ else min(low, z) - .5, open_,
                         0.0, 0.0))
    ramps = []
    profiles = deck_profiles(plan)[1:]
    for ramp, (side, profile) in zip(freeway['ramps'], profiles):
        # (The profile runs in x order; the stations run from the foot.)
        by_x = {round(st[0], 6): st for st in profile}
        stations = []
        for x, y, z in ramp['points']:
            _, _, inner, outer, ti, to = by_x[round(x, 6)]
            low, high = under(x, inner, side * (half + 2 * ramp_half))
            bottom = z - FREEWAY_RAMP_DEPTH
            open_ = bottom - high >= FREEWAY_OPEN
            stations.append((x, y, z, inner, outer, bottom if open_ else min(low, z) - .5, open_,
                             ti, to))
        ramps.append(stations)

    def clear_of_streets(x, reach):
        return all(abs(x - cx) >= clear + reach for cx, clear in crossings)
    piers = []

    def deck_at(stations, x):
        for a, b in zip(stations, stations[1:]):
            if a[0] <= x <= b[0] or b[0] <= x <= a[0]:
                t = (x - a[0]) / (b[0] - a[0]) if b[0] != a[0] else 0.0
                return a[2] + (b[2] - a[2]) * t, a[6] and b[6]
        return None, False
    # Mainline piers every FREEWAY_PIERS out from the middle both ways.
    xs = [st[0] for st in mainline]
    spots = []
    k = 0
    while True:
        moved = False
        for sign in ((1,) if k == 0 else (-1, 1)):
            x = sign * k * FREEWAY_PIERS
            if xs[0] < x < xs[-1]:
                spots.append(x)
                moved = True
        if not moved and k:
            break
        k += 1
    for x in sorted(spots):
        z, open_ = deck_at(mainline, x)
        if z is None or not open_:
            continue
        # Shift off a street under the deck (either way, the nearer free spot).
        for shift in (0.0, 3.0, -3.0, 6.0, -6.0, 9.0, -9.0, 12.0, -12.0):
            if clear_of_streets(x + shift, FREEWAY_CAP[0] / 2):
                break
        else:
            continue
        x += shift
        z, open_ = deck_at(mainline, x)
        if z is None or not open_:
            continue
        low, high = under(x, -half, half)
        soffit = z - FREEWAY_DEPTH
        if soffit - FREEWAY_CAP[1] - high < 2.0:
            continue
        piers.append((x, 0.0, FREEWAY_PIER[0], FREEWAY_PIER[1], min(
            ground(x + a, b) for a in (-1.0, 1.0) for b in (-2.0, 0.0, 2.0)) - .5,
            soffit - FREEWAY_CAP[1], soffit, 2 * half - 1.0))
    for ramp, stations in zip(freeway['ramps'], ramps):
        side = ramp['side']
        y = side * (half + ramp_half)
        start = ramp['foot']
        total = ramp['length'] + ramp['taper']
        count = max(1, int(total // (FREEWAY_PIERS / 2)))
        for j in range(1, count + 1):
            x = start + ramp['reach'] * total * j / (count + 1)
            if not clear_of_streets(x, 1.2):
                continue
            z, open_ = deck_at(stations, x)
            if z is None or not open_:
                continue
            soffit = z - FREEWAY_RAMP_DEPTH
            low, high = under(x, side * half, side * (half + 2 * ramp_half))
            if soffit - .8 - high < 2.0:
                continue
            # Under the narrowing lane, nearer the deck.
            width = 2 * ramp_half * max(0.0, min(1.0, (total - abs(x - start)) / ramp['taper']))
            if width < 4.0:
                continue
            centre = side * (half + width / 2)
            piers.append((x, centre, 1.4, 2.2, min(ground(x, centre + d) for d in (-1.5, 0.0, 1.5))
                          - .5, soffit - .8, soffit, width - 1.0))
    return {'mainline': mainline, 'ramps': ramps, 'piers': piers}


def build_freeway_mesh(plan):
    """Return vertices, faces, material indices (0 deck asphalt, 1 concrete)
    for a raised highway, or empty lists."""
    built = freeway_stations(plan)
    vertices, faces, materials = [], [], []
    if not built:
        return vertices, faces, materials
    ids = {}
    solid = [0]

    def vertex(co):
        # Each solid keeps its own vertices (parapets stand on the deck
        # without sharing its edges).
        co = (round(co[0], 8), round(co[1], 8), round(co[2], 8))
        key = (solid[0], co)
        if key not in ids:
            ids[key] = len(vertices)
            vertices.append(co)
        return ids[key]

    def face(points, material, outward):
        indices = list(dict.fromkeys(vertex(p) for p in _oriented(points, outward)))
        if len(indices) >= 3:
            faces.append(tuple(indices))
            materials.append(material)

    def box(x, y, along, across, bottom, top):
        solid[0] += 1
        corners = [(x - along / 2, y - across / 2), (x + along / 2, y - across / 2),
                   (x + along / 2, y + across / 2), (x - along / 2, y + across / 2)]
        for (ax, ay), (bx, by) in zip(corners, corners[1:] + corners[:1]):
            mx, my = (ax + bx) / 2 - x, (ay + by) / 2 - y
            face([(ax, ay, bottom), (bx, by, bottom), (bx, by, top), (ax, ay, top)], 1, (mx, my, 0.0))
        face([(cx, cy, top) for cx, cy in corners], 1, (0.0, 0.0, 1.0))
        face([(cx, cy, bottom) for cx, cy in corners], 1, (0.0, 0.0, -1.0))

    def strip(stations, inner, outer, low, high, material):
        """A closed solid band along ``stations`` between two lateral edges
        (functions of a station) and two heights (offsets from the top, or
        None for the station's bottom): its top in ``material``, the rest
        concrete."""
        def level(st, offset, y):
            if offset is None:
                return st[5]
            # The station's cross-fall, from its inner to its outer edge.
            span = st[4] - st[3]
            t = (y - st[3]) / span if abs(span) > 1e-9 else 0.0
            return st[2] + offset + st[7] + (st[8] - st[7]) * t
        solid[0] += 1
        for a, b in zip(stations, stations[1:]):
            ia, ib, oa, ob = inner(a), inner(b), outer(a), outer(b)
            if abs(ia - oa) < 1e-6 and abs(ib - ob) < 1e-6:
                continue
            face([(a[0], ia, level(a, high, ia)), (b[0], ib, level(b, high, ib)),
                  (b[0], ob, level(b, high, ob)), (a[0], oa, level(a, high, oa))], material,
                 (0.0, 0.0, 1.0))
            face([(a[0], ia, level(a, low, ia)), (b[0], ib, level(b, low, ib)),
                  (b[0], ob, level(b, low, ob)), (a[0], oa, level(a, low, oa))], 1,
                 (0.0, 0.0, -1.0))
            for (ea, eb), sign in (((ia, ib), -1.0), ((oa, ob), 1.0)):
                side = sign * (1.0 if oa > ia else -1.0)
                face([(a[0], ea, level(a, low, ea)), (b[0], eb, level(b, low, eb)),
                      (b[0], eb, level(b, high, eb)), (a[0], ea, level(a, high, ea))], 1,
                     (0.0, side, 0.0))
        for st, sign in ((stations[0], -1.0), (stations[-1], 1.0)):
            direction = sign * (1.0 if stations[-1][0] > stations[0][0] else -1.0)
            i, o = inner(st), outer(st)
            face([(st[0], i, level(st, low, i)), (st[0], o, level(st, low, o)),
                  (st[0], o, level(st, high, o)), (st[0], i, level(st, high, i))], 1,
                 (direction, 0.0, 0.0))

    def runs(stations, keep):
        """Consecutive stretches of stations whose segments all pass ``keep``."""
        found, current = [], []
        for a, b in zip(stations, stations[1:]):
            if keep(a, b):
                current = current or [a]
                current.append(b)
            elif current:
                found.append(current)
                current = []
        if current:
            found.append(current)
        return found

    mainline, ramps = built['mainline'], built['ramps']
    freeway = plan.freeway
    half = freeway['half']
    # Mainline: deck (asphalt top; fascias and soffit or fill in concrete).
    strip(mainline, lambda st: -half, lambda st: half, None, 0.0, 0)
    # Where a ramp runs level with the deck, no parapet between them.
    merged = {-1: [], 1: []}
    for ramp, stations in zip(freeway['ramps'], ramps):
        for st in stations:
            near = min(mainline, key=lambda m: abs(m[0] - st[0]))
            if abs(near[2] - st[2]) <= FREEWAY_MERGE and abs(st[4]) > abs(st[3]) + 1e-6:
                merged[ramp['side']].append(st[0])
    for side in (-1, 1):
        spans = sorted(merged[side])

        def free(a, b, spans=spans):
            lo, hi = sorted((a[0], b[0]))
            return not any(lo - 4.0 <= x <= hi + 4.0 for x in spans)
        for run in runs(mainline, free):
            inner = side * (half - PARAPET[1])
            strip(run, lambda st, v=inner: v, lambda st, v=side * half: v, 0.0, PARAPET[2], 1)
    strip(mainline, lambda st: -FREEWAY_MEDIAN[0] / 2, lambda st: FREEWAY_MEDIAN[0] / 2,
          0.0, FREEWAY_MEDIAN[1], 1)
    # Ramps: deck, then a parapet along the outer edge where it stands up.
    ground = _freeway_ground(plan)
    for ramp, stations in zip(freeway['ramps'], ramps):
        side = ramp['side']
        inset = side * .05
        strip(stations, lambda st: st[3] + inset, lambda st: st[4], None, 0.0, 0)
        high = runs(stations, lambda a, b: min(a[2] - ground(a[0], a[4]), b[2] - ground(b[0], b[4]))
                    > .8 and abs(a[4] - a[3]) > PARAPET[1] + .05)
        for run in high:
            strip(run, lambda st: st[4] - side * PARAPET[1], lambda st: st[4], 0.0, PARAPET[2], 1)
    for x, y, along, across, foot, cap_bottom, cap_top, cap_across in built['piers']:
        box(x, y, along, across, foot, cap_bottom)
        box(x, y, FREEWAY_CAP[0], cap_across, cap_bottom, cap_top)
    # Where a ramp leaves the street its footways end (the road runs on):
    # a curb across each footway's end.
    surface, nodes = plan.surface(), flush_junctions(plan)
    walk = plan.settings.sidewalk_width
    for ramp in freeway['ramps']:
        x, sign = ramp['foot'], ramp['reach']
        for lateral in (-1, 1):
            y0 = ramp['y'] + lateral * freeway['ramp_half']
            y1 = y0 + lateral * walk
            top = max(surface(x, y) + pavement_height(plan, x, y, nodes) for y in (y0, y1))
            low = min(surface(x, y) for y in (y0, y1)) - .3
            solid[0] += 1
            corners = [(x, y0), (x + sign * .15, y0), (x + sign * .15, y1), (x, y1)]
            for (ax, ay), (bx, by) in zip(corners, corners[1:] + corners[:1]):
                mx, my = (ax + bx) / 2 - (x + sign * .075), (ay + by) / 2 - (y0 + y1) / 2
                face([(ax, ay, low), (bx, by, low), (bx, by, top), (ax, ay, top)], 1, (mx, my, 0.0))
            face([(cx, cy, top) for cx, cy in corners], 1, (0.0, 0.0, 1.0))
            face([(cx, cy, low) for cx, cy in corners], 1, (0.0, 0.0, -1.0))
    return vertices, faces, materials


def freeway_markings(plan):
    """Lane paint on a raised highway's deck: quads (four xyz points) for
    the solid edge and median lines and the dashed lane lines."""
    freeway = getattr(plan, 'freeway', None) or {}
    if not freeway:
        return []
    mainline = [(x, 0.0, z) for x, z in freeway['mainline']]
    edge_line = freeway['half'] - 2.5
    quads = []

    def quad(x0, x1, y):
        z0, z1 = _interpolate(mainline, x0) + .004, _interpolate(mainline, x1) + .004
        w = FREEWAY_LINE / 2
        quads.append([(x0, y - w, z0), (x1, y - w, z1), (x1, y + w, z1), (x0, y + w, z0)])
    for y in (-edge_line, edge_line, -FREEWAY_MEDIAN[0] / 2 - .4, FREEWAY_MEDIAN[0] / 2 + .4):
        for (x0, _, _), (x1, _, _) in zip(mainline, mainline[1:]):
            quad(x0, x1, y)
    dash, gap = FREEWAY_DASH
    lane = (edge_line + FREEWAY_MEDIAN[0] / 2 + .4) / 2
    for y in (-lane, lane):
        x = math.ceil(mainline[0][0] / (dash + gap)) * (dash + gap)
        while x + dash < mainline[-1][0]:
            quad(x, x + dash, y)
            x += dash + gap
    return quads


def _interpolate(stations, x):
    """Deck top at ``x`` along a run of stations."""
    for a, b in zip(stations, stations[1:]):
        if a[0] <= x <= b[0]:
            t = (x - a[0]) / (b[0] - a[0]) if b[0] != a[0] else 0.0
            return a[2] + (b[2] - a[2]) * t
    return stations[0][2] if x < stations[0][0] else stations[-1][2]


def footprint(center, width, depth, rotation):
    """World corners (counter-clockwise) of a pad: width along its front."""
    c, s = math.cos(rotation), math.sin(rotation)
    return [(center[0] + x * c - y * s, center[1] + x * s + y * c)
            for x, y in ((-width / 2, -depth / 2), (width / 2, -depth / 2),
                         (width / 2, depth / 2), (-width / 2, depth / 2))]


def _polygon_distance(polygon, x, y):
    """Distance from (x, y) to a convex counter-clockwise polygon (0 inside)."""
    inside = True
    best = math.inf
    for (ax, ay), (bx, by) in zip(polygon, polygon[1:] + polygon[:1]):
        if (bx - ax) * (y - ay) - (by - ay) * (x - ax) < 0:
            inside = False
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(x - ax - dx * t, y - ay - dy * t))
    return 0.0 if inside else best


class Grading:
    """The graded ground of a terrain city: the natural ground, cut back round
    every building and site pad (the ground stays under the pad's top and
    rises from it no steeper than PAD_CUT_SLOPE) and, on hills, held up to the
    curbs' skirts along every footway. Heights are relative to the city origin.

    On terraces the natural ground is the base hills plus the rise of the
    terrace a point is on, falling away across a terrace's slope; the
    terraces' edges are snapped to the ground's sample grid (``line``), where
    the retaining walls stand. Each point belongs to a ``level`` (0 off the
    terraces, then a terrace's top and its slope). A pad shapes only the
    ground on its own level; stairs are holes in the ground, and the ground
    runs on under the viaducts (``spans``: {path id: arc-length intervals}).
    """

    def __init__(self, plan):
        settings = plan.settings
        self.surface = plan.surface()
        self.offset = GROUND_Z_TERRAIN if plan.heights else GROUND_Z
        self.walk = settings.sidewalk_width
        self.size = settings.block_size
        self.terraces = getattr(plan, 'terraces', None) or {}
        self.plan = plan
        self.nodes = flush_junctions(plan)
        self.streets = Field(plan)
        self.field = self.streets
        self.stairs, self.spans = [], {}
        self.wild = getattr(plan, 'wild', 0) if plan.heights else 0
        # On hills the outer roads run through the wild land on their own
        # level (a terraced city's along its valley floor).
        self.outers = outer_roads(plan) if self.wild and not self.terraces else []
        if self.terraces:
            self.wild = self.terraces.get('wild', 0)
            self.base = _Facets(settings.radius + self.wild,
                                {(x, y): z for x, y, z in self.terraces.get('ground', ())},
                                self.line, self._index)
            # Levels: 0 off the terraces; a terrace's top, and each of its
            # slopes and corners (sheets meeting where they agree, and
            # walled where they do not).
            self.levels, self.tops, self.slopes = {}, {}, {}
            for index, region in enumerate(self.terraces['regions']):
                top = ('top', index)
                self.tops[top] = region['step']
                for c in region['cells']:
                    self.levels[tuple(c)] = top
                rises = _slope_rises(region, self.line)
                parts = ([('slope', index, k, s['cells']) for k, s in
                          enumerate(region.get('slopes', ()))] +
                         [('corner', index, k, [c['cell']]) for k, c in
                          enumerate(region.get('corners', ()))])
                for kind, i, k, cells in parts:
                    level = (kind, i, k)
                    self.slopes[level] = {tuple(c): rises[tuple(c)] for c in cells}
                    for c in cells:
                        self.levels[tuple(c)] = level
            self.stairs = stair_layout(plan)
            self.spans = viaduct_spans(plan, self)
            self.field = Field(plan, [stair['segment'] for stair in self.stairs], self.spans)
        curb = settings.curb_height
        # Under a raised highway's decks (and cut back beside its ramps).
        self.decks = deck_profiles(plan)
        # The ground is graded up and down to each foundation and forecourt
        # (``_shaped``).
        self.forecourts = {}
        for lot in plan.lots:
            court = forecourt(lot, plan, self.surface, self.nodes)
            if court is not None:
                self.forecourts[lot.id] = court
        self.pads = ([(footprint(lot.center, lot.width, lot.depth, lot.rotation),
                       curb + lot.level) for lot in plan.lots] +
                     [(court.polygon, court) for court in self.forecourts.values()] +
                     [(site_footprint(poi), curb + poi.level) for poi in plan.pois] +
                     [(footprint(yard.center, yard.width, yard.depth, 0.0), curb + yard.level)
                      for yard in getattr(plan, 'yards', ())])
        self.hash = defaultdict(list)
        for polygon, top in self.pads:
            xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
            rise = self.level_at(sum(xs) / len(xs), sum(ys) / len(ys))
            margin = PAD_REACH
            for i in range(math.floor((min(xs) - margin) / PAD_CELL),
                           math.floor((max(xs) + margin) / PAD_CELL) + 1):
                for j in range(math.floor((min(ys) - margin) / PAD_CELL),
                               math.floor((max(ys) + margin) / PAD_CELL) + 1):
                    self.hash[i, j].append((polygon, top, rise))

    def line(self, k):
        """The ground's line for lattice line ``k`` (a terrace's edge)."""
        return round(k * self.size / SAMPLE) * SAMPLE

    def _index(self, value):
        k = math.floor(value / self.size)
        while value < self.line(k):
            k -= 1
        while value >= self.line(k + 1):
            k += 1
        return k

    def level_at(self, x, y):
        """The level the ground at (x, y) belongs to: 0 off the terraces."""
        if not self.terraces:
            return 0
        return self.levels.get((self._index(x), self._index(y)), 0)

    def rise(self, x, y, level):
        """Metres the terrace ``level`` stands above the hills at (x, y)."""
        if not level:
            return 0.0
        if level in self.tops:
            return self.tops[level]
        rises = self.slopes[level]
        # On a block's edge any of its slope blocks will do: they agree there.
        for cell in sorted({(self._index(x + dx), self._index(y + dy))
                            for dx in (-1e-7, 1e-7) for dy in (-1e-7, 1e-7)}):
            if cell in rises:
                return rises[cell](x, y)
        return 0.0

    def natural(self, x, y, level=None):
        if not self.terraces:
            return self.surface(x, y) + self.offset
        if level is None:
            level = self.level_at(x, y)
        return self.base(x, y) + self.rise(x, y, level) + self.offset

    def ground(self, x, y, cap=math.inf, level=None):
        """Graded ground at (x, y); ``cap`` is a pad top it must also stay
        under; ``level`` the terrace level (on a terrace's edge, which side)."""
        if self.terraces:
            if level is None:
                level = self.level_at(x, y)
            height = self._shaped(x, y, self.natural(x, y, level), level)
            return min(height, cap - PAD_CLEAR, self.under_decks(x, y))
        level = self.surface(x, y)
        height = min(self._shaped(x, y, level + self.offset, 0), cap - PAD_CLEAR,
                     self.under_decks(x, y))
        if self.field.value(x, y) <= self.walk + .5:
            height = max(height, level + CURB_BOTTOM_TERRAIN + .05)
        if self.outers:
            height = min(self._outer_section(x, y, height), self.under_decks(x, y))
        return height

    def _outer_section(self, x, y, height):
        """The ground (``height``) beside an outer road out in the wild land:
        level with its edges out to the ground grid's next line, then cut or
        filled at OUTER_SLOPE back to the hills."""
        width, deep = OUTER_DITCH
        for outer in self.outers:
            a, b = (x, y) if outer.axis == 0 else (y, x)
            along = (a - outer.cut) * outer.sign
            off = abs(b - outer.centre)
            if along < 0 or along > outer.length or off > OUTER_CORRIDOR:
                continue
            bed = math.ceil(outer.band / GROUND_CELL_TERRAIN - 1e-9) * GROUND_CELL_TERRAIN
            side = math.copysign(1.0, b - outer.centre)
            lateral = outer.centre + side * min(off, outer.band)
            edge = outer.top(along, lateral) + self.offset
            beyond = max(0.0, off - bed)
            # How far the hills stand over the road past the ditch: a ditch
            # in a cutting, none on an embankment.
            rim = outer.centre + side * (bed + width)
            hill = self.surface(*((a, rim) if outer.axis == 0 else (rim, a))) + self.offset
            share = min(1.0, max(0.0, (hill - edge - OUTER_DITCH_CUT[0]) / OUTER_DITCH_CUT[1]))
            high = edge + OUTER_SLOPE * max(0.0, beyond - width * share)
            height = min(max(height, edge - OUTER_SLOPE * beyond), high)
            if share and beyond < width:
                height = min(height, edge - deep * share * (1 - abs(2 * beyond / width - 1)))
        return height

    def under_decks(self, x, y, beside=True):
        """The most the ground may stand at (x, y) for a raised highway's
        decks (math.inf away from them); ``beside`` False: only right under
        one."""
        return _deck_cut(self.decks, x, y, beside) if self.decks else math.inf

    def _shaped(self, x, y, height, level):
        """Natural ``height`` blended into the foundations on ``level`` round
        (x, y), so a foundation stands in its ground rather than on a plinth
        over it: level with each for PAD_SHOULDER, then cut down at
        PAD_CUT_SLOPE or filled up at PAD_FILL_SLOPE to the natural ground.
        Near a foundation the ground also meets the footways, level with
        them for PAD_SHOULDER and rising or falling from them at the same
        slopes (so a front yard runs from the footway to the door, with no
        curb wall along it)."""
        ceiling, floor = math.inf, -math.inf
        nearest = (math.inf, math.inf, -math.inf)
        for polygon, top, pad_level in self.hash.get(
                (math.floor(x / PAD_CELL), math.floor(y / PAD_CELL)), ()):
            if pad_level != level:
                continue
            gap = _polygon_distance(polygon, x, y)
            distance = max(0.0, gap - PAD_SHOULDER)
            here = _pad_top(top, x, y)
            high = here - PAD_CLEAR + PAD_CUT_SLOPE * distance
            low = here - PAD_CLEAR - PAD_FILL_SLOPE * distance
            ceiling, floor = min(ceiling, high), max(floor, low)
            # Of pads as near (side by side), the lower.
            if (gap, high) < nearest[:2]:
                nearest = (gap, high, low)
        if nearest[0] == math.inf:
            return height
        if floor > ceiling:
            # Between two foundations at different levels: the nearer one's.
            ceiling, floor = nearest[1], nearest[2]
        value = self.field.value(x, y)
        if value < self.walk - .3 or self.streets.value(x, y) < self.walk - .3:
            # Under the paving (a viaduct's too) the ground is never lifted
            # into it (its edge, cut on the sample grid, counts as outside).
            return min(height, ceiling)
        beyond = max(0.0, value - self.walk)
        if beyond < PAD_REACH:
            # The ground at a footway's edge: on terraces (cut at that edge)
            # just under the footway's top; on hills (whose cells reach under
            # the paving) at the street's own ground.
            footway = self.surface(x, y) + (self.plan.settings.curb_height - .05
                                            if self.terraces else self.offset)
            slope = max(0.0, beyond - PAD_SHOULDER)
            high = footway + PAD_CUT_SLOPE * slope
            low = footway - PAD_FILL_SLOPE * slope
            if max(floor, low) <= min(ceiling, high):
                ceiling, floor = min(ceiling, high), max(floor, low)
            else:
                # Where they cannot meet, the lower of the two: the ground
                # never stands above a footway or a foundation.
                ceiling = min(ceiling, high)
                floor = min(floor, low, ceiling)
        return min(max(height, floor), ceiling)

    def lowest(self, polygon, step=2.0):
        """Lowest ground over a convex polygon (sampled about ``step`` apart)."""
        xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
        nx = max(1, math.ceil((max(xs) - min(xs)) / step))
        ny = max(1, math.ceil((max(ys) - min(ys)) / step))
        low = math.inf
        for i in range(nx + 1):
            for j in range(ny + 1):
                x = min(xs) + (max(xs) - min(xs)) * i / nx
                y = min(ys) + (max(ys) - min(ys)) * j / ny
                if _polygon_distance(polygon, x, y) <= 1e-6:
                    low = min(low, self.ground(x, y))
        for x, y in polygon:
            low = min(low, self.ground(x, y))
        return low

    def stair_at(self, x, y):
        """The stair whose hole (x, y) is in, if a stair is nearer than any street."""
        best, value = None, self.streets.value(x, y)
        for stair in self.stairs:
            candidate = _distance(x, y, stair['segment']) - stair['segment'][4]
            if candidate < value:
                best, value = stair, candidate
        return best

    def paved(self, x, y):
        """The walking surface at a point of the street network or a stair:
        the carriageway, the footway's top, or a stair's pitch line."""
        stair = self.stair_at(x, y)
        if stair is not None:
            return stair_pitch(stair, x, y)
        level = self.surface(x, y)
        if self.streets.value(x, y) <= 0:
            return level
        return level + pavement_height(self.plan, x, y, self.nodes)

    def wall_foot(self, x, y):
        """Where a wall at the edge of the paving meets it: the footway's top,
        or a riser below a stair's pitch line (under every step)."""
        stair = self.stair_at(x, y)
        if stair is not None:
            return stair_pitch(stair, x, y) - stair['riser']
        return self.surface(x, y) + pavement_height(self.plan, x, y, self.nodes)


SLOPE_KNOTS = ((0.0, 1.0), (.2, .88), (.8, .12), (1.0, 0.0))   # As city_plan's.


def _slope_profile(t):
    """Share of a terrace's rise left a fraction ``t`` down its slope (as
    ``city_plan.slope_profile``): three flat facets."""
    t = max(0.0, min(1.0, t))
    for (t0, h0), (t1, h1) in zip(SLOPE_KNOTS, SLOPE_KNOTS[1:]):
        if t <= t1:
            return h0 + (h1 - h0) * (t - t0) / (t1 - t0)
    return 0.0


def _corner_distance(a, b):
    a, b = max(0.0, a), max(0.0, b)
    return max(a, b, (a + b) / math.sqrt(2))


class _Facets:
    """The hills as flat facets (as ``city_plan.Facets``), on the ground's
    snapped lines."""

    def __init__(self, radius, heights, line, index):
        self.radius, self.heights, self.line, self.index = radius, heights, line, index

    def __call__(self, x, y):
        if not self.heights:
            return 0.0
        i, j = self.index(x), self.index(y)
        if i < -self.radius or j < -self.radius or i >= self.radius or j >= self.radius:
            return 0.0
        x0, x1, y0, y1 = self.line(i), self.line(i + 1), self.line(j), self.line(j + 1)
        u, v = (x - x0) / (x1 - x0), (y - y0) / (y1 - y0)
        h = self.heights
        h00, h10 = h.get((i, j), 0.0), h.get((i + 1, j), 0.0)
        h01, h11 = h.get((i, j + 1), 0.0), h.get((i + 1, j + 1), 0.0)
        if u >= v:
            return h00 + (h10 - h00) * u + (h11 - h10) * v
        return h00 + (h01 - h00) * v + (h11 - h01) * u


def _slope_rises(region, line):
    """{cell: rise(x, y)} over a terrace's slopes and the corners joining
    them, with lattice line k standing at ``line(k)`` (as
    ``city_plan.slope_rises``)."""
    step = region['step']
    found = {}

    def down(value, crest, sign):
        a, b = line(crest), line(crest + sign)
        return (value - a) / (b - a)
    for slope in region.get('slopes', ()):
        axis, sign, crest = slope['axis'], slope['sign'], slope['line']
        for c in slope['cells']:
            found[tuple(c)] = (lambda x, y, axis=axis, sign=sign, crest=crest:
                               step * _slope_profile(down((x, y)[axis], crest, sign)))
    for corner in region.get('corners', ()):
        (cx, sx), (cy, sy) = corner['x'], corner['y']
        found[tuple(corner['cell'])] = (
            lambda x, y, cx=cx, sx=sx, cy=cy, sy=sy: step * _slope_profile(
                _corner_distance(down(x, cx, sx), down(y, cy, sy))))
    return found


def _ramp_rows(plan):
    """Every ramp edge as a world segment."""
    size = plan.settings.block_size
    return [(a[0] * size, a[1] * size, b[0] * size, b[1] * size, 0.0)
            for ramp in (getattr(plan, 'terraces', None) or {}).get('ramps', ())
            for a, b in zip(ramp['nodes'], ramp['nodes'][1:])]


def _walk_polyline(points, step):
    """(arc length, point, unit tangent) about every ``step`` metres, both ends included."""
    lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
    total = sum(lengths)
    count = max(1, math.ceil(total / step))
    samples = []
    for k in range(count + 1):
        target = total * k / count
        along = 0.0
        for (a, b), length in zip(zip(points, points[1:]), lengths):
            if length and (target <= along + length or (a, b) == (points[-2], points[-1])):
                t = max(0.0, min(1.0, (target - along) / length))
                samples.append((target, (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t),
                                ((b[0] - a[0]) / length, (b[1] - a[1]) / length)))
                break
            along += length
    return samples


def viaduct_spans(plan, grading):
    """{path id: [(start, end) arc lengths]}: the stretches of a ramp high
    enough over the ground on either side to stand on piers."""
    ramps = _ramp_rows(plan)
    if not ramps:
        return {}
    walk = plan.settings.sidewalk_width
    spans = {}
    for path in plan.paths:
        half = path['width'] / 2
        reach = half + walk + 1.0
        runs, start, previous = [], None, None
        for along, (x, y), (tx, ty) in _walk_polyline(path['points'], 1.0):
            # (A ramp's wide turns run up to about 10 m off the lattice.)
            high = min(_distance(x, y, r) for r in ramps) < RAMP_REACH
            if high:
                soffit = grading.surface(x, y) - DECK_DEPTH
                under = max(grading.natural(x - ty * o, y + tx * o) for o in (-reach, 0, reach))
                high = soffit - under >= VIADUCT_CLEARANCE
            if high and start is None:
                start = along
            elif not high and start is not None:
                runs.append((start, previous))
                start = None
            previous = along
        if start is not None:
            runs.append((start, previous))
        runs = [(a, b) for a, b in runs if b - a >= VIADUCT_SPAN]
        if runs:
            spans[path['id']] = runs
    return spans


def stair_layout(plan):
    """Each stair as built: from the upper street's footway (``top`` metres
    along from the upper junction, at ``z_top``) down to the lower street's
    (``bottom``, ``z_bottom``) in equal steps; ``segment`` is its hole in the
    ground, as a field row (``STAIR_WIDTH`` wide at the footways' edge)."""
    terraces = getattr(plan, 'terraces', None) or {}
    if not terraces.get('stairs'):
        return []
    settings = plan.settings
    size, walk = settings.block_size, settings.sidewalk_width
    field = Field(plan)
    surface = plan.surface()
    nodes = flush_junctions(plan)
    stairs = []
    for stair in terraces['stairs']:
        hx, hy = stair['high'][0] * size, stair['high'][1] * size
        lx, ly = stair['low'][0] * size, stair['low'][1] * size
        length = math.hypot(lx - hx, ly - hy)
        ux, uy = (lx - hx) / length, (ly - hy) / length

        def clear(sign):
            # The first point out from a junction past its street's footway.
            for k in range(int(length * 10)):
                along = k / 10 if sign > 0 else length - k / 10
                if field.value(hx + ux * along, hy + uy * along) > walk:
                    return along
            return length / 2
        top, bottom = clear(1), clear(-1)

        def level(along):
            x, y = hx + ux * along, hy + uy * along
            return surface(x, y) + pavement_height(plan, x, y, nodes)
        z_top, z_bottom = level(top), level(bottom)
        steps = max(1, math.ceil((z_top - z_bottom) / STAIR_RISE))
        half = stair['width'] / 2
        stairs.append({'origin': (hx, hy), 'direction': (ux, uy), 'length': length,
                       'top': top, 'bottom': bottom, 'z_top': z_top, 'z_bottom': z_bottom,
                       'steps': steps, 'riser': (z_top - z_bottom) / steps, 'half': half,
                       'segment': (hx, hy, lx, ly, half - walk)})
    return stairs


def stair_pitch(stair, x, y):
    """Height of a stair's pitch line (its step nosings) abreast of (x, y)."""
    (hx, hy), (ux, uy) = stair['origin'], stair['direction']
    along = (x - hx) * ux + (y - hy) * uy
    run = stair['bottom'] - stair['top']
    t = max(0.0, min(1.0, (along - stair['top']) / run)) if run > 0 else 0.0
    return stair['z_top'] + (stair['z_bottom'] - stair['z_top']) * t


def build_stair_mesh(plan):
    """Stairs up the terraces' faces: closed solid steps between the walls,
    with a landing under each street's footway."""
    vertices, faces = [], []
    for stair in stair_layout(plan):
        (hx, hy), (ux, uy) = stair['origin'], stair['direction']
        px, py = -uy, ux
        half = stair['half'] - STAIR_INSET
        base = stair['z_bottom'] - STAIR_BASE
        run = (stair['bottom'] - stair['top']) / stair['steps']
        pieces = [(stair['top'] - STAIR_LANDING, stair['top'], stair['z_top'] - .02)]
        for index in range(stair['steps']):
            top = stair['z_top'] - (index + 1) * stair['riser']
            pieces.append((stair['top'] + index * run, stair['top'] + (index + 1) * run,
                           top - (.02 if index == stair['steps'] - 1 else 0.0)))
        pieces.append((stair['bottom'], stair['bottom'] + STAIR_LANDING, stair['z_bottom'] - .02))
        for a0, a1, top in pieces:
            offset = len(vertices)
            for z in (base, top):
                for along, across in ((a0, -half), (a1, -half), (a1, half), (a0, half)):
                    vertices.append((round(hx + ux * along + px * across, 8),
                                     round(hy + uy * along + py * across, 8), round(z, 8)))
            # Counter-clockwise seen from outside (the frame is right-handed).
            faces.extend(tuple(offset + i for i in f) for f in
                         ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                          (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)))
    return vertices, faces


def heightmap(plan, resolution, column_sign=1, row_sign=1):
    """The graded ground with every building and site pad at its top (streets
    at their road level, to within the ground's few centimetres) on a
    ``resolution`` x ``resolution`` grid over the city ground. Returns
    ``(rows, x0, y0, step)``: sample (row r, column c) lies at
    (x0 + column_sign * c * step, y0 + row_sign * r * step) from the city
    origin; columns run along x, rows along y."""
    settings = plan.settings
    extent = settings.radius * settings.block_size + 20
    step = 2 * extent / (resolution - 1)
    x0 = -extent if column_sign > 0 else extent
    y0 = -extent if row_sign > 0 else extent
    grading = Grading(plan)
    surface, offset = grading.surface, grading.offset
    terraced = bool(grading.terraces)
    rows = []
    for r in range(resolution):
        y = y0 + row_sign * r * step
        row = []
        for c in range(resolution):
            x = x0 + column_sign * c * step
            if terraced and grading.field.value(x, y) <= grading.walk:
                # Streets, ramps and stairs at their walking surface.
                row.append(grading.paved(x, y))
                continue
            here = grading.level_at(x, y)
            height = grading.natural(x, y, here) if terraced else surface(x, y) + offset
            tops = [_pad_top(top, x, y) for polygon, top, level in grading.hash.get(
                (math.floor(x / PAD_CELL), math.floor(y / PAD_CELL)), ())
                if level == here and _polygon_distance(polygon, x, y) <= 0.0]
            row.append(tops[0] if tops else grading._shaped(x, y, height, here))
        rows.append(row)
    return rows, x0, y0, step


def site_footprint(poi):
    """World corners of a site's pad, its approach to the footway included."""
    width, depth = poi.width, poi.depth + poi.approach
    c, s = math.cos(poi.rotation), math.sin(poi.rotation)
    # The approach extends the pad toward the street (local -y).
    cx, cy = 0.0, -poi.approach / 2
    center = (poi.center[0] + cx * c - cy * s, poi.center[1] + cx * s + cy * c)
    return footprint(center, width, depth, poi.rotation)


def _subtract(rect, holes):
    """Axis-aligned rectangle minus rectangles, as disjoint rectangles."""
    pieces = [rect]
    for hx0, hy0, hx1, hy1 in holes:
        result = []
        for x0, y0, x1, y1 in pieces:
            if hx0 >= x1 or hx1 <= x0 or hy0 >= y1 or hy1 <= y0:
                result.append((x0, y0, x1, y1))
                continue
            cx0, cy0, cx1, cy1 = max(x0, hx0), max(y0, hy0), min(x1, hx1), min(y1, hy1)
            for piece in ((x0, y0, x1, cy0), (x0, cy1, x1, y1),
                          (x0, cy0, cx0, cy1), (cx1, cy0, x1, cy1)):
                if piece[2] - piece[0] > 1e-6 and piece[3] - piece[1] > 1e-6:
                    result.append(piece)
        pieces = result
    return pieces


def _oriented(points, outward):
    """Points ordered so the polygon's normal points along ``outward``."""
    nx = ny = nz = 0.0
    for index, (x0, y0, z0) in enumerate(points):
        x1, y1, z1 = points[(index + 1) % len(points)]
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    if nx * outward[0] + ny * outward[1] + nz * outward[2] < 0:
        return list(reversed(points))
    return points


def build_outer_road_mesh(plan, street_vertices):
    """Highways continuing out of the city across the wasteland.

    Materials: 0 carriageway, 1 shoulder, 2 curbs and skirts (every vertical
    face), 3 ground (where the surface has broken up). The first cross-section is made of the
    street mesh's own vertices on the cut line (``street_vertices``), so the two
    meshes meet without cracks: the footways ramp down onto the shoulders, and
    the long edges and the far end drop to ``CURB_BOTTOM`` like the city curbs.
    """
    vertices, faces, materials = [], [], []
    ids = {}

    def vertex(co):
        co = (round(co[0], 8), round(co[1], 8), round(co[2], 8))
        if co not in ids:
            ids[co] = len(vertices)
            vertices.append(co)
        return ids[co]

    def face(points, material, outward=(0.0, 0.0, 1.0)):
        indices = list(dict.fromkeys(vertex(point) for point in _oriented(points, outward)))
        if len(indices) >= 3:
            faces.append(tuple(indices))
            materials.append(material)

    seed = plan.settings.seed
    for index, outer in enumerate(outer_roads(plan)):
        low, high = outer.centre - outer.band, outer.centre + outer.band
        heights = {}
        if outer.deck:
            # Off a raised highway's deck: shoulders flush with the carriageway.
            heights = {round(b, 8): outer.top(0.0, b) for b in (low, outer.centre - outer.half,
                                                                outer.centre + outer.half, high)}
            street_vertices = ()
        for x, y, z in street_vertices:
            a, b = (x, y) if outer.axis == 0 else (y, x)
            if abs(a - outer.cut) < 1e-6 and low - 1e-6 <= b <= high + 1e-6:
                key = round(b, 8)
                heights[key] = max(heights.get(key, z), z)
        laterals = sorted(heights)
        if len(laterals) < 2:
            continue
        length = outer.length
        fade_start = max(0.0, length - outer.road['fade'])
        alongs = [0.0, OUTER_RAMP / 2, OUTER_RAMP]
        while alongs[-1] < length - 1e-6:
            step = OUTER_SOLID_ROW if alongs[-1] < fade_start - 1e-6 else OUTER_FADE_ROW
            following = alongs[-1] + step
            if alongs[-1] < fade_start - 1e-6:
                following = min(following, fade_start)
            alongs.append(min(following, length))
        # On hills a row wherever its level bends.
        alongs = sorted(set(alongs) | {a for a in outer.bends() if 0 < a < length})
        road_seed = seed * 31 + index

        def shoulder(lateral, along):
            """Footway height at the cut, ramping down to the shoulder level."""
            key = round(lateral, 8)
            raised = heights.get(key, outer.top(0.0, lateral)) - outer.top(0.0, lateral)
            return outer.top(along, lateral) + raised * max(0.0, 1 - along / OUTER_RAMP)

        def surface(lateral, along, carriageway):
            if carriageway:
                return outer.top(along, lateral)
            return shoulder(lateral, along)

        for a0, a1 in zip(alongs, alongs[1:]):
            middle = (a0 + a1) / 2
            for l0, l1 in zip(laterals, laterals[1:]):
                lateral = (l0 + l1) / 2
                road = abs(lateral - outer.centre) <= outer.half
                if not outer_asphalt(outer, road_seed, middle, lateral):
                    material = 3
                else:
                    material = 0 if road else 1
                face([outer.world(a0, l0, surface(l0, a0, road)),
                      outer.world(a1, l0, surface(l0, a1, road)),
                      outer.world(a1, l1, surface(l1, a1, road)),
                      outer.world(a0, l1, surface(l1, a0, road))], material)
            # Curbs where the raised footways meet the carriageway, while they ramp.
            if a0 < OUTER_RAMP - 1e-9:
                for side in (-1, 1):
                    lateral = round(outer.centre + side * outer.half, 8)
                    if lateral not in heights:
                        continue
                    toward = (0.0, -side, 0.0) if outer.axis == 0 else (-side, 0.0, 0.0)
                    face([outer.world(a0, lateral, outer.top(a0, lateral)),
                          outer.world(a1, lateral, outer.top(a1, lateral)),
                          outer.world(a1, lateral, shoulder(lateral, a1)),
                          outer.world(a0, lateral, shoulder(lateral, a0))], 2, toward)
            for side, lateral in ((-1, laterals[0]), (1, laterals[-1])):
                outward = (0.0, side, 0.0) if outer.axis == 0 else (side, 0.0, 0.0)
                face([outer.world(a0, lateral, shoulder(lateral, a0)),
                      outer.world(a1, lateral, shoulder(lateral, a1)),
                      outer.world(a1, lateral, outer.top(a1, lateral) + CURB_BOTTOM),
                      outer.world(a0, lateral, outer.top(a0, lateral) + CURB_BOTTOM)],
                     2, outward)
        outward = (outer.sign, 0.0, 0.0) if outer.axis == 0 else (0.0, outer.sign, 0.0)
        for l0, l1 in zip(laterals, laterals[1:]):
            face([outer.world(length, l0, outer.top(length, l0)),
                  outer.world(length, l1, outer.top(length, l1)),
                  outer.world(length, l1, outer.top(length, l1) + CURB_BOTTOM),
                  outer.world(length, l0, outer.top(length, l0) + CURB_BOTTOM)], 2, outward)
    return vertices, faces, materials


def outer_road_dashes(plan):
    """Worn lane dashes on the outer highways: quads (four points just over
    the road) at the lane lines, thinning out and gone where the surface
    breaks up."""
    quads = []
    seed = plan.settings.seed
    for index, outer in enumerate(outer_roads(plan)):
        width = outer.road['width']
        offsets = (0.0, -width / 4, width / 4) if width >= 12 else (0.0,)
        road_seed = seed * 31 + index
        fade_start = outer.length - outer.road['fade']
        along = 6.0 - abs(outer.cut - outer.start)     # From just past the end node.
        step = 0
        while along + 3 < outer.length:
            step += 1
            middle = along + 1.5
            worn = .2 + (max(0.0, middle - fade_start) / max(1.0, outer.road['fade'])) * .6
            for lane, offset in enumerate(offsets):
                lateral = outer.centre + offset
                if _hash01(road_seed + 7, step, lane) < worn:
                    continue
                if not outer_asphalt(outer, road_seed, middle, lateral):
                    continue
                # Over the road all along, where its level bends under it too.
                ends = (outer.top(along, lateral), outer.top(along + 3, lateral))
                lift = .004 + max(0.0, outer.top(middle, lateral) - sum(ends) / 2)
                quad = [outer.world(along, lateral - .06, ends[0] + lift),
                        outer.world(along + 3, lateral - .06, ends[1] + lift),
                        outer.world(along + 3, lateral + .06, ends[1] + lift),
                        outer.world(along, lateral + .06, ends[0] + lift)]
                area = sum(ax * by - bx * ay for (ax, ay, _), (bx, by, _) in
                           zip(quad, quad[1:] + quad[:1]))
                quads.append(quad if area > 0 else quad[::-1])
            along += 7.0
    return quads
