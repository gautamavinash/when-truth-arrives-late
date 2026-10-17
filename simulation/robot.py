"""
ORMSTC robot agent.

Each robot builds a Local Spanning Tree (LST) via DFS. It broadcasts its
current position, visited cells, and next intended move. Coordination works
by treating any cell that another robot has visited (or announced as its next
move) as a wall — ensuring non-overlapping coverage.

Movement preference: anti-clockwise (left → up → right → down).
"""

from dataclasses import dataclass, field
from typing import Optional, Tuple, FrozenSet


# Anti-clockwise: left, up, right, down
DIRECTIONS = [(0, -1), (-1, 0), (0, 1), (1, 0)]


@dataclass
class Message:
    robot_id: int
    position: Tuple[int, int]
    visited_cells: FrozenSet[Tuple[int, int]]
    next_move: Optional[Tuple[int, int]]
    generated_at: int       # simulation time step when created
    seq_num: int
    received_at: int = -1   # filled in by the simulator / attack proxy


class ORMSTCRobot:
    def __init__(self, robot_id: int, start: Tuple[int, int], env):
        self.robot_id = robot_id
        self.pos = start
        self.env = env

        self.visited: set = {start}         # cells this robot has visited
        self.lst: list = [start]            # local spanning tree path
        self.dfs_stack: list = [start]      # backtracking stack

        self.next_move: Optional[Tuple] = None
        self.done = False
        self.seq_num = 0

        # Aggregate view built from received broadcasts
        self.known_visited: set = {start}   # own + others' visited + claimed next moves

        self.collisions = 0
        self.redundant = 0

    # ── messaging ────────────────────────────────────────────────────────────

    def make_message(self, timestep: int) -> Message:
        self.seq_num += 1
        return Message(
            robot_id=self.robot_id,
            position=self.pos,
            visited_cells=frozenset(self.visited),
            next_move=self.next_move,
            generated_at=timestep,
            seq_num=self.seq_num,
        )

    def receive(self, msg: Message):
        """Update local knowledge from a received message."""
        self.known_visited.update(msg.visited_cells)
        if msg.next_move is not None:
            self.known_visited.add(msg.next_move)

    # ── planning ─────────────────────────────────────────────────────────────

    def _is_wall(self, r, c) -> bool:
        return self.env.is_wall(r, c, self.known_visited)

    def plan(self):
        """Compute next move using DFS. Call after processing received messages."""
        if self.done:
            self.next_move = None
            return

        # Try each direction from current position
        for dr, dc in DIRECTIONS:
            nr, nc = self.pos[0] + dr, self.pos[1] + dc
            if not self._is_wall(nr, nc):
                self.next_move = (nr, nc)
                return

        # All neighbours are walls → backtrack
        if len(self.dfs_stack) > 1:
            self.dfs_stack.pop()
            self.next_move = self.dfs_stack[-1]
            return

        # DFS complete
        self.done = True
        self.next_move = None

    # ── execution ─────────────────────────────────────────────────────────────

    def move(self, global_visited: set):
        """Execute the planned move (simulator calls this after all robots plan)."""
        if self.done or self.next_move is None:
            return

        target = self.next_move
        self.next_move = None

        if self.env.is_obstacle(*target):
            return  # safety: never enter obstacle

        if target in global_visited and target not in self.visited:
            self.redundant += 1

        if target == self.pos:
            # Backtracking in place — no actual movement needed
            return

        # Collision: another robot is already here this step (detected externally)
        self.pos = target

        if target not in self.visited:
            self.visited.add(target)
            self.lst.append(target)
            if len(self.dfs_stack) == 0 or self.dfs_stack[-1] != target:
                self.dfs_stack.append(target)

        self.known_visited.add(target)

    # ── metrics ───────────────────────────────────────────────────────────────

    @property
    def coverage(self) -> int:
        return len(self.visited)
