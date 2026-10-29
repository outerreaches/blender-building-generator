# SPDX-License-Identifier: GPL-3.0-or-later
"""Architecture recipes shared by city assets and the standalone style operator.

Each style is a district archetype, not only a palette. Dimensions follow the
Ares player (dims.py) and real buildings: ground floors are taller than the
storeys above, doors clear the 2.0 m capsule, and windows sit at believable
sill and head heights. Towers vary by seed in lobby, facade system, massing
(podium and setbacks) and crown.
"""
import random
import zlib

STYLE_ITEMS = [
    ('DOWNTOWN', 'Downtown Tower', 'Office towers: lobbies, curtain walls, setbacks and crowns'),
    ('OLD_TOWN', 'Old Town / Masonry', 'Thick masonry, tall windows, shopfronts and cornices'),
    ('RESIDENTIAL', 'Residential', 'Apartment blocks with regular windows and parapets'),
    ('BRUTALIST', 'Brutalist', 'Deep concrete grids, often lifted on columns'),
    ('INDUSTRIAL', 'Industrial', 'Wide sheds, high window bands and loading doors'),
    ('SUBURBAN', 'Suburban House', 'Small pitched-roof houses set back from the street'),
]
INTERIOR_PROFILE = {
    'DOWNTOWN': 'OFFICE',
    'OLD_TOWN': 'STOREFRONT',
    'RESIDENTIAL': 'RESIDENTIAL',
    'BRUTALIST': 'OFFICE',
    'INDUSTRIAL': 'WAREHOUSE',
    'SUBURBAN': 'HOUSE',
}
STYLE_CONDITIONS = ('INTACT', 'WEATHERED', 'SEMI_COLLAPSED', 'RUBBLE_FILLED',
                    'PARTIAL_FILLED', 'LOWER_FLOORS', 'SHELL', 'WALL_RING',
                    'COLLAPSED')
STYLE_COLORS = {'DOWNTOWN': (.42, .47, .52, 1), 'OLD_TOWN': (.48, .30, .20, 1),
                'RESIDENTIAL': (.62, .58, .44, 1), 'BRUTALIST': (.48, .48, .46, 1),
                'INDUSTRIAL': (.32, .39, .42, 1), 'SUBURBAN': (.66, .55, .42, 1)}
LOBBIES = ('GRAND', 'RETAIL', 'ARCADE', 'PILOTIS')


def _pick(rng, weighted):
    roll = rng.uniform(0, sum(weight for _, weight in weighted))
    for value, weight in weighted:
        roll -= weight
        if roll <= 0:
            return value
    return weighted[-1][0]


