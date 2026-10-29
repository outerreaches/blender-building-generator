# SPDX-License-Identifier: GPL-3.0-or-later
"""Building spec: storeys, massing tiers and facade layouts from parameters.

Pure Python. Coordinates are building-local: x along the front (0..width),
y towards the back (0..depth), z up from the ground-floor surface. Facades
run counter-clockwise seen from above (front, right, back, left); each
facade's u starts at its own start corner and its outward normal is
direction x up.

Facades use a bay grid: windows sit centred in bays, doors take whole bays and
interior walls may only meet the facade at bay boundaries (piers), so
partitions never land on a window.
"""
import math
import random
from dataclasses import dataclass, field

from . import dims
from .meshdata import MAT_DOOR_FRAME, MAT_WALLS, MAT_WINDOW_FRAME
from .solids import Opening

SIDES = ('front', 'right', 'back', 'left')
WINDOW_SIDES = {
    'ALL': SIDES,
    'FRONT_BACK': ('front', 'back'),
    'FRONT_SIDES': ('front', 'left', 'right'),
    'FRONT_ONLY': ('front',),
    'FRONT_LEFT': ('front', 'left'),
    'FRONT_RIGHT': ('front', 'right'),
    'BACK_SIDES': ('back', 'left', 'right'),
    'SIDES_ONLY': ('left', 'right'),
    'NONE': (),
}


@dataclass
class Level:
    index: int
    z: float          # Finished floor surface.
    height: float     # Floor to floor.
    kind: str         # GROUND, TYPICAL or MECHANICAL.
    rect: tuple       # Outer footprint (x0, y0, x1, y1) of this storey.

    @property
    def ceiling(self):
        return self.z + self.height


@dataclass
class Facade:
    side: str
    tier: int
    origin: tuple
    direction: tuple
    length: float     # Corner to corner along the outer face.
    ua: float         # Extent of the wall solid along u.
    ub: float
    base: float
    top: float
    bays: list = field(default_factory=list)   # Bay boundaries (pier centres) in u.
    openings: list = field(default_factory=list)
    segments: list = field(default_factory=list)  # (ua, ub, top): wall pieces along u.

    def point(self, u):
        return (self.origin[0] + self.direction[0] * u, self.origin[1] + self.direction[1] * u)

    @property
    def normal(self):
        return (self.direction[1], -self.direction[0])


@dataclass
class Tier:
    first: int
    last: int
    rect: tuple
    base: float
    top: float
    facades: list = field(default_factory=list)


def _contains(outer, inner, eps=1e-6):
    return (outer[0] <= inner[0] + eps and outer[1] <= inner[1] + eps and
            outer[2] >= inner[2] - eps and outer[3] >= inner[3] - eps)


