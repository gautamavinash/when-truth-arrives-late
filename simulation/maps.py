"""
Named 16x16 obstacle layouts for the grid-world simulator, giving each map
a topology qualitatively similar to the corresponding real M-TARE
environment, while staying within the abstract grid-world model (the
simulator has no notion of 3D mesh geometry -- these are stand-ins, not
literal reproductions of the M-TARE .world files).
"""

# Tunnel: two long corridor walls offset from each other, forcing an
# S-shaped path through narrow gaps -- mirrors a constrained, linear
# tunnel environment rather than an open area.
TUNNEL_OBSTACLES = (
    [(5, c) for c in range(0, 9)] +
    [(10, c) for c in range(7, 16)]
)

# Garage: a regular grid of single-cell pillars, like support columns in a
# parking structure -- open area, but with periodic structured obstacles.
GARAGE_OBSTACLES = [
    (r, c) for r in (3, 7, 11) for c in (0, 3, 6, 9, 12, 15)
]

# Forest: irregular scattered obstacles with no structural pattern, like
# trees -- open area with no corridors or regular spacing.
FOREST_OBSTACLES = [
    (2, 2), (2, 10), (3, 6), (4, 13), (5, 3), (5, 9),
    (6, 12), (7, 1), (7, 6), (8, 10), (9, 4), (9, 14),
    (10, 7), (11, 2), (11, 11), (12, 5), (13, 9), (14, 3),
]

# Indoor: a building floorplan -- a central cross of walls dividing the grid
# into four rooms, each connected to its neighbors only through narrow
# doorway gaps -- mirrors a compartmentalized indoor space rather than an
# open area.
_INDOOR_DOOR_ROWS = (3, 4, 11, 12)
_INDOOR_DOOR_COLS = (3, 4, 11, 12)
INDOOR_OBSTACLES = sorted(set(
    [(r, 8) for r in range(16) if r not in _INDOOR_DOOR_ROWS] +
    [(8, c) for c in range(16) if c not in _INDOOR_DOOR_COLS]
))

# Campus: several large rectangular building footprints scattered across
# open courtyards/roadways -- mirrors an outdoor campus of buildings
# connected by open ground, as opposed to small point obstacles (forest)
# or a regular pillar grid (garage).
def _rect(r0, r1, c0, c1):
    return [(r, c) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)]


CAMPUS_OBSTACLES = (
    _rect(1, 3, 1, 3) +     # building A
    _rect(1, 4, 8, 10) +    # building B
    _rect(6, 8, 3, 5) +     # building C
    _rect(9, 12, 10, 13) +  # building D
    _rect(12, 14, 1, 3) +   # building E
    _rect(6, 7, 12, 14)     # building F
)

MAPS = {
    "tunnel": TUNNEL_OBSTACLES,
    "indoor": INDOOR_OBSTACLES,
    "garage": GARAGE_OBSTACLES,
    "campus": CAMPUS_OBSTACLES,
    "forest": FOREST_OBSTACLES,
}


def get_map_obstacles(name):
    if name not in MAPS:
        raise ValueError(f"Unknown map '{name}'. Available: {sorted(MAPS.keys())}")
    return MAPS[name]
