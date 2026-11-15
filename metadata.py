# SPDX-License-Identifier: GPL-3.0-or-later
"""City metadata for game-side procedural placement (pure Python).

The city operator fills a ``CityMetadata`` while it builds the scene and stores
``as_dict()`` as JSON; the FBX exporter writes it next to the FBX. Everything
the game may want to place or query lives here: roads and junctions, driving
loops, buildings with their entrances, sites, transit stops, and markers for
assets the game supplies (small props, trees, fences, flagpoles, parked cars).

Coordinates are metres in one space, chosen at export:

``UNITY`` (default): Unity world space as the companion FBX imports
    (exported with forward -Z, up Y): a Blender point (x, y, z) becomes
    (-x, z, -y). ``yaw`` is the rotation about +Y in degrees that turns an
    asset modelled facing +Z to face ``forward``.
``BLENDER``: Blender world space, Z up. ``yaw`` is the rotation about +Z in
    degrees that turns an asset modelled facing -Y to face ``forward``.

Objects are referred to by name (the FBX node and Unity GameObject names), so
a script can bind entries to the imported meshes.

Interiors (each building's ``rooms``, ``lifts`` and ``railings``) are in
building space, to keep the file small: offsets from the building's
``position`` in the same axes, rotated by its ``yaw`` about up. In Unity a
point is ``position + Quaternion.Euler(0, yaw, 0) * local``. Rooms carry what
furnishing needs (kind, clear size, doors, windows, blank wall runs); lifts
their shaft, served floors, doors and car; railings a base line and height.
Furniture, railings and lift parts are game assets: none is modelled.

The layout suits Unity's ``JsonUtility``: no dictionaries, nested arrays or
nulls (unknown numbers are 0, unknown strings empty).
Point lists (road centrelines, fence lines) are flat [x, y, z, x, y, z, ...]
arrays and lattice nodes flat [x, y, x, y, ...] arrays; markers are one list,
each with a ``type``.
"""
import math

from .interior import FIXTURE_KINDS
from .sites import SMALL_PROPS

FORMAT = 'ares.city.metadata'
SCHEMA = 2
SPACES = ('UNITY', 'BLENDER')

# Markers the game always supplies (no mesh is generated for them).
MARKER_ONLY = ('tree', 'fence', 'flagpole', 'parking_stall') + FIXTURE_KINDS


def apply(transform, x, y, z=0.0):
    """Blender world point of a local point under (tx, ty, tz, yaw)."""
    tx, ty, tz, yaw = transform
    c, s = math.cos(yaw), math.sin(yaw)
    return (tx + c * x - s * y, ty + s * x + c * y, tz + z)


def turn(transform, fx, fy):
    yaw = transform[3]
    c, s = math.cos(yaw), math.sin(yaw)
    return (c * fx - s * fy, s * fx + c * fy)


def chain(parent, child):
    """Transform of ``child`` (given in ``parent``'s frame) in world space."""
    x, y, z = apply(parent, child[0], child[1], child[2])
    return (x, y, z, parent[3] + child[3])


class Space:
    def __init__(self, name='UNITY'):
        if name not in SPACES:
            raise ValueError(f'Unknown metadata space: {name}')
        self.name = name

    def point(self, p):
        x, y, z = p
        if self.name == 'UNITY':
            return [_r(-x), _r(z), _r(-y)]
        return [_r(x), _r(y), _r(z)]

    def direction(self, fx, fy):
        length = math.hypot(fx, fy) or 1.0
        fx, fy = fx / length, fy / length
        if self.name == 'UNITY':
            return [_r(-fx, 6), 0.0, _r(-fy, 6)]
        return [_r(fx, 6), _r(fy, 6), 0.0]

    def yaw(self, fx, fy):
        if self.name == 'UNITY':
            ux, _, uz = self.direction(fx, fy)
            return _r(math.degrees(math.atan2(ux, uz)) % 360.0, 3)
        return _r(math.degrees(math.atan2(fx, -fy)) % 360.0, 3)

    def local(self, p):
        """A building-space point (object axes, z up) in this space's axes."""
        return self.point(p)

    def local_direction(self, fx, fy):
        return self.direction(fx, fy)

    def pose(self, p, fx, fy):
        return {'position': self.point(p), 'forward': self.direction(fx, fy),
                'yaw': self.yaw(fx, fy)}

    def describe(self):
        if self.name == 'UNITY':
            return {'name': 'UNITY', 'units': 'metres', 'up': '+Y',
                    'from_blender': '(x, y, z) -> (-x, z, -y)',
                    'yaw': 'degrees about +Y turning an asset modelled facing +Z to face forward',
                    'interiors': 'building space: world = position + Quaternion.Euler(0, yaw, 0) * local'}
        return {'name': 'BLENDER', 'units': 'metres', 'up': '+Z',
                'yaw': 'degrees about +Z turning an asset modelled facing -Y to face forward',
                'interiors': 'building space: world = position + rotation(yaw about +Z) * local'}


def local_entrances(spec):
    """Ground-floor street doors of a building, in its object space (footprint
    centred on the origin): (x, y, outward normal x, y, width)."""
    result = []
    for facade in spec.tiers[0].facades:
        nx, ny = facade.normal
        for opening in facade.openings:
            if opening.kind != 'door' or min(z for _, z in opening.bottom) > 1e-6:
                continue
            x, y = facade.point((opening.u0 + opening.u1) / 2)
            result.append((round(x - spec.width / 2, 3), round(y - spec.depth / 2, 3),
                           nx, ny, round(opening.u1 - opening.u0, 3)))
    return result


def _flat(items):
    return [value for item in items for value in item]


def _r(value, digits=3):
    return round(float(value), digits)


STREET_KINDS = ('surface', 'street')    # Underground nodes that are the street level.


def _across(passage, along, across):
    """Plan point of a passage running across a sewer: ``along`` the sewer,
    ``across`` (absolute) along the passage."""
    return (along, across) if passage.axis == 'y' else (across, along)
SHAFT_SIZE = .9                         # sewers.SHAFT, for exits.


