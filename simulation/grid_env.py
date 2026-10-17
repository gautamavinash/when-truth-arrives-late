"""
16x16 grid environment matching the paper's experimental setup.
Cells are either free or obstacles. Boundary cells are always walls.
"""

import random


DEFAULT_OBSTACLES_16x16 = [
    (1, 3), (1, 9), (2, 6), (3, 1), (3, 12),
    (4, 7), (5, 4), (5, 10), (6, 2), (6, 14),
    (7, 8), (8, 5), (9, 11), (10, 3), (10, 13),
    (11, 6), (12, 1), (12, 9), (13, 4), (14, 7),
]  # 20 obstacles (paper uses 18; adjust via constructor)


class GridEnv:
    def __init__(self, size=16, obstacles=None):
        self.size = size
        self.obstacle_set = set()
        obs = obstacles if obstacles is not None else DEFAULT_OBSTACLES_16x16[:18]
        for (r, c) in obs:
            if 0 <= r < size and 0 <= c < size:
                self.obstacle_set.add((r, c))

    def in_bounds(self, r, c):
        return 0 <= r < self.size and 0 <= c < self.size

    def is_obstacle(self, r, c):
        return not self.in_bounds(r, c) or (r, c) in self.obstacle_set

    def is_wall(self, r, c, global_visited):
        """
        A cell is a wall if it is:
          - out of bounds (boundary)
          - a static obstacle
          - already visited by any robot
        """
        if not self.in_bounds(r, c):
            return True
        if (r, c) in self.obstacle_set:
            return True
        if (r, c) in global_visited:
            return True
        return False

    def free_cells(self):
        return [
            (r, c)
            for r in range(self.size)
            for c in range(self.size)
            if (r, c) not in self.obstacle_set
        ]

    def total_free(self):
        return len(self.free_cells())

    def random_free_starts(self, n, seed=42):
        rng = random.Random(seed)
        free = self.free_cells()
        if n > len(free):
            raise ValueError(f"Cannot place {n} robots in {len(free)} free cells")
        return rng.sample(free, n)