def building_recipe(style, width, depth, floors, seed, damage=0, interiors=False,
                    condition='INTACT'):
    if style not in STYLE_COLORS:
        raise ValueError(f'Unknown building style: {style}')
    rng = random.Random((seed * 69069) ^ zlib.crc32(style.encode()) ^ 0x57E1)
    profile = dict(
        width=width, depth=depth, floors=floors, floor_height=3.3,
        wall_thickness=.3, window_type='RECTANGULAR',
        window_width=1.4, window_height=1.6, window_spacing=1.0, sill_height=.85,
        window_sides='ALL', ground_floor_windows='REGULAR',
        storefront_window_width=2.2, storefront_window_height=2.6, storefront_sill_height=.4,
        door_width=1.4, door_height=2.4, front_door_offset=.5,
        back_exit=True, back_door_offset=.5,
        flat_roof=True, floor_slabs=True,
        facade_pilasters=False, pilaster_width=.35, pilaster_depth=.15,
        pilaster_style='CORNERS', pilaster_sides='FRONT',
        roof_parapet=True, parapet_height=.6,
        has_patio=False,
        building_profile=INTERIOR_PROFILE.get(style, 'RESIDENTIAL') if interiors else 'NONE',
        skyscraper=style == 'DOWNTOWN',
        exterior_stairs=False, interior_fill='NONE', exterior_rubble=False,
        enable_damage=damage > 0, damage_amount=damage,
        damage_pointiness=.4, damage_resolution=1.0,
        seed=seed, auto_clean=True, mark_uv_seams=True,
        roof_kind='FLAT', roof_height=0.0, roof_overhang=0.0, roof_box=None,
        lobby='NONE', facade_system='PUNCHED', cornice=False,
    )
    profile['ground_floor_height'] = profile['floor_height']
    if style == 'DOWNTOWN':
        system = _pick(rng, (('CURTAIN', 4), ('RIBBON', 3.5), ('PUNCHED', 2.5)))
        lobby = _pick(rng, (('GRAND', 3.5), ('RETAIL', 3), ('ARCADE', 2), ('PILOTIS', 1.5)))
        ground = {'GRAND': rng.uniform(6.4, 7.8), 'RETAIL': rng.uniform(4.8, 5.4),
                  'ARCADE': rng.uniform(5.2, 6.0), 'PILOTIS': rng.uniform(5.0, 5.8)}[lobby]
        profile.update(floor_height=3.9, ground_floor_height=ground, wall_thickness=.3,
                       window_width=2.4 if system != 'PUNCHED' else 1.8,
                       window_height=1.8, window_spacing=.55 if system != 'PUNCHED' else .9,
                       sill_height=.8, facade_system=system, lobby=lobby,
                       ground_floor_windows='STOREFRONT', door_width=2.4, door_height=2.8,
                       entrance_width=3.2, parapet_height=.9,
                       roof_box=(rng.uniform(.3, .45), rng.uniform(.25, .4), rng.uniform(3.0, 4.5)),
                       crown=_pick(rng, (('NONE', 3), ('STEPPED', 2), ('MAST', 2 if floors >= 14 else 0))),
                       mechanical_every=12 if floors >= 14 else 0)
        setbacks = []
        if floors >= 10 and width >= 18 and depth >= 18:
            # Podium of 2-4 storeys, tower set back above it.
            podium = rng.randint(2, min(4, floors - 6))
            inset = rng.uniform(2.4, 4.0)
            back = inset if rng.random() < .5 else 0.0
            setbacks.append((podium, (inset, inset, inset, back)))
            if floors >= 18 and min(width, depth) - 2 * inset >= 18:
                setbacks.append((int(floors * rng.uniform(.62, .78)), (2.0, 2.0, 2.0, 2.0)))
        profile['setbacks'] = setbacks
    elif style == 'OLD_TOWN':
        profile.update(floor_height=3.6, ground_floor_height=4.2, wall_thickness=.45,
                       window_type='TALL', window_width=1.4, window_height=1.6, sill_height=.8,
                       window_spacing=1.1, ground_floor_windows='STOREFRONT',
                       storefront_window_height=2.8, storefront_sill_height=.45,
                       door_width=1.4, door_height=2.6, facade_pilasters=True,
                       pilaster_style=rng.choice(('CORNERS', 'BETWEEN_WINDOWS')),
                       parapet_height=.5, cornice=True)
    elif style == 'RESIDENTIAL':
        profile.update(floor_height=3.2, ground_floor_height=3.4, window_width=1.4,
                       window_height=1.6, sill_height=.85, window_spacing=1.1,
                       cornice=rng.random() < .5, parapet_height=.5)
    elif style == 'BRUTALIST':
        lobby = 'PILOTIS' if rng.random() < .35 and floors >= 4 else 'NONE'
        profile.update(floor_height=3.3, ground_floor_height=4.2 if lobby == 'PILOTIS' else 3.6,
                       wall_thickness=.45, sill_height=1.0, parapet_height=.9,
                       window_width=1.6, window_height=1.4, window_spacing=1.2,
                       facade_system='GRID', lobby=lobby)
    elif style == 'INDUSTRIAL':
        profile.update(floor_height=5.5, ground_floor_height=5.5, wall_thickness=.3,
                       window_width=2.4, window_height=1.2, window_spacing=1.2,
                       sill_height=3.2, door_width=3.6, door_height=4.0, roof_parapet=False,
                       building_profile='WAREHOUSE' if interiors else 'NONE')
    elif style == 'SUBURBAN':
        profile.update(floor_height=3.1, ground_floor_height=3.1, wall_thickness=.25,
                       window_width=1.2, window_height=1.4, window_spacing=1.2, sill_height=.9,
                       door_width=1.2, door_height=2.4, roof_parapet=False,
                       flat_roof=False, roof_kind='GABLE', roof_height=2.4,
                       roof_overhang=.5)
    if condition == 'RUBBLE_FILLED':
        profile.update(interior_fill='FILLED', building_profile='NONE',
                       chunk_cut=True, expose_fill=True)
    elif condition == 'PARTIAL_FILLED':
        profile.update(interior_fill='PARTIAL',
                       fill_floors=max(1, min(3, floors // 3 + 1)),
                       building_profile='NONE', chunk_cut=True, expose_fill=True)
    elif condition == 'SHELL':
        profile.update(flat_roof=False, floor_slabs=True,
                       building_profile='NONE', roof_parapet=False, roof_box=None,
                       chunk_cut=True, crown=None)
    elif condition == 'SEMI_COLLAPSED':
        profile.update(chunk_cut=True)
    elif condition == 'LOWER_FLOORS':
        profile.update(damage_amount=1.0, enable_damage=True,
                       damage_cap_height=profile['floor_height'] * 2.6)
    elif condition == 'COLLAPSED':
        profile.update(building_profile='NONE', interior_fill='NONE')
    elif condition == 'WALL_RING':
        profile.update(floors=min(floors, 4), flat_roof=False, floor_slabs=False,
                       roof_parapet=False, building_profile='NONE', setbacks=[],
                       interior_mound=True, chunk_cut=False, roof_box=None, lobby='NONE',
                       roof_kind='FLAT')
    if condition in ('RUBBLE_FILLED', 'PARTIAL_FILLED', 'SHELL', 'WALL_RING',
                     'COLLAPSED'):
        profile['building_profile'] = 'NONE'
    if (condition == 'WEATHERED' and floors >= 10 and
            random.Random(seed ^ 0x5EED).random() < .55):
        # Tall weathered towers lose a piece, but stay recognisably standing.
        profile['chunk_cut'] = True
        profile['collapse'] = random.Random(seed ^ 0x5EEE).choice(
            ('SAWTOOTH', 'BLOWOUT', 'BLOWOUT', 'CORNER'))
    margin = 2 * (profile['wall_thickness'] + .35)
    module = profile['window_width'] + profile['window_spacing']
    profile['windows_per_floor'] = max(1, int(round((width - margin) / module)))
    profile['ground_floor_window_count'] = max(1, int((width - 3) / 3))
    return profile
