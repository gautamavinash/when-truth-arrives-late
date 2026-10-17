"""
Sequential-Lag Attack (SLA)

The compromised robot buffers outgoing messages and releases them one-by-one,
each separated by a fixed inter-release interval λ (lambda_steps).

Formal model from the paper:
    t'_i = t_i + i * λ

where t_i is the generation time of the i-th message and t'_i is its actual
transmission time. Messages are released from a FIFO queue sequentially.
"""

from collections import deque
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class DelayedMessage:
    msg: object          # the original Message object
    release_at: int      # simulation step at which to release


class SequentialLagAttacker:
    """
    Wraps a robot's outbound message queue and injects sequential delays.

    Usage (simulation):
        attacker = SequentialLagAttacker(lambda_steps=3)
        delayed_msgs = attacker.intercept(msg, current_step)
        to_send = attacker.flush(current_step)
    """

    def __init__(self, lambda_steps: int = 3, buffer_size: Optional[int] = None):
        """
        Parameters
        ----------
        lambda_steps : int
            Fixed inter-release delay (in simulation steps) between messages.
        buffer_size : int or None
            Maximum buffer before a forced drain (None = unbounded queue, the default). A forced
            drain delivers every queued message at once; earlier versions discarded them, which
            turned SLA into a message-suppression attack.
        """
        self.lambda_steps = lambda_steps
        self.buffer_size = buffer_size
        self._queue: deque[DelayedMessage] = deque()
        self._release_cursor = 0   # next release time for sequential scheduling
        self._t_first: Optional[int] = None
        self._ready: List = []

    def intercept(self, msg, current_step: int) -> None:
        """
        Accept a message from the compromised robot. Schedule it for delayed
        release.  Does NOT send immediately.
        """
        if self._t_first is None:
            self._t_first = current_step
            self._release_cursor = current_step + self.lambda_steps

        # Each subsequent message released lambda_steps after the previous
        self._queue.append(DelayedMessage(msg=msg, release_at=self._release_cursor))
        self._release_cursor += self.lambda_steps

        # If buffer full, force immediate drain (safety)
        if self.buffer_size is not None and len(self._queue) >= self.buffer_size:
            self._force_drain(current_step)

    def flush(self, current_step: int) -> List:
        """
        Return messages whose scheduled release time has arrived.
        Call once per simulation step.
        """
        ready, self._ready = self._ready, []
        while self._queue and self._queue[0].release_at <= current_step:
            dm = self._queue.popleft()
            dm.msg.received_at = current_step   # stamp actual delivery time
            ready.append(dm.msg)

        if not self._queue:
            self._t_first = None

        return ready

    def _force_drain(self, current_step: int):
        """Release everything immediately (buffer overflow safety valve)."""
        for dm in self._queue:
            dm.msg.received_at = current_step
            self._ready.append(dm.msg)
        self._queue.clear()
        self._t_first = None
        self._release_cursor = 0

    @property
    def buffered(self) -> int:
        return len(self._queue)