class BuildingSpec:
    """Everything about a building's form, before any geometry is made."""

    def __init__(self, params):
        self.params = params
        p = params
        self.width = float(p['width'])
        self.depth = float(p['depth'])
        self.floors = max(1, int(p['floors']))
        self.floor_height = float(p['floor_height'])
        self.t = float(p.get('wall_thickness', .25))
        self.slab = float(p.get('slab_thickness', dims.SLAB))
        self.roof_slab = float(p.get('roof_thickness', dims.ROOF_SLAB))
        self.seed = int(p.get('seed', 0))
        self.rng = random.Random((self.seed * 7919) ^ 0x5BEC)
        self.has_slabs = p.get('floor_slabs', True)
        self.roof_kind = self._roof_kind()
        self.parapet = (float(p.get('parapet_height', .5))
                        if self.roof_kind == 'FLAT' and p.get('roof_parapet', False) else 0.0)
        self.lobby = p.get('lobby', 'NONE')
        self.facade_system = p.get('facade_system', 'PUNCHED')
        # Sides built against a neighbour (row and block buildings): blank and
        # without projecting details wherever the wall stands on the lot line.
        self.party = frozenset(p.get('party_walls', ()) or ())
        self.levels = self._levels()
        self.top = self.levels[-1].ceiling      # Roof surface / eaves.
        self.tiers = self._tiers()
        self.columns = []                       # (x, y, size, z0, z1) free-standing columns.
        self.door_overrides = None
        # Explicit street doors [(side, centre, width[, height])] for designed
        # buildings (bay doors, shop units); the interior planner may replace them.
        self.base_doors = p.get('doors')
        for index, tier in enumerate(self.tiers):
            tier.facades = self._facades(index, tier)
        self._segment_shared_lines()
        self._place_columns()
        self.build_openings()

    def build_openings(self, doors=None):
        """Cut windows and doors into every facade.

        ``doors`` optionally replaces the ground-floor street doors with the
        planner's choice: a list of (side, centre, width) in building space.
        """
        self.door_overrides = doors if doors is not None else self.base_doors
        for tier in self.tiers:
            for facade in tier.facades:
                facade.openings = []
                for level in self.levels[tier.first:tier.last + 1]:
                    facade.openings.extend(self._openings(facade, level, tier))

    # -- storeys ---------------------------------------------------------
    def _roof_kind(self):
        kind = self.params.get('roof_kind', 'FLAT')
        if kind in ('GABLE', 'HIP', 'MANSARD'):
            return kind
        return 'FLAT' if self.params.get('flat_roof', True) else 'NONE'

    def _levels(self):
        p = self.params
        ground = float(p.get('ground_floor_height', self.floor_height))
        every = int(p.get('mechanical_every', 0) or 0)
        levels = []
        z = 0.0
        full = (0.0, 0.0, self.width, self.depth)
        for index in range(self.floors):
            height = ground if index == 0 else self.floor_height
            kind = 'GROUND' if index == 0 else 'TYPICAL'
            if every and index > 0 and index % every == 0 and index < self.floors - 1:
                kind = 'MECHANICAL'
            levels.append(Level(index, z, height, kind, full))
            z += height
        for level in levels:
            level.rect = self._level_rect(level, levels)
        return levels

    def _level_rect(self, level, levels):
        p = self.params
        x0, y0, x1, y1 = 0.0, 0.0, self.width, self.depth
        top_index = len(levels) - 1
        if level.index == 0 and self.lobby == 'ARCADE' and len(levels) > 1:
            y0 = float(p.get('arcade_depth', 2.8))
        if level.index == 0 and self.lobby == 'PILOTIS' and len(levels) > 1:
            inset = float(p.get('pilotis_inset', 3.0))
            x0, y0, x1, y1 = x0 + inset, y0 + inset, x1 - inset, y1 - inset
        for start, insets in p.get('setbacks', ()) or ():
            if level.index >= start:
                left, front, right, back = insets
                x0, y0, x1, y1 = x0 + left, y0 + front, x1 - right, y1 - back
        if (p.get('has_patio', False) and len(levels) >= 2 and level.index == top_index):
            side = p.get('patio_side', 'BACK')
            size = float(p.get('patio_size', .4))
            if side == 'BACK':
                y1 = min(y1, self.depth * (1 - size))
            elif side == 'FRONT':
                y0 = max(y0, self.depth * size)
            elif side == 'LEFT':
                x0 = max(x0, self.width * size)
            else:
                x1 = min(x1, self.width * (1 - size))
        minimum = 2 * self.t + 3.0
        if x1 - x0 < minimum or y1 - y0 < minimum:
            return levels[level.index - 1].rect if level.index else (0.0, 0.0, self.width, self.depth)
        return (x0, y0, x1, y1)

    def _tiers(self):
        tiers = []
        for level in self.levels:
            if tiers and tiers[-1].rect == level.rect:
                tiers[-1].last = level.index
            else:
                tiers.append(Tier(level.index, level.index, level.rect, 0.0, 0.0))
        for index, tier in enumerate(tiers):
            first = self.levels[tier.first]
            if index == 0:
                tier.base = -dims.GROUND_SLAB
            else:
                below = tiers[index - 1].rect
                # An overhanging storey wraps the slab edge it stands on.
                tier.base = first.z - self.slab if (_contains(tier.rect, below) and tier.rect != below) else first.z
            if index + 1 < len(tiers):
                above = tiers[index + 1]
                z_next = self.levels[above.first].z
                if _contains(tier.rect, above.rect):
                    tier.top = z_next + float(self.params.get('terrace_parapet', 1.05))
                else:
                    tier.top = z_next - self.slab
            else:
                tier.top = self.top + self.parapet
        return tiers

    # -- facades ---------------------------------------------------------
    def _facades(self, tier_index, tier):
        x0, y0, x1, y1 = tier.rect
        t = self.t
        w, d = x1 - x0, y1 - y0
        lines = (('front', (x0, y0), (1.0, 0.0), w, 0.0, w),
                 ('right', (x1, y0), (0.0, 1.0), d, t, d - t),
                 ('back', (x1, y1), (-1.0, 0.0), w, 0.0, w),
                 ('left', (x0, y1), (0.0, -1.0), d, t, d - t))
        facades = []
        for side, origin, direction, length, ua, ub in lines:
            facade = Facade(side, tier_index, origin, direction, length, ua, ub,
                            tier.base, tier.top)
            facade.bays = self._bays(side, length)
            if tier_index > 0:
                inherited = self._inherited_bays(facade)
                if inherited:
                    facade.bays = inherited
            facades.append(facade)
        return facades

    def _segment_shared_lines(self):
        """Stop a terrace parapet where the storey above continues the same wall.

        Where the tier above stands on the same facade line (a patio or a
        one-sided setback), the lower wall ends at that storey's floor and the
        upper wall carries on; only the open terrace keeps its parapet.
        """
        for index, tier in enumerate(self.tiers):
            for facade in tier.facades:
                facade.segments = [(facade.ua, facade.ub, facade.top)]
            if index + 1 >= len(self.tiers):
                continue
            above = self.tiers[index + 1]
            if not _contains(tier.rect, above.rect):
                continue
            z_next = self.levels[above.first].z
            ax0, ay0, ax1, ay1 = above.rect
            for facade in tier.facades:
                axis = 0 if facade.side in ('front', 'back') else 1
                line = facade.origin[1 - axis]
                edge = {'front': ay0, 'back': ay1, 'left': ax0, 'right': ax1}[facade.side]
                if abs(line - edge) > 1e-6:
                    continue
                lo, hi = (ax0, ax1) if axis == 0 else (ay0, ay1)
                start = facade.origin[axis]
                sign = 1 if (facade.direction[0] + facade.direction[1]) > 0 else -1
                a, b = sorted((sign * (lo - start), sign * (hi - start)))
                a, b = max(a, facade.ua), min(b, facade.ub)
                if b - a < 1e-6:
                    continue
                pieces = []
                if a > facade.ua + 1e-6:
                    pieces.append((facade.ua, a, facade.top))
                pieces.append((a, b, z_next))
                if b < facade.ub - 1e-6:
                    pieces.append((b, facade.ub, facade.top))
                facade.segments = pieces

    def _inherited_bays(self, facade):
        """The base tier's piers that fall on this (inset) facade, as u values."""
        base = next(f for f in self.tiers[0].facades if f.side == facade.side)
        axis = 0 if facade.side in ('front', 'back') else 1
        start = facade.point(0)[axis]
        sign = 1 if (facade.direction[0] + facade.direction[1]) > 0 else -1
        margin = self.t + .3
        bays = sorted(sign * (base.point(u)[axis] - start) for u in base.bays)
        bays = [u for u in bays if margin - 1e-6 <= u <= facade.length - margin + 1e-6]
        if len(bays) < 2:
            return None
        widest = max(b - a for a, b in zip(bays, bays[1:]))
        return bays if widest > dims.MIN_PIER + .6 else None

    def _module(self):
        p = self.params
        width = self._window_size()[0]
        return width + max(float(p.get('window_spacing', .8)), dims.MIN_PIER)

    def _bays(self, side, length):
        """Bay boundaries across a facade, symmetric about its middle."""
        p = self.params
        margin = self.t + .35
        usable = length - 2 * margin
        if usable < 1.0:
            return [length / 2 - .5, length / 2 + .5] if length > 1.2 else [0.0, length]
        module = self._module()
        fit = max(1, int((usable + 1e-6) // max(1.0, self._window_size()[0] + dims.MIN_PIER)))
        if side in ('front', 'back') and p.get('windows_per_floor'):
            count = int(p['windows_per_floor'])
        else:
            count = max(1, int(round(usable / module)))
        count = max(1, min(count, fit))
        bay = usable / count
        return [margin + bay * index for index in range(count + 1)]

    def _window_size(self):
        p = self.params
        width = float(p.get('window_width', 1.2))
        height = float(p.get('window_height', 1.4))
        kind = p.get('window_type', 'RECTANGULAR')
        if kind == 'TALL':
            width, height = width * .75, height * 1.3
        elif kind == 'SQUARE':
            height = width
        return width, height

    def _clear_height(self, level):
        """Highest opening head on a storey (keeps a lintel under the slab)."""
        return level.height - self.slab - dims.LINTEL

    def is_party(self, facade, tier=None):
        """True for a facade standing on a party wall (on the lot line of a
        party side); set-back storeys above it keep their windows."""
        if facade.side not in self.party:
            return False
        rect = (tier or self.tiers[facade.tier]).rect
        edge = {'left': rect[0], 'front': rect[1], 'right': rect[2] - self.width,
                'back': rect[3] - self.depth}[facade.side]
        return abs(edge) < 1e-6

    def _openings(self, facade, level, tier):
        if self.is_party(facade, tier):
            return []
        p = self.params
        bays = facade.bays
        count = len(bays) - 1
        chosen = p.get('window_sides', 'ALL')
        # A tuple of side names (designed buildings) or a WINDOW_SIDES key.
        sides = tuple(chosen) if isinstance(chosen, (tuple, list)) else WINDOW_SIDES.get(chosen, SIDES)
        windowed = facade.side in sides
        result = []
        doors = self._doors(facade, level, tier) if level.index == tier.first else []
        taken = set()
        for first_bay, last_bay, width, height, kind in doors:
            u0, u1 = bays[first_bay], bays[last_bay + 1]
            centre = (u0 + u1) / 2
            frame = MAT_DOOR_FRAME
            result.append(Opening.rect(centre - width / 2, centre + width / 2, level.z,
                                       level.z + min(height, self._clear_height(level)),
                                       frame, kind))
            taken.update(range(first_bay, last_bay + 1))
        if level.kind == 'MECHANICAL':
            return self._extra_openings(facade, level, result)
        if level.index == 0 and tier.first == 0:
            sill, head, width, glazed = self._ground_glazing(facade, level, windowed)
        elif windowed:
            sill, head, width, glazed = self._upper_glazing(facade, level)
        else:
            return self._extra_openings(facade, level, result)
        for bay in glazed:
            if bay in taken or bay >= count:
                continue
            u0, u1 = bays[bay], bays[bay + 1]
            span = min(width, u1 - u0 - dims.MIN_PIER)
            if span < .4 or head - sill < .4:
                continue
            centre = (u0 + u1) / 2
            result.append(Opening.rect(centre - span / 2, centre + span / 2,
                                       level.z + sill, level.z + head, MAT_WINDOW_FRAME))
        return self._extra_openings(facade, level, result)

    def _extra_openings(self, facade, level, result):
        """Designed openings (drive-thru windows, hatches) replace what they overlap."""
        extras = [e for e in self.params.get('extra_openings', ()) or ()
                  if e['side'] == facade.side and
                  level.z - 1e-6 <= level.z + e.get('z0', 1.0) < level.ceiling]
        axis = 0 if facade.side in ('front', 'back') else 1
        for extra in extras:
            u = abs(extra['centre'] - facade.point(0)[axis])
            u0, u1 = u - extra['width'] / 2, u + extra['width'] / 2
            if u0 < facade.ua + .3 or u1 > facade.ub - .3:
                continue
            z0 = level.z + extra.get('z0', 1.0)
            z1 = min(z0 + extra['height'], level.ceiling - self.slab - dims.LINTEL)
            if z1 - z0 < .4:
                continue
            result = [o for o in result if not (o.u0 < u1 + .2 and o.u1 > u0 - .2)]
            frame = MAT_DOOR_FRAME if extra.get('kind') == 'door' else MAT_WINDOW_FRAME
            result.append(Opening.rect(u0, u1, z0, z1, frame, extra.get('kind', 'window')))
        return result

    def _upper_glazing(self, facade, level):
        p = self.params
        width, height = self._window_size()
        sill = float(p.get('sill_height', .9))
        clear = self._clear_height(level)
        system = self.facade_system
        bays = facade.bays
        widest = max(b - a for a, b in zip(bays, bays[1:]))
        if system == 'OPEN':
            # Parking decks: open from a 1.05 m upstand to the beam.
            width = widest
            sill = 1.05
            head = clear
        elif system == 'RIBBON':
            width = widest
            sill = max(.75, sill)
            head = min(clear, sill + max(height, 1.5))
        elif system == 'CURTAIN':
            width = widest
            sill = .1
            head = clear
        elif system == 'GRID':
            head = min(clear, sill + height)
        else:
            head = min(clear, sill + height)
        if head - sill < .6:
            sill = max(.2, head - max(.6, height))
        return sill, head, width, range(len(bays) - 1)

    def _ground_glazing(self, facade, level, windowed):
        p = self.params
        mode = p.get('ground_floor_windows', 'REGULAR')
        bays = facade.bays
        count = len(bays) - 1
        clear = self._clear_height(level)
        if self.lobby in ('GRAND', 'ARCADE', 'PILOTIS') or (
                self.lobby == 'RETAIL' and facade.side == 'front'):
            # Lobby glazing: tall, nearly floor to ceiling, wrapping the corners.
            reach = count if facade.side == 'front' else min(count, 2)
            if facade.side in ('right', 'left') and self.lobby != 'PILOTIS':
                glazed = range(count - reach, count) if facade.side == 'left' else range(reach)
            elif facade.side == 'back' and self.lobby != 'PILOTIS':
                glazed = range(0)
            else:
                glazed = range(count)
            widest = max(b - a for a, b in zip(bays, bays[1:]))
            return .15, clear, widest, glazed
        if mode == 'OPEN' and windowed:
            return self._upper_glazing(facade, level)
        if mode in ('STOREFRONT', 'STOREFRONT_WIDE') and facade.side == 'front':
            sill = float(p.get('storefront_sill_height', .3))
            head = min(clear, sill + float(p.get('storefront_window_height', 2.2)))
            if mode == 'STOREFRONT_WIDE':
                width = max(b - a for a, b in zip(bays, bays[1:]))
                glazed = range(count)
            else:
                width = float(p.get('storefront_window_width', 2.0))
                wanted = max(1, int(p.get('ground_floor_window_count', count)))
                glazed = _spread(count, wanted)
            return sill, head, width, glazed
        if mode == 'NONE' or not windowed:
            return 0.0, 0.0, 0.0, range(0)
        sill, head, width, glazed = self._upper_glazing(facade, level)
        return sill, head, width, glazed

    def _doors(self, facade, level, tier):
        """Doors on this facade for the first storey of a tier: (bay0, bay1, w, h, kind)."""
        p = self.params
        bays = facade.bays
        count = len(bays) - 1
        result = []
        if level.index == 0 and self.door_overrides is not None:
            height = float(p.get('door_height', 2.4))
            axis = 0 if facade.side in ('front', 'back') else 1
            for item in self.door_overrides:
                side, centre, width = item[:3]
                if side != facade.side:
                    continue
                offset = facade.point(0)[axis]
                u = abs(centre - offset)
                result.append(self._door_bays(facade, u / facade.length, width,
                                              item[3] if len(item) > 3 else height, 'door'))
        elif level.index == 0:
            width = float(p.get('door_width', 1.2))
            height = float(p.get('door_height', 2.4))
            if facade.side == 'front':
                if self.lobby != 'NONE':
                    width = max(width, float(p.get('entrance_width', dims.ENTRANCE_WIDTH)))
                result.append(self._door_bays(facade, float(p.get('front_door_offset', .5)),
                                              width, height, 'door'))
            elif facade.side == 'back' and p.get('back_exit', True):
                # back_door_offset is measured along x from the left corner.
                offset = 1.0 - float(p.get('back_door_offset', .5))
                result.append(self._door_bays(facade, offset, width, height, 'door'))
            elif (p.get('exterior_stairs', False) and facade.side == 'left'):
                result.append(self._door_bays(facade, .7, dims.EXTERIOR_DOOR_MIN, 2.4, 'door'))
        elif p.get('has_patio', False) and level.index == len(self.levels) - 1:
            side = {'BACK': 'back', 'FRONT': 'front', 'LEFT': 'left', 'RIGHT': 'right'}[
                p.get('patio_side', 'BACK')]
            if facade.side == side and count >= 1:
                width = float(p.get('patio_door_width', 1.5))
                result.append(self._door_bays(facade, .5, width, dims.DOOR_HEIGHT + .1, 'door'))
        return [door for door in result if door is not None]

    def _door_bays(self, facade, offset, width, height, kind):
        bays = facade.bays
        count = len(bays) - 1
        if count < 1:
            return None
        target = facade.length * offset
        needed = width + dims.MIN_PIER
        best = None
        for span in range(1, count + 1):
            for first in range(0, count - span + 1):
                if bays[first + span] - bays[first] + 1e-6 < needed:
                    continue
                centre = (bays[first] + bays[first + span]) / 2
                score = abs(centre - target)
                if best is None or score < best[0] - 1e-6:
                    best = (score, first, first + span - 1)
            if best is not None:
                break
        if best is None:
            first, last = 0, count - 1
            width = min(width, bays[-1] - bays[0] - dims.MIN_PIER)
        else:
            _, first, last = best
        return first, last, max(.9, width), height, kind

    def _place_columns(self):
        """Arcade and pilotis columns on the outer line under an overhang."""
        if len(self.levels) < 2 or self.lobby not in ('ARCADE', 'PILOTIS'):
            return
        ground = self.levels[0]
        upper = self.tiers[1] if len(self.tiers) > 1 else None
        if upper is None:
            return
        size = max(.45, self.t * 1.8)
        z1 = self.levels[1].z - self.slab
        x0, y0, x1, y1 = upper.rect
        front = next(f for f in upper.facades if f.side == 'front')
        positions = [(front.point(u)[0], y0 + size / 2) for u in front.bays[1:-1]]
        positions += [(x0 + size / 2, y0 + size / 2), (x1 - size / 2, y0 + size / 2)]
        if self.lobby == 'PILOTIS':
            for facade in upper.facades:
                if facade.side == 'front':
                    continue
                nx, ny = facade.normal
                for u in facade.bays[1:-1]:
                    px, py = facade.point(u)
                    positions.append((px - nx * size / 2, py - ny * size / 2))
            positions += [(x0 + size / 2, y1 - size / 2), (x1 - size / 2, y1 - size / 2)]
        gx0, gy0, gx1, gy1 = ground.rect
        for x, y in positions:
            # Skip columns that would stand inside the glazed ground storey.
            if gx0 - size < x < gx1 + size and gy0 - size < y < gy1 + size:
                continue
            self.columns.append((x, y, size, -dims.GROUND_SLAB, z1))

    # -- queries used by interiors ---------------------------------------
    def interior_rect(self, level_index):
        x0, y0, x1, y1 = self.levels[level_index].rect
        t = self.t
        return (x0 + t, y0 + t, x1 - t, y1 - t)

    def tier_of(self, level_index):
        for index, tier in enumerate(self.tiers):
            if tier.first <= level_index <= tier.last:
                return index
        return len(self.tiers) - 1

    def piers(self, level_index):
        """Building-space coordinates where partitions may meet each facade.

        Returns {side: [positions]}: x positions on front/back, y on left/right.
        """
        tier = self.tiers[self.tier_of(level_index)]
        level = self.levels[level_index]
        result = {}
        for facade in tier.facades:
            axis = 0 if facade.side in ('front', 'back') else 1
            # A pier swallowed by a wide opening (a two-bay door) is no pier.
            spans = [(o.u0, o.u1) for o in facade.openings
                     if level.z - 1e-6 <= min(z for _, z in o.bottom) < level.ceiling]
            result[facade.side] = sorted(facade.point(u)[axis] for u in facade.bays
                                         if not any(a - .05 < u < b + .05 for a, b in spans))
        return result

    def solid_spans(self, side, levels=None):
        """Stretches of a tier-0 facade free of openings on every given storey.

        Returned in building coordinates (x on front/back, y on the sides).
        """
        facade = self.ground_facade(side)
        axis = 0 if side in ('front', 'back') else 1
        wanted = set(levels) if levels is not None else None
        blocked = []
        # Every tier's openings on this side count: upper tiers (arcades,
        # setbacks, patios) have their own facades.
        for tier in self.tiers:
            other = next(f for f in tier.facades if f.side == side)
            for opening in other.openings:
                z = min(v for _, v in opening.bottom)
                level = next((lv for lv in self.levels if lv.z - 1e-6 <= z < lv.ceiling), None)
                if wanted is not None and (level is None or level.index not in wanted):
                    continue
                a, b = other.point(opening.u0)[axis], other.point(opening.u1)[axis]
                blocked.append((min(a, b), max(a, b)))
        lo = facade.point(facade.ua)[axis]
        hi = facade.point(facade.ub)[axis]
        lo, hi = min(lo, hi), max(lo, hi)
        spans = []
        cursor = lo
        for a, b in sorted(blocked):
            if a > cursor:
                spans.append((cursor, a))
            cursor = max(cursor, b)
        if cursor < hi:
            spans.append((cursor, hi))
        return spans

    def ground_facade(self, side):
        return next(f for f in self.tiers[0].facades if f.side == side)

    def door_bays(self, side):
        """Default ground doors on a side: [(first_bay, last_bay, width, height, kind)]."""
        facade = self.ground_facade(side)
        if self.is_party(facade, self.tiers[0]):
            return []
        saved, self.door_overrides = self.door_overrides, self.base_doors
        try:
            return self._doors(facade, self.levels[0], self.tiers[0])
        finally:
            self.door_overrides = saved

    def door_centre(self, side, door):
        facade = self.ground_facade(side)
        axis = 0 if side in ('front', 'back') else 1
        first, last = door[0], door[1]
        return facade.point((facade.bays[first] + facade.bays[last + 1]) / 2)[axis]

    def entrances(self):
        """Ground-floor exterior doors as (side, centre x/y in building space, width)."""
        result = []
        for facade in self.tiers[0].facades:
            axis = 0 if facade.side in ('front', 'back') else 1
            for opening in facade.openings:
                if opening.kind == 'door' and opening.bottom[0][1] <= 1e-6:
                    centre = facade.point((opening.u0 + opening.u1) / 2)[axis]
                    result.append((facade.side, centre, opening.u1 - opening.u0))
        return result


def _spread(count, wanted):
    """``wanted`` bay indices spread evenly over ``count`` bays."""
    wanted = min(count, wanted)
    if wanted >= count:
        return range(count)
    step = count / wanted
    return sorted({min(count - 1, int(step * index + step / 2)) for index in range(wanted)})
