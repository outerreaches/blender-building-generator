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
        self.stops = []
        self.markers = []

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
        for fixture in (interior or {}).get('fixtures', ()):
            fx_, fy_ = turn(transform, *fixture['facing'])
            marker = {'type': fixture['kind'], 'site': site_id, 'building': obj_name,
                      'floor': fixture['floor'], 'modelled': False}
            marker.update(self.space.pose(apply(transform, fixture['x'], fixture['y'], fixture['z']),
                                          fx_, fy_))
            marker['size'] = [_r(v) for v in fixture['size']]
            self.markers.append(marker)
        return entry

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
                interior=None):
        entry = {'id': lot.id, 'object': obj_name, 'kind': 'building', 'style': lot.style,
                 'district': lot.district, 'condition': lot.condition, 'floors': lot.floors,
                 'damage': _r(lot.damage), 'interiors': lot.interiors,
                 'party_walls': list(lot.party_walls), 'group': lot.group or '', 'seed': lot.seed}
        entry.update(self._building(self.lot_transform(lot), lot.width, lot.depth, entrances,
                                    interior, obj_name))
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
        terraces = [{'id': f'terrace_{k}', 'kind': region['kind'], 'rise': region['step'],
                     'blocks': _flat(sorted(regions[k]))}
                    for k, region in enumerate(found['regions'])]
        ramps = [{'id': f'ramp_{k}', 'terrace': _terrace_of(regions, tuple(ramp['nodes'][0])),
                  'nodes': _flat(ramp['nodes']),
                  'points': _flat(node_point(n) for n in ramp['nodes'])}
                 for k, ramp in enumerate(found['ramps'])]
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
        roads = [{'id': path['id'], 'tier': path['tier'], 'width': path['width'],
                  'nodes': _flat(path['nodes']),
                  'points': _flat(space.point((ox + x, oy + y, oz + surface(x, y)))
                                  for x, y in path['points'])}
                 for path in plan.paths]
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
                     'plateau_height': settings.plateau_height, 'podiums': settings.podiums},
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
            'buildings': self.buildings,
            'sites': self.sites,
            'transit_stops': self.stops,
            'markers': markers,
            'counts': {'buildings': len(self.buildings), 'sites': len(self.sites),
                       'transit_stops': len(self.stops),
                       'markers': [{'type': kind, 'count': count}
                                   for kind, count in sorted(counts.items())]},
        }


def _terrace_of(regions, node):
    x, y = node
    around = {(x - 1, y - 1), (x, y - 1), (x - 1, y), (x, y)}
    return next((f'terrace_{k}' for k, cells in enumerate(regions) if around <= cells), None)


def _plan_version():
    from . import city_plan
    return city_plan.VERSION