def _graph_facts(nodes, links):
    """The underground graph with derived facts: per node ``depth`` (links to
    the nearest street-level node, -1 if none is reached) and ``exits``
    (street-level nodes in its connected part); per link ``bridge`` (taking
    it away splits its part)."""
    index = {node['id']: k for k, node in enumerate(nodes)}
    near = [[] for _ in nodes]
    for number, link in enumerate(links):
        a, b = index.get(link['a']), index.get(link['b'])
        if a is None or b is None or a == b:
            continue
        near[a].append((b, number))
        near[b].append((a, number))
    streets = [k for k, node in enumerate(nodes) if node['kind'] in STREET_KINDS]
    depth = [-1] * len(nodes)
    queue = list(streets)
    for k in streets:
        depth[k] = 0
    head = 0
    while head < len(queue):
        v = queue[head]
        head += 1
        for w, _ in near[v]:
            if depth[w] < 0:
                depth[w] = depth[v] + 1
                queue.append(w)
    part = [-1] * len(nodes)
    exits = []
    for root in range(len(nodes)):
        if part[root] >= 0:
            continue
        label, count, todo = len(exits), 0, [root]
        part[root] = label
        while todo:
            v = todo.pop()
            count += nodes[v]['kind'] in STREET_KINDS
            for w, _ in near[v]:
                if part[w] < 0:
                    part[w] = label
                    todo.append(w)
        exits.append(count)
    # Bridges (Tarjan, iterative): a link is one when nothing else joins its far side back.
    seen, low, bridges, clock = [-1] * len(nodes), [0] * len(nodes), set(), 0
    for root in range(len(nodes)):
        if seen[root] >= 0:
            continue
        seen[root] = low[root] = clock
        clock += 1
        stack = [(root, -1, iter(near[root]))]
        while stack:
            v, via, edges = stack[-1]
            for w, number in edges:
                if number == via:
                    continue
                if seen[w] < 0:
                    seen[w] = low[w] = clock
                    clock += 1
                    stack.append((w, number, iter(near[w])))
                    break
                low[v] = min(low[v], seen[w])
            else:
                stack.pop()
                if stack:
                    u = stack[-1][0]
                    low[u] = min(low[u], low[v])
                    if low[v] > seen[u]:
                        bridges.add(via)
    return {'nodes': [dict(node, depth=depth[k], exits=exits[part[k]]) for k, node in enumerate(nodes)],
            'links': [dict(link, bridge=k in bridges) for k, link in enumerate(links)]}


