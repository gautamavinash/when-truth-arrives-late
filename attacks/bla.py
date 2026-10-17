"""
Bounded-Lag Attack (BLA)

The compromised robot accumulates n messages over a delay window λ
(lambda_steps) and then releases the entire buffer simultaneously as a burst.

Formal model from the paper:
    t'_i = t_i + λ   for all i in {1, ..., n}
    all messages transmitted together at t_burst = t_first + λ

Effect: receivers observe a sudden influx of outdated state messages,
overwhelming local decision logic and causing clustered conflicts.
"""

from collections import deque
from typing import List, Optional


class BoundedLagAttacker:
    """
    Wraps outbound messages and releases them all at once after a time window.

    Usage (simulation):
        attacker = BoundedLagAttacker(lambda_steps=5)
        attacker.intercept(msg, current_step)
        to_send = attacker.flush(current_step)   # returns burst when window expires
    """

    def __init__(self, lambda_steps: int = 5, buffer_size: int = 20):
        """
        Parameters
        ----------
        lambda_steps : int
            Window duration (in simulation steps) before burst release.
        buffer_size : int
            Maximum messages before forced early release.
        """
        self.lambda_steps = lambda_steps
        self.buffer_size = buffer_size
        self._buffer: deque = deque()
        self._t_first: Optional[int] = None
        self._burst_at: Optional[int] = None

    def intercept(self, msg, current_step: int) -> None:
        """Buffer a message. Does NOT release immediately."""
        if self._t_first is None:
            self._t_first = current_step
            self._burst_at = current_step + self.lambda_steps

        self._buffer.append(msg)

        # Force early burst on buffer overflow
        if len(self._buffer) >= self.buffer_size:
            self._burst_at = current_step  # release now on next flush

    def flush(self, current_step: int) -> List:
        """
        Return all buffered messages if the burst window has expired.
        Returns an empty list otherwise.
        """
        if not self._buffer:
            return []

        if self._burst_at is not None and current_step >= self._burst_at:
            burst = list(self._buffer)
            for msg in burst:
                msg.received_at = current_step  # all delivered at same step
            self._buffer.clear()
            self._t_first = None
            self._burst_at = None
            return burst

        return []

    @property
    def buffered(self) -> int:
        return len(self._buffer)

    @property
    def burst_due_at(self) -> Optional[int]:
        return self._burst_at
