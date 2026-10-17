"""
Stealth (adaptive) delay attacker: each outgoing message is delayed by a fixed `delay_steps` with probability
`p`, otherwise sent on time. A small delay and/or a small p keep the attacker's delay statistics close to the
honest ones, trading damage for stealth. Same intercept/flush interface as the SLA/BLA proxies.
"""
import random


class StealthDelayAttacker:
    def __init__(self, delay_steps: int = 1, p: float = 0.25, seed: int = 0):
        self.delay_steps, self.p = delay_steps, p
        self.rng = random.Random(seed)
        self._queue = []          # (release_at, msg)

    def intercept(self, msg, current_step: int) -> None:
        d = self.delay_steps if self.rng.random() < self.p else 0
        self._queue.append((current_step + d, msg))

    def flush(self, current_step: int):
        ready = [m for r, m in self._queue if r <= current_step]
        self._queue = [(r, m) for r, m in self._queue if r > current_step]
        for m in ready:
            m.received_at = current_step
        return ready
