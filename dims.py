# SPDX-License-Identifier: GPL-3.0-or-later
"""Dimensions the generator designs to, derived from the Ares player.

Player (the Ares Player.prefab):
capsule 2.0 m tall, 0.8 m wide, 0.08 m skin, 0.4 m step offset, 45 degree
slope limit. The game's reference doorway is 2.2 x 1.2 m. Spaces are sized for
that capsule with gameplay margins, not for a 1.8 m real-world occupant.
"""

PLAYER_HEIGHT = 2.0
PLAYER_WIDTH = .8
PLAYER_SKIN = .08

# Openings
DOOR_WIDTH = 1.2          # Interior door clear width; 0.8 capsule + skin passes easily.
DOOR_HEIGHT = 2.3         # Clear height above the finished floor.
EXTERIOR_DOOR_MIN = 1.4   # Street doors.
ENTRANCE_WIDTH = 2.6      # Main entrance of large buildings (double doors).
LINTEL = .3               # Minimum wall above any opening, below the slab.
MIN_PIER = .45            # Minimum solid wall between openings.

# Circulation
CORRIDOR = 1.8            # Clear corridor width (< 1.2 feels tight in game).
STAIR_FLIGHT = 1.3        # Clear width of one flight.
STAIR_WELL = .15          # Gap between switchback flights.
STAIR_RISER = .19         # Maximum riser (the player's step offset is 0.4).
STAIR_TREAD = .27         # Tread depth.
STAIR_LANDING = 1.3       # Landing depth at each end of a switchback.
STAIR_WAIST = .3         # Stair flight soffit, measured down from the tread below.
STAIR_LANDING_SLAB = .25  # Turning landing thickness.
ELEVATOR_SHAFT = (2.4, 2.4)

# Structure
SLAB = .25                # Floor slab thickness.
ROOF_SLAB = .3
PARTITION = .15           # Interior wall thickness.
CORE_WALL = .25           # Stair/elevator core wall thickness.
GROUND_SLAB = .1          # Ground-floor slab, sunk into the foundation.

# Rooms
MIN_ROOM = 2.4            # Smallest room side.
MIN_BATH = 1.9
