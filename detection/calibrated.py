"""
Population-relative (noise-calibrated) delay detector.

The original DelayDetector uses fixed absolute thresholds (mean delay > 1.0,
variance > 0.5, cumulative sequence gaps >= 3) that only make sense on a
noiseless channel. This detector instead calibrates to the honest-delay
distribution that the receiver itself observes:

  * Each receiver keeps the last `window` delays of every sender it hears.
  * Sender j's score is the mean of its window. The reference is the median of
    all senders' window means (robust while fewer than half the senders are
    compromised), and the noise scale is the median per-sender delay standard
    error, so the test automatically widens as channel jitter grows.
  * A sender is suspicious when its score exceeds the reference by more than
    k * max(scale, scale_floor) + delta for `persist` consecutive messages.

Same interface as DelayDetector (observe / _suspicious / _detection_time), so it
plugs into the existing simulator variant machinery and ConsensusDetector.
"""

import math
from collections import defaultdict, deque
from typing import Dict


class CalibratedDetector:
    def __init__(
        self,
        receiver_id: int,
        window: int = 10,
        k: float = 4.0,
        delta: float = 0.25,
        persist: int = 3,
        min_samples: int = 5,
        scale_floor: float = 0.05,
        min_senders: int = 3,
        loo: bool = False,
        **_ignored,          # accepts (and ignores) the shared constructor kwargs, e.g. alpha
    ):
        self.receiver_id = receiver_id
        self.window = window
        self.k = k
        self.delta = delta
        self.persist = persist
        self.min_samples = min_samples
        self.scale_floor = scale_floor
        self.min_senders = min_senders   # warm-up: no test until this many senders have min_samples delays
        self.loo = loo                   # leave-one-out: exclude the tested sender from the population reference

        self._delays: Dict[int, deque] = defaultdict(lambda: deque(maxlen=window))
        self._streak: Dict[int, int] = defaultdict(int)
        self._suspicious: Dict[int, bool] = {}
        self._detection_time: Dict[int, int] = {}
        self._stats_step = None
        self._ref = (0.0, 0.0)

    # -- population statistics, recomputed once per time step --------------------
    def _population(self, exclude=None):
        means, ses = [], []
        for sid, dq in self._delays.items():
            if sid == exclude:
                continue
            n = len(dq)
            if n < self.min_samples:
                continue
            m = sum(dq) / n
            var = sum((x - m) ** 2 for x in dq) / n
            means.append(m)
            ses.append(math.sqrt(var) / math.sqrt(n))
        if len(means) < self.min_senders:
            return None
        means.sort()
        ses.sort()
        mid = len(means) // 2
        med = means[mid] if len(means) % 2 else 0.5 * (means[mid - 1] + means[mid])
        mids = len(ses) // 2
        scale = ses[mids] if len(ses) % 2 else 0.5 * (ses[mids - 1] + ses[mids])
        return med, scale

    def observe(self, sender_id: int, seq_num: int, generated_at: int, received_at: int):
        delay = received_at - generated_at
        self._delays[sender_id].append(delay)

        if self.loo:
            ref = self._population(exclude=sender_id)
        else:
            if self._stats_step != received_at:
                self._ref = self._population()
                self._stats_step = received_at
            ref = self._ref
        if ref is None:
            return
        med, scale = ref

        dq = self._delays[sender_id]
        if len(dq) < self.min_samples:
            return
        score = sum(dq) / len(dq)
        exceed = score - med > self.k * max(scale, self.scale_floor) + self.delta

        self._streak[sender_id] = self._streak[sender_id] + 1 if exceed else 0
        suspected = self._streak[sender_id] >= self.persist
        if suspected and sender_id not in self._detection_time:
            self._detection_time[sender_id] = received_at
        self._suspicious[sender_id] = suspected