class CityMetadata:
    """Collects metadata while a city is generated; ``as_dict`` builds the JSON."""

    def __init__(self, plan, origin=(0.0, 0.0, 0.0), space='UNITY', props_modelled=True,
                 addon_version='', collection='', interiors=True, water=False):
        self.plan = plan
        self.origin = tuple(origin)
        self.space = Space(space)
        self.props_modelled = props_modelled
        self.addon_version = addon_version
        self.collection = collection
        self.interiors = interiors      # Rooms, lifts and railings (fixtures are always listed).
        self.water = water              # Water surfaces modelled (always listed as markers).
        self.curb = plan.settings.curb_height
        self.buildings = []
        self.sites = []
        self.yards = []
        self.stops = []
        self.markers = []
        self.under_nodes = []           # The underground graph: rooms below ground
        self.under_links = []           # and what joins them.
        self.tunnels = []
        self.sewers = []
        self.manholes = []
        self.breaches = []
        self.subway = {'lines': [], 'stations': [], 'utilities': [], 'risers': []}

    # -- transforms ------------------------------------------------------
    def lot_transform(self, lot):
        ox, oy, oz = self.origin
        return (ox + lot.center[0], oy + lot.center[1], oz + self.curb + lot.level, lot.rotation)

    def poi_transform(self, poi):
        ox, oy, oz = self.origin
        return (ox + poi.center[0], oy + poi.center[1], oz + self.curb + poi.level, poi.rotation)

    def _building(self, transform, width, depth, entrances, interior=None, obj_name='',
                  site_id=''):
        """Footprint pose, entrances and interior; ``entrances`` are object-local
        (centred) (x, y, normal_x, normal_y, width) tuples, ``interior`` the
        building's ``interior.interior_facts``."""
        fx, fy = turn(transform, 0.0, -1.0)
        doors = []
        for x, y, nx, ny, door in entrances:
            p = apply(transform, x, y, 0.0)
            dx, dy = turn(transform, nx, ny)
            doors.append(dict(self.space.pose(p, dx, dy), width=_r(door)))
        entry = self.space.pose(apply(transform, 0.0, 0.0, 0.0), fx, fy)
        entry.update(width=_r(width), depth=_r(depth), entrances=doors)
        entry.update(self._interior(interior or {}))
        self._underground(transform, obj_name, interior or {})
        for fixture in (interior or {}).get('fixtures', ()):
            fx_, fy_ = turn(transform, *fixture['facing'])
            marker = {'type': fixture['kind'], 'site': site_id, 'building': obj_name,
                      'floor': fixture['floor'], 'modelled': False}
            marker.update(self.space.pose(apply(transform, fixture['x'], fixture['y'], fixture['z']),
                                          fx_, fy_))
            marker['size'] = [_r(v) for v in fixture['size']]
            self.markers.append(marker)
        return entry

    def _underground(self, transform, building, facts):
        """Adds a building's rooms below ground to the underground graph:
        a node per room, a link per doorway, per pair of rooms open to each
        other and per stair, the topmost to the building's ``surface`` node
        (its ground floor). Listed whether or not interiors are."""
        below = [room for room in facts.get('rooms', ()) if room['floor'] < 0]
        if not below:
            return
        point = self.space.point

        def ident(name):
            return f'{building}/{name}'

        def centre(room):
            x0, y0, x1, y1 = room['rect']
            return apply(transform, (x0 + x1) / 2, (y0 + y1) / 2, room['z'])

        self.under_nodes.append({'id': ident('surface'), 'kind': 'surface', 'building': building,
                                 'room': '', 'floor': 0, 'layer': 'surface',
                                 'position': point(apply(transform, 0.0, 0.0, 0.0)), 'area': 0.0})
        names = {room['name'] for room in below}
        seen = set()
        stairs = {}
        for room in below:
            x0, y0, x1, y1 = room['rect']
            self.under_nodes.append({'id': ident(room['name']), 'kind': room['kind'],
                                     'building': building, 'room': room['name'],
                                     'floor': room['floor'], 'layer': room['layer'],
                                     'position': point(centre(room)),
                                     'area': _r((x1 - x0) * (y1 - y0))})
            if room['kind'] == 'stair':
                stairs[room['floor']] = room
            for door in room['doors']:
                pair = tuple(sorted((room['name'], door['to'])))
                if door['to'] in names and pair not in seen:
                    seen.add(pair)
                    self.under_links.append({
                        'a': ident(pair[0]), 'b': ident(pair[1]), 'kind': 'door',
                        'width': _r(door['width']),
                        'position': point(apply(transform, door['x'], door['y'], room['z']))})
        # Rooms of one group on a storey are open to each other.
        groups = {}
        for room in below:
            if room['group']:
                groups.setdefault((room['floor'], room['group']), []).append(room)
        for members in groups.values():
            for a, b in zip(members, members[1:]):
                self.under_links.append({'a': ident(a['name']), 'b': ident(b['name']), 'kind': 'open',
                                         'width': 0.0, 'position': point(centre(b))})
        for floor in sorted(stairs, reverse=True):
            upper = ident('surface') if floor == -1 else ident(stairs[floor + 1]['name']) \
                if floor + 1 in stairs else None
            if upper:
                self.under_links.append({'a': upper, 'b': ident(stairs[floor]['name']),
                                         'kind': 'stair', 'width': 0.0,
                                         'position': point(centre(stairs[floor]))})

    def add_tunnels(self, built):
        """Tunnels between basements: a node each in the underground graph,
        a ``tunnel`` link to the room at either end, and their own list
        (where the game hangs doors)."""
        from .tunnels import DOOR, HEIGHT, WIDTH
        from .basement import LAYERS
        ox, oy, oz = self.origin
        point = self.space.point
        for tunnel in built:
            def at(along, z):
                x, y = (along, tunnel.line) if tunnel.axis == 'x' else (tunnel.line, along)
                return point((ox + x, oy + y, oz + z))
            middle = at((tunnel.start + tunnel.end) / 2, (tunnel.za + tunnel.zb) / 2)
            self.under_nodes.append({'id': tunnel.id, 'kind': 'tunnel', 'building': '', 'room': '',
                                     'floor': tunnel.index, 'layer': LAYERS[tunnel.index],
                                     'position': middle, 'area': _r(tunnel.length * WIDTH)})
            ends = ((tunnel.a, tunnel.room_a, tunnel.start, tunnel.za), (tunnel.b, tunnel.room_b, tunnel.end, tunnel.zb))
            for building, room, along, z in ends:
                self.under_links.append({'a': f'{building}/{room}', 'b': tunnel.id, 'kind': 'tunnel',
                                         'width': _r(DOOR[0]), 'position': at(along, z)})
            self.tunnels.append({'id': tunnel.id, 'a': tunnel.a, 'b': tunnel.b, 'room_a': tunnel.room_a,
                                 'room_b': tunnel.room_b, 'floor': tunnel.index,
                                 'start': at(tunnel.start, tunnel.za), 'end': at(tunnel.end, tunnel.zb),
                                 'width': _r(WIDTH), 'height': _r(HEIGHT), 'door_width': _r(DOOR[0]),
                                 'door_height': _r(DOOR[1]), 'length': _r(tunnel.length),
                                 'under_street': tunnel.street})

    def add_sewers(self, network):
        """Sewers: chambers, sections (a collapsed one as its two halves),
        manholes up to street nodes, and breaches into basements; graph
        nodes and links, and their own lists."""
        from .sewers import SHAFT, TRENCH
        from . import tunnels as passages
        ox, oy, oz = self.origin
        point = self.space.point

        def at(x, y, z):
            return point((ox + x, oy + y, oz + z))

        for chamber in sorted(network.chambers.values(), key=lambda c: c.id):
            if chamber.hall:
                continue          # A subway hall: listed with the subway.
            self.under_nodes.append({'id': chamber.id, 'kind': 'chamber', 'building': '', 'room': '',
                                     'floor': -2, 'layer': 'sewer',
                                     'position': at(chamber.x, chamber.y, chamber.floor),
                                     'area': _r(chamber.size * chamber.size)})
            m = chamber.manhole
            if m is None:
                continue
            street = f'street_{chamber.node[0]}_{chamber.node[1]}'
            self.under_nodes.append({'id': street, 'kind': 'street', 'building': '', 'room': '',
                                     'floor': 0, 'layer': 'street', 'position': at(m.x, m.y, m.rim),
                                     'area': 0.0})
            self.under_links.append({'a': chamber.id, 'b': street, 'kind': 'shaft', 'width': _r(SHAFT),
                                     'height': _r(m.rim - chamber.floor), 'open': m.open,
                                     'position': at(m.x, m.y, m.rim)})
            self.manholes.append({'id': m.id, 'chamber': chamber.id, 'street': street,
                                  'position': at(m.x, m.y, m.rim), 'bottom': at(m.x, m.y, chamber.floor),
                                  'size': _r(SHAFT), 'shape': 'octagon', 'depth': _r(m.rim - chamber.floor),
                                  'open': m.open, 'kind': 'sewer'})
        halves = {}
        for sewer in network.sewers:
            clearance = 'walk' if sewer.kind == 'trunk' else 'crouch'
            parts = ([(sewer.id, sewer.start, sewer.end)] if sewer.plug is None else
                     [(sewer.id + ':a', sewer.start, sewer.plug[0]), (sewer.id + ':b', sewer.plug[1], sewer.end)])
            halves[sewer.id] = parts
            for ident, a0, a1 in parts:
                middle = (a0 + a1) / 2
                self.under_nodes.append({'id': ident, 'kind': 'sewer', 'building': '', 'room': '', 'floor': -2,
                                         'layer': 'sewer' if sewer.kind == 'trunk' else 'sewer_lateral',
                                         'position': at(*sewer.point(middle), sewer.floor_at(middle)),
                                         'area': _r((a1 - a0) * sewer.width)})
            for chamber, ident, along in ((sewer.a, parts[0][0], sewer.start), (sewer.b, parts[-1][0], sewer.end)):
                self.under_links.append({'a': chamber, 'b': ident, 'kind': 'sewer', 'width': _r(sewer.width),
                                         'height': _r(sewer.height), 'clearance': clearance,
                                         'position': at(*sewer.point(along), sewer.floor_at(along))})
            plug = ([at(*sewer.point(a), sewer.floor_at(a)) for a in sewer.plug] if sewer.plug else [])
            self.sewers.append({'id': sewer.id, 'kind': sewer.kind, 'a': sewer.a, 'b': sewer.b,
                                'start': at(*sewer.point(sewer.start), sewer.floor_at(sewer.start)),
                                'end': at(*sewer.point(sewer.end), sewer.floor_at(sewer.end)),
                                'width': _r(sewer.width), 'height': _r(sewer.height),
                                'length': _r(sewer.length), 'clearance': clearance,
                                'condition': 'collapsed' if sewer.plug else 'clear',
                                'plug_start': plug[0] if plug else [], 'plug_end': plug[1] if plug else [],
                                # An octagon with a trench down the floor; the walkways' level along
                                # the centre line, straight between these points.
                                'profile': 'octagon', 'trench_width': _r(TRENCH[sewer.kind][0]),
                                'trench_depth': _r(TRENCH[sewer.kind][1]),
                                'points': _flat(at(*sewer.point(a), f) for a, f in sewer.sections)})
        for item in network.breaches:
            t = item.tunnel
            node = next(ident for ident, a0, a1 in halves[item.sewer] if a0 - 1e-6 <= item.along <= a1 + 1e-6)

            def end(along, z, t=t):
                x, y = (along, t.line) if t.axis == 'x' else (t.line, along)
                return at(x, y, z)

            entry = {'id': item.id, 'building': item.site, 'room': item.room, 'sewer': node,
                     'start': end(t.start, t.za), 'end': end(t.end, t.zb), 'storey': item.storey,
                     'width': _r(passages.WIDTH), 'height': _r(passages.HEIGHT),
                     'door_width': _r(passages.DOOR[0]), 'door_height': _r(passages.DOOR[1]),
                     'length': _r(t.length), 'drop': item.drop is not None,
                     'ladder_bottom': [], 'ladder_top': [], 'ladder_facing': []}
            if item.drop is None:
                wall = (t.start, t.za) if t.b == item.sewer and item.side > 0 else (t.end, t.zb)
                position = end(*wall)
            else:
                # A ladder on the shaft's far wall, from the sewer's floor up to the passage's.
                from .sewers import DROP
                sewer_wall, far, zs, zb, top = item.drop
                position = at(*_across(t, item.along, sewer_wall), zs)
                face = far - item.side * DROP[1]
                entry['ladder_bottom'] = at(*_across(t, item.along, face), zs)
                entry['ladder_top'] = at(*_across(t, item.along, face), zb)
                facing = (0.0, -item.side) if t.axis == 'y' else (-item.side, 0.0)
                entry['ladder_facing'] = self.space.direction(*facing)
            self.under_links.append({'a': f'{item.site}/{item.room}', 'b': node, 'kind': 'breach',
                                     'width': _r(passages.DOOR[0]), 'height': _r(passages.HEIGHT),
                                     'position': position, 'ladder': item.drop is not None})
            self.breaches.append(entry)

    def add_subway(self, transit, network=None):
        """The subway: per station a hall and a platform node (and its
        bathrooms and the service rooms in from the sewers), the line between
        stations as runs, the rooms at the end of its hallways, the ladder
        shafts up to the sewer; stair, subway, door and shaft links; and its
        own lists. Exits join the manholes (kind ``exit``)."""
        from . import subway as sub
        from . import tunnels as passages
        ox, oy, oz = self.origin
        point = self.space.point

        def at(x, y, z):
            return point((ox + x, oy + y, oz + z))

        def node(ident, kind, position, area, floor):
            self.under_nodes.append({'id': ident, 'kind': kind, 'building': '', 'room': '', 'floor': floor,
                                     'layer': 'subway', 'position': position, 'area': _r(area)})

        def link(a, b, kind, width, position, **extra):
            self.under_links.append(dict({'a': a, 'b': b, 'kind': kind, 'width': _r(width), 'position': position},
                                         **extra))

        def axis_dir(axis, sign):
            return self.space.direction(*((float(sign), 0.0) if axis == 'x' else (0.0, float(sign))))

        order = {n: k for k, n in enumerate(transit.path)}
        stops = sorted(transit.stations, key=lambda s: order[s.node])
        halls, platforms = {}, {}
        for s in stops:
            key = sub._key(s.node)
            hall, platform = f'subway_hall_{key}', f'subway_platform_{key}'
            halls[s.id], platforms[s.id] = hall, platform

            def in_hall(a, c, z, s=s):
                return at(*s.point(s.centre + a, c), z)

            f = s.hall_floor
            node(hall, 'station_hall', at(s.x, s.y, f), 4 * sub.HALL[0] * s.side_half, -2)
            area = sum(c1 - c0 for c0, c1 in s.platforms()) * sub.STATION
            node(platform, 'platform', at(s.x, s.y, s.track + sub.PLATFORM_HEIGHT), area, -4)
            stairs = []
            for sign, across, bottom, steps, rise in s.stairs():
                top = bottom + sign * steps * sub.STAIR[2]
                x, y = s.point(top, across)
                link(hall, platform, 'stair', sub.STAIR[0], at(x, y, f), height=_r(f - s.track))
                stairs.extend(at(*s.point(bottom, across), s.track + sub.PLATFORM_HEIGHT) + at(x, y, f))
            entrances = []
            for e in s.entrances:
                head = s.point(e.start + e.sign * e.run, sum(e.across) / 2)
                street = f'street_{e.id}'
                node(street, 'street', at(*head, e.top), 0.0, 0)
                width = e.across[1] - e.across[0]
                link(hall, street, 'stair', width, at(*head, e.top), height=_r(e.top - e.floor))
                foot = s.point(e.start, sum(e.across) / 2)
                x0, y0, x1, y1 = sub._entrance_surface(s, e)
                entrances.append({'id': e.id, 'street': street, 'foot': at(*foot, e.floor), 'head': at(*head, e.top),
                                  'width': _r(width), 'place': e.place, 'facing': axis_dir(s.axis, e.sign),
                                  'opening': _flat([at(x0, y0, e.top), at(x1, y1, e.top)])})
            accesses = []
            for a in s.accesses:
                t = a.tunnel
                wall = s.line + (s.side_half + sub.HALL_SHELL) * a.side
                x, y = (t.line, wall) if s.axis == 'x' else (wall, t.line)
                link(f'{a.site}/{a.room}', hall, 'door', passages.DOOR[0], at(x, y, f), ladder=a.drop is not None)
                entry = {'id': a.id, 'building': a.site, 'room': a.room, 'length': _r(t.length), 'storey': a.storey,
                         'drop': a.drop is not None, 'ladder_bottom': [], 'ladder_top': [], 'ladder_facing': []}
                if a.drop is not None:
                    from .sewers import DROP
                    _, far, zs, zb, _ = a.drop
                    face = far - a.side * DROP[1]
                    entry['ladder_bottom'] = at(*_across(t, a.along, face), zs)
                    entry['ladder_top'] = at(*_across(t, a.along, face), zb)
                    entry['ladder_facing'] = self.space.direction(*((0.0, -a.side) if t.axis == 'y'
                                                                    else (-a.side, 0.0)))
                accesses.append(entry)
            # The fare lines: fences (game props) with gates either side of a booth.
            fences, gates, booths = [], [], []
            for fare in s.fares:
                for c0, c1 in fare.fences:
                    fences.append({'points': _flat([in_hall(fare.at, c0, f), in_hall(fare.at, c1, f)]),
                                   'height': _r(sub.FENCE)})
                for c0, c1 in fare.gates:
                    gates.append({'position': in_hall(fare.at, (c0 + c1) / 2, f), 'width': _r(c1 - c0),
                                  'facing': axis_dir(s.axis, fare.sign)})
                booths.append({'id': f'{s.id}_booth_{"a" if fare.sign > 0 else "b"}',
                               'position': in_hall(fare.at, fare.booth, f), 'width': _r(sub.BOOTH[0]),
                               'depth': _r(sub.BOOTH[1]), 'height': _r(sub.BOOTH[2]),
                               'facing': axis_dir(s.axis, fare.sign)})
            rooms, fixtures = [], []
            if s.baths is not None:
                b = s.baths
                depth = s.side_half - abs(b.c0) - sub.PARTITION
                for k, (r0, r1) in enumerate(b.rooms()):
                    ident = f'{s.id}_bathroom_{k}'
                    middle = in_hall((r0 + r1) / 2, b.c0 + b.side * (sub.PARTITION + depth / 2), f)
                    door = in_hall(r0 + .6 + sub.SMALL_DOOR[0] / 2, b.c0, f)
                    node(ident, 'bathroom', middle, (r1 - r0) * depth, -2)
                    link(hall, ident, 'door', sub.SMALL_DOOR[0], door)
                    rooms.append({'id': ident, 'kind': 'bathroom', 'position': middle, 'length': _r(r1 - r0),
                                  'width': _r(depth), 'height': _r(sub.HALL[1]), 'door': door})
                for kind, a, c, facing in sub.stall_fixtures(s):
                    direction = (0.0, float(facing)) if s.axis == 'x' else (float(facing), 0.0)
                    fixtures.append({'type': kind, 'position': in_hall(a, c, f),
                                     'facing': self.space.direction(*direction)})
            links = []
            for item in s.links:
                chain = [hall] + [room.id for room in item.rooms] + [item.chamber]
                spots = [self._link_door(s, item, at)] + [at(*self._room_face(room, item), room.floor)
                                                          for room in item.rooms]
                for room in item.rooms:
                    node(room.id, 'service', at(room.x, room.y, room.floor), 4 * room.hx * room.hy, -2)
                for (a, b), position in zip(zip(chain, chain[1:]), spots):
                    link(a, b, 'door', sub.SERVICE_DOOR[0], position)
                links.append({'id': item.id, 'chamber': item.chamber, 'kind': item.kind,
                              'rooms': [{'id': r.id, 'position': at(r.x, r.y, r.floor), 'width': _r(2 * r.hx),
                                         'depth': _r(2 * r.hy), 'height': _r(r.height)} for r in item.rooms]})
            self.subway['stations'].append({
                'id': s.id, 'kind': s.kind, 'hall': hall, 'platform': platform, 'position': at(s.x, s.y, s.track),
                'forward': axis_dir(s.axis, s.heading), 'length': _r(sub.STATION),
                'box_length': _r(2 * s.half_length), 'platform_width': _r(s.platforms()[0][1] - s.platforms()[0][0]),
                'platform_height': _r(sub.PLATFORM_HEIGHT), 'track_offset': _r(s.track_offset),
                'track_width': _r(sub.LINE[0]), 'hall_floor': _r(f + oz), 'hall_length': _r(2 * sub.HALL[0]),
                'hall_width': _r(2 * s.side_half), 'stairs': stairs, 'entrances': entrances, 'accesses': accesses,
                'fences': fences, 'gates': gates, 'booths': booths, 'rooms': rooms, 'fixtures': fixtures,
                'links': links})
        # The line between stations: one node per run.
        runs = {}
        for run in transit.runs:
            frames = run.frames()
            middle = frames[len(frames) // 2]
            node(run.id, 'subway', at(*middle[:3]), run.length * sub.LINE[0], -4)
            for station in (run.a, run.b):
                link(run.id, platforms[station.id], 'subway', sub.LINE[0], at(*middle[:3]))
            for piece in run.pieces:
                runs[id(piece)] = run.id
        for u in transit.utilities:
            run = runs[id(u.piece)]
            x, y = u.piece.point(u.along, u.across)
            node(u.id, 'utility', at(x, y, u.floor), u.size ** 2, -4)
            dx, dy = u.piece.point(u.along, u.piece.left * sub.LINE[0] / 2)
            link(run, u.id, 'door', passages.WIDTH, at(dx, dy, u.floor))
            entry = {'id': u.id, 'kind': u.kind, 'position': at(x, y, u.floor), 'size': _r(u.size), 'exit': ''}
            if u.exit is not None:
                m = u.exit
                street = f'street_{m.id}'
                node(street, 'street', at(m.x, m.y, m.rim), 0.0, 0)
                link(u.id, street, 'shaft', SHAFT_SIZE, at(m.x, m.y, m.rim), height=_r(m.rim - u.floor), open=m.open)
                self.manholes.append({'id': m.id, 'chamber': u.id, 'street': street, 'position': at(m.x, m.y, m.rim),
                                      'bottom': at(m.x, m.y, u.floor), 'size': _r(SHAFT_SIZE), 'shape': 'octagon',
                                      'depth': _r(m.rim - u.floor), 'open': m.open, 'kind': 'exit'})
                entry['exit'] = m.id
            self.subway['utilities'].append(entry)
        plugs = {sw.id: sw.plug for sw in (network.sewers if network is not None else ())}
        for r in transit.risers:
            run = runs[id(r.piece)]
            plug = plugs.get(r.sewer)
            sewer_node = r.sewer if plug is None else r.sewer + (':a' if r.along < plug[0] else ':b')
            face = r.far - r.side * sub.RISER[1]
            bottom = at(*r.piece.point(r.along, face), r.floor)
            top = at(*r.piece.point(r.along, face), r.top_floor)
            facing = (0.0, -float(r.side)) if r.piece.axis == 'x' else (-float(r.side), 0.0)
            link(run, sewer_node, 'shaft', passages.WIDTH, top, height=_r(r.top_floor - r.floor), ladder=True)
            self.subway['risers'].append({'id': r.id, 'sewer': sewer_node, 'ladder_bottom': bottom,
                                          'ladder_top': top, 'ladder_facing': self.space.direction(*facing)})
        # The line: its centre and both tracks at the track bed, end to end; its curves.
        points = []
        for kind_, item in [('s', stops[0])] + [x for run in transit.runs for x in (('r', run), ('s', run.b))]:
            if kind_ == 's':
                points.append(at(item.x, item.y, item.track))
            else:
                points.extend(at(*f[:3]) for f in item.frames())
        left, right = sub.tracks(transit)
        curves = [{'id': b.id, 'radius': _r(b.radius), 'centre': at(b.cx, b.cy, (b.z0 + b.z1) / 2),
                   'length': _r(b.length)} for b in transit.bends]
        self.subway['lines'].append({'id': 'line_1', 'stations': [s.id for s in stops], 'points': _flat(points),
                                     'tracks': [{'id': 'line_1_left', 'points': _flat(at(*p) for p in left)},
                                                {'id': 'line_1_right', 'points': _flat(at(*p) for p in right)}],
                                     'curves': curves, 'width': _r(sub.LINE[0]), 'height': _r(sub.LINE[1])})

    @staticmethod
    def _link_door(station, item, at):
        """Where a service link comes through a hall's wall: the doorway's
        middle at the hall's floor."""
        from . import subway as sub
        side, sign = item.wall[0], 1 if item.wall[1] == '+' else -1
        if side == 'a':
            x, y = station.point(station.centre + sign * (sub.HALL[0] + sub.HALL_SHELL / 2), item.coordinate)
        else:
            x, y = station.point(station.centre + item.coordinate, sign * (station.side_half + sub.HALL_SHELL / 2))
        return at(x, y, station.hall_floor)

    @staticmethod
    def _room_face(room, item):
        """The doorway out of a service room on its far side (towards the
        chamber): its plan point."""
        side = item.toward.replace('-', '#').replace('+', '-').replace('#', '+')
        if side[1] == 'x':
            return (room.x + (room.hx if side[0] == '+' else -room.hx), room.y)
        return (room.x, room.y + (room.hy if side[0] == '+' else -room.hy))

    def _interior(self, facts):
        """Rooms, lifts and railings in building space."""
        if not self.interiors:
            return {'rooms': [], 'lifts': [], 'railings': []}
        local, normal = self.space.local, self.space.local_direction
        rooms = []
        for room in facts.get('rooms', ()):
            x0, y0, x1, y1 = room['rect']
            z = room['z']
            rooms.append({
                'name': room['name'], 'kind': room['kind'], 'floor': room['floor'],
                'layer': room.get('layer', ''),
                'unit': room['unit'], 'group': room['group'],
                'position': local(((x0 + x1) / 2, (y0 + y1) / 2, z)),
                'width': _r(x1 - x0), 'depth': _r(y1 - y0), 'height': _r(room['height']),
                'standing': room['standing'], 'ceiling': room['ceiling'],
                'doors': [{'position': local((d['x'], d['y'], z)), 'normal': normal(*d['normal']),
                           'width': _r(d['width']), 'height': _r(d['height']), 'to': d['to']}
                          for d in room['doors']],
                'windows': [{'position': local((w['x'], w['y'], z + w['sill'])),
                             'normal': normal(*w['normal']), 'width': _r(w['width']),
                             'sill': _r(w['sill']), 'head': _r(w['head']), 'broken': w['broken']}
                            for w in room['windows']],
                'wall_runs': [{'start': local(run['start'] + (z,)), 'end': local(run['end'] + (z,)),
                               'normal': normal(*run['normal'])} for run in room['wall_runs']]})
        lifts = []
        for lift in facts.get('lifts', ()):
            x0, y0, x1, y1 = lift['rect']
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            car = lift['car']
            lifts.append({
                'name': lift['name'], 'position': local((cx, cy, lift['bottom'])),
                'width': _r(x1 - x0), 'depth': _r(y1 - y0),
                'height': _r(lift['top'] - lift['bottom']), 'floors': list(lift['floors']),
                'doors': [{'floor': d['floor'], 'position': local((d['x'], d['y'], d['z'])),
                           'normal': normal(*d['normal']), 'width': _r(d['width']),
                           'height': _r(d['height'])} for d in lift['doors']],
                'car': {'floor': car['floor'], 'position': local((cx, cy, car['z'])),
                        'width': _r(x1 - x0), 'depth': _r(y1 - y0), 'height': _r(car['height'])}})
        railings = [{'kind': rail['kind'], 'floor': rail['floor'],
                     'points': _flat(local(p) for p in rail['points']),
                     'height': _r(rail['height'])} for rail in facts.get('railings', ())]
        return {'rooms': rooms, 'lifts': lifts, 'railings': railings}

    # -- collection ------------------------------------------------------
    def add_lot(self, lot, obj_name, entrances=(), height=None, enterable_floors=None,
                interior=None, structure='NONE', footprint=('RECT', None)):
        """``structure``: the recipe's (PARTITIONS, BEARING or NONE) for a lot
        without a fitted interior; a fitted one is listed as FITTED.
        ``footprint``: the recipe's (shape, wings in building coordinates)."""
        entry = {'id': lot.id, 'object': obj_name, 'kind': 'building', 'style': lot.style,
                 'district': lot.district, 'condition': lot.condition, 'floors': lot.floors,
                 'damage': _r(lot.damage), 'interiors': lot.interiors,
                 'structure': 'FITTED' if lot.interiors else structure,
                 'party_walls': list(lot.party_walls), 'group': lot.group or '', 'seed': lot.seed}
        entry.update(self._building(self.lot_transform(lot), lot.width, lot.depth, entrances,
                                    interior, obj_name))
        shape, wings = footprint
        entry['footprint'] = shape
        # Two opposite corners of each wing at ground level, in building space.
        entry['wings'] = _flat(self.space.local((x - lot.width / 2, y - lot.depth / 2, 0.0))
                               for wing in (wings or ((0.0, 0.0, lot.width, lot.depth),))
                               for x, y in ((wing[0], wing[1]), (wing[2], wing[3])))
        entry['height'] = _r(height or 0.0)
        entry['enterable_floors'] = int(enterable_floors or 0)
        self.buildings.append(entry)

    def add_site(self, poi, site, grounds_name, buildings=()):
        """``buildings``: (SiteBuilding, object name, entrances, height,
        enterable floors[, interior facts]) for each building made."""
        site_t = self.poi_transform(poi)
        fx, fy = turn(site_t, 0.0, -1.0)
        entry = {'id': poi.id, 'object': grounds_name, 'kind': site.kind, 'variant': site.variant,
                 'condition': poi.condition, 'district': poi.district, 'seed': poi.seed,
                 'width': _r(poi.width), 'depth': _r(poi.depth), 'buildings': []}
        entry.update(self.space.pose(apply(site_t, 0.0, 0.0, 0.0), fx, fy))
        for building, name, entrances, height, floors, *rest in buildings:
            t = chain(site_t, (building.x, building.y, 0.0, building.quarter * math.pi / 2))
            item = {'object': name, 'role': building.role, 'name': building.name,
                    'floors': building.params['floors'], 'height': _r(height or 0.0),
                    'enterable_floors': int(floors or 0)}
            item.update(self._building(t, building.params['width'], building.params['depth'],
                                       entrances, rest[0] if rest else None, name, poi.id))
            entry['buildings'].append(item)
        self.sites.append(entry)
        for marker in site.markers:
            self.markers.append(self._marker(marker, site_t, poi.id))

    def add_yard(self, yard, site, obj_name):
        """A courtyard or estate grounds (``sites.compose_yard``) and its
        markers (trees, benches, lamps, play equipment)."""
        ox, oy, oz = self.origin
        transform = (ox + yard.center[0], oy + yard.center[1], oz + self.curb + yard.level, 0.0)
        entry = {'id': yard.id, 'object': obj_name, 'kind': yard.kind, 'variant': site.variant,
                 'district': yard.district, 'seed': yard.seed,
                 'width': _r(yard.width), 'depth': _r(yard.depth)}
        entry.update(self.space.pose(apply(transform, 0.0, 0.0, 0.0), 0.0, -1.0))
        self.yards.append(entry)
        for marker in site.markers:
            self.markers.append(self._marker(marker, transform, yard.id))

    def add_shelter(self, shelter, obj_name):
        ox, oy, oz = self.origin
        t = (ox + shelter.position[0], oy + shelter.position[1], oz + self.curb + shelter.level,
             shelter.rotation)
        fx, fy = turn(t, 0.0, -1.0)
        entry = {'id': shelter.id, 'object': obj_name, 'variant': shelter.variant,
                 'road': _flat(shelter.road)}
        entry.update(self.space.pose(apply(t, 0.0, 0.0, 0.0), fx, fy))
        self.stops.append(entry)

    def _marker(self, marker, transform, site_id):
        kind = marker['type']
        # Small props and water have a mesh only when the city was made with
        # them; trees, fences, flagpoles and parked cars never do.
        entry = {'type': kind, 'site': site_id,
                 'modelled': (kind in SMALL_PROPS and self.props_modelled or
                              kind == 'water' and self.water)}
        if kind == 'fence':
            entry['points'] = _flat(self.space.point(apply(transform, x, y, marker['z']))
                                    for x, y in marker['points'])
            entry['height'] = marker['height']
            return entry
        fx, fy = turn(transform, *marker['facing'])
        entry.update(self.space.pose(apply(transform, marker['x'], marker['y'], marker['z']), fx, fy))
        for key, value in marker.items():
            if key in ('type', 'x', 'y', 'z', 'facing', 'points'):
                continue
            if key == 'barrier':
                entry['barrier'] = self.space.direction(*turn(transform, *value))
            elif isinstance(value, tuple):
                entry[key] = [_r(v) for v in value]
            else:
                entry[key] = value
        return entry

    def _terraces(self, node_point):
        """Terraces (their blocks and rise), ramps (their junctions, top
        first) and stairs (top and foot, at the footways' edge)."""
        found = getattr(self.plan, 'terraces', None) or {}
        if not found:
            return [], [], []
        from .streets import stair_layout
        space = self.space
        ox, oy, oz = self.origin
        regions = [{tuple(c) for c in region['cells']} for region in found['regions']]
        from .streets import DECK_DEPTH, RAMP_REACH, viaducts
        terraces = [{'id': f'terrace_{k}', 'kind': region['kind'], 'rise': region['step'],
                     'blocks': _flat(sorted(tuple(c) for c in region['cells'])),
                     'slope_blocks': _flat(sorted(
                         {tuple(c) for s in region.get('slopes', ()) for c in s['cells']} |
                         {tuple(c['cell']) for c in region.get('corners', ())}))}
                    for k, region in enumerate(found['regions'])]
        size = self.plan.settings.block_size
        decks = viaducts(self.plan)

        def point(x, y, z):
            return space.point((ox + x, oy + y, oz + z))
        ramps = []
        for k, ramp in enumerate(found['ramps']):
            nodes = [tuple(n) for n in ramp['nodes']]
            rows = [(a[0] * size, a[1] * size, b[0] * size, b[1] * size)
                    for a, b in zip(nodes, nodes[1:])]

            def on_ramp(x, y):
                return min(_segment_distance(x, y, r) for r in rows) < RAMP_REACH
            spans = [d for d in decks
                     if on_ramp(*d['stations'][len(d['stations']) // 2][1])]
            ramps.append({'id': f'ramp_{k}', 'terrace': _terrace_of(regions, nodes[0]),
                          'nodes': _flat(ramp['nodes']),
                          'points': _flat(node_point(n) for n in ramp['nodes']),
                          'viaducts': [{'start': point(*d['stations'][0][1],
                                                       d['stations'][0][5] + DECK_DEPTH),
                                        'end': point(*d['stations'][-1][1],
                                                     d['stations'][-1][5] + DECK_DEPTH),
                                        'piers': _flat(point(*c, foot)
                                                       for c, _, foot, _ in d['piers'])}
                                       for d in spans]})
        stairs = []
        for k, (stair, layout) in enumerate(zip(found['stairs'], stair_layout(self.plan))):
            (hx, hy), (ux, uy) = layout['origin'], layout['direction']
            top = (hx + ux * layout['top'], hy + uy * layout['top'], layout['z_top'])
            foot = (hx + ux * layout['bottom'], hy + uy * layout['bottom'], layout['z_bottom'])
            stairs.append({'id': f'stair_{k}', 'terrace': _terrace_of(regions, tuple(stair['high'])),
                           'top': space.point((ox + top[0], oy + top[1], oz + top[2])),
                           'bottom': space.point((ox + foot[0], oy + foot[1], oz + foot[2])),
                           'width': stair['width'], 'steps': layout['steps'],
                           'riser': _r(layout['riser'])})
        return terraces, ramps, stairs

    def _ditches(self):
        return _ditch_lists(self.plan, self.space, self.origin)

    def _freeway(self, node_point):
        """A raised highway: its deck's centreline, interchanges, ramps (from
        the cross street, at grade, to where the lane has joined the deck) and
        pier feet; None for one at grade."""
        freeway = getattr(self.plan, 'freeway', None) or {}
        if not freeway:
            return None
        from .streets import freeway_stations
        space = self.space
        ox, oy, oz = self.origin

        def point(x, y, z):
            return space.point((ox + x, oy + y, oz + z))
        built = freeway_stations(self.plan)
        ramps = []
        for k, ramp in enumerate(freeway['ramps']):
            (tx, ty), _ = ramp['tail']
            line = [point(tx, ty, ramp['base'])] + [point(*p) for p in ramp['points']]
            ramps.append({'id': f'freeway_ramp_{k}', 'kind': ramp['kind'],
                          'interchange': freeway['interchanges'].index(ramp['node'][0]),
                          'side': 'north' if ramp['side'] > 0 else 'south',
                          'width': 2 * freeway['ramp_half'],
                          'climb': ramp['length'], 'taper': ramp['taper'],
                          'points': _flat(line)})
        return {'width': 2 * freeway['half'],
                'interchanges': [{'node': [x, 0], 'position': node_point((x, 0))}
                                 for x in freeway['interchanges']],
                'mainline': _flat(point(x, 0.0, z) for x, z in freeway['mainline']),
                'touchdown': _flat(point(x, 0.0, z) for x, z in (freeway['mainline'][0],
                                                                 freeway['mainline'][-1])),
                'ramps': ramps,
                'piers': _flat(point(x, y, foot) for x, y, _, _, foot, *_ in built['piers'])}

    # -- output ----------------------------------------------------------
    def as_dict(self):
        plan, space = self.plan, self.space
        settings = plan.settings
        size = settings.block_size
        ox, oy, oz = self.origin
        surface = plan.surface()

        def node_point(node):
            x, y = node[0] * size, node[1] * size
            return space.point((ox + x, oy + y, oz + surface(x, y)))
        junctions = {}
        for road in plan.roads:
            for node in (road.a, road.b):
                junctions.setdefault(node, []).append(road.width / 2)
        degree = {}
        for road in plan.roads:
            for node in (road.a, road.b):
                degree[node] = degree.get(node, 0) + 1
        # A cul-de-sac's turning circle sets its junction radius.
        for bulb in getattr(plan, 'culdesacs', ()):
            junctions.setdefault(tuple(bulb['node']), []).append(bulb['radius'])
        rural = {tuple(sorted((tuple(a), tuple(b)))) for a, b in getattr(plan, 'rural', ())}
        roads = [{'id': path['id'], 'tier': path['tier'], 'width': path['width'],
                  'nodes': _flat(path['nodes']),
                  'points': _flat(space.point((ox + x, oy + y, oz + surface(x, y)))
                                  for x, y in path['points']),
                  'rural_edges': [k for k, (a, b) in enumerate(zip(path['nodes'], path['nodes'][1:]))
                                  if tuple(sorted((tuple(a), tuple(b)))) in rural]}
                 for path in plan.paths]
        ditches, culverts = self._ditches()
        bulbs = {tuple(bulb['node']) for bulb in getattr(plan, 'culdesacs', ())}
        terraces, ramps, stairs = self._terraces(node_point)
        markers = sorted(self.markers, key=lambda m: m['type'])
        counts = {}
        for marker in markers:
            counts[marker['type']] = counts.get(marker['type'], 0) + 1
        extent = settings.radius * size
        return {
            'format': FORMAT, 'schema': SCHEMA, 'addon_version': self.addon_version,
            'plan_version': _plan_version(), 'collection': self.collection,
            'space': space.describe(),
            'city': {'preset': settings.preset, 'shape': settings.shape, 'seed': settings.seed,
                     'origin': space.point(self.origin),
                     'extent': _r(extent), 'block_size': size,
                     'wasteland': settings.wasteland, 'curb_height': settings.curb_height,
                     'sidewalk_width': settings.sidewalk_width,
                     'small_props_modelled': self.props_modelled,
                     'interiors_listed': self.interiors, 'water_modelled': self.water,
                     'terrain': settings.terrain, 'relief': settings.relief,
                     'rural_streets': settings.rural_streets,
                     'wild_extent': _r((settings.radius + getattr(plan, 'wild', 0)) * size
                                       if getattr(plan, 'wild', 0) else 0.0),
                     'plateau_height': settings.plateau_height, 'podiums': settings.podiums,
                     'highway': settings.highway},
            'underground': _graph_facts(self.under_nodes, self.under_links),
            'tunnels': self.tunnels,
            'sewers': self.sewers,
            'manholes': self.manholes,
            'breaches': self.breaches,
            'subway': self.subway,
            'districts': [{'id': loc.id, 'role': loc.role, 'style': loc.style,
                           'position': node_point(loc.node)} for loc in plan.locations],
            'roads': roads,
            'junctions': [{'node': list(node), 'position': node_point(node),
                           'radius': _r(max(halves) + settings.sidewalk_width),
                           'roads': degree[node], 'cul_de_sac': node in bulbs}
                          for node, halves in sorted(junctions.items())],
            'driving_loops': [{'id': loop.get('id', f'loop_{k}'),
                               'nodes': _flat(loop['nodes']),
                               'tiers': list(loop.get('tiers', ())),
                               'length_m': loop.get('length_m', 0.0)}
                              for k, loop in enumerate(plan.driving_loops)],
            'outer_roads': [{'id': road['id'], 'width': road['width'],
                             'start': space.point((ox + road['start'][0], oy + road['start'][1], oz)),
                             'forward': space.direction(*road['direction']),
                             'length': road['length'], 'fade': road['fade']}
                            for road in getattr(plan, 'outer_roads', ())],
            'terraces': terraces,
            'ramps': ramps,
            'stairs': stairs,
            'freeway': self._freeway(node_point),
            'ditches': ditches,
            'culverts': culverts,
            'buildings': self.buildings,
            'sites': self.sites,
            'yards': self.yards,
            'transit_stops': self.stops,
            'markers': markers,
            'counts': {'buildings': len(self.buildings), 'sites': len(self.sites),
                       'yards': len(self.yards), 'ditches': len(ditches),
                       'culverts': len(culverts),
                       'transit_stops': len(self.stops),
                       'markers': [{'type': kind, 'count': count}
                                   for kind, count in sorted(counts.items())]},
        }


def _ditch_lists(plan, space, origin):
    """The rural streets' ditches (along each one's bottom) and the culverts
    where they end (at the bottom of each headwall's face, facing into the
    ditch)."""
    from .streets import DITCH_DEPTH, DITCH_WIDTH, GROUND_Z, Grading, ditches
    found = ditches(plan)
    if not found:
        return [], []
    grading = Grading(plan) if plan.heights else None
    ox, oy, oz = origin

    def point(ditch, along, across):
        x, y = (along, across) if ditch.axis == 0 else (across, along)
        z = (grading.ground(x, y) if grading else GROUND_Z) - DITCH_DEPTH
        return space.point((ox + x, oy + y, oz + z))

    def direction(ditch, along, across):
        return space.direction(*((along, across) if ditch.axis == 0 else (across, along)))
    listed, culverts = [], []
    for k, ditch in enumerate(found):
        ends = [point(ditch, a, ditch.bottom) for a in (ditch.start, ditch.end)]
        listed.append({'id': f'ditch_{k}', 'start': ends[0], 'end': ends[1],
                       'width': DITCH_WIDTH, 'depth': DITCH_DEPTH,
                       'outward': direction(ditch, 0.0, float(ditch.side))})
        for end, sign in ((ends[0], 1.0), (ends[1], -1.0)):
            culverts.append({'id': f'culvert_{len(culverts)}', 'ditch': f'ditch_{k}',
                             'position': end, 'facing': direction(ditch, sign, 0.0)})
    return listed, culverts


def _segment_distance(px, py, row):
    x0, y0, x1, y1 = row
    dx, dy = x1 - x0, y1 - y0
    t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - x0 - dx * t, py - y0 - dy * t)


def _terrace_of(regions, node):
    """The terrace whose top a junction is on (any corner of its blocks)."""
    x, y = node
    around = {(x - 1, y - 1), (x, y - 1), (x - 1, y), (x, y)}
    return next((f'terrace_{k}' for k, cells in enumerate(regions) if around & cells), None)


def _plan_version():
    from . import city_plan
    return city_plan.VERSION
