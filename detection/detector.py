"""
Distributed Receiver-Centric Delay Attack Detector

Implements the detection framework from:
  "A Distributed Detection Framework for Timing-Based Attacks in Multi-Robot Systems"

Each robot (or robot0 in M-TARE) maintains a local delay history per sender and
detects anomalies across three dimensions:

  1. Temporal consistency   — sustained deviation from expected delay mean/std
  2. Cross-receiver         — same message perceived with inconsistent delay by
                              different receivers (cross-receiver indicator)
  3. Sequence gaps          — missing sequence numbers indicate buffering

Detection decision: majority vote across indicators.
"""

import math
from collections import defaultdict, deque
from typing import Dict, List, Optional, Tuple


class DelayRecord:
    """Tracks delay observations for a single sender."""

    def __init__(self, window: int = 10, alpha: float = 2.0):
        self.window = window        # sliding window size for anomaly density
        self.alpha = alpha          # sensitivity: flag if |d - μ| > α·σ
        self._history: deque = deque(maxlen=200)   # full delay history
        self._anomaly_window: deque = deque(maxlen=window)
        self._last_seq: Optional[int] = None
        self.seq_gap_count = 0

    def record(self, observed_delay: float, seq_num: int) -> bool:
        """
        Record a new observation. Returns True if this message is anomalous.
        """
        self._history.append(observed_delay)

        # Sequence gap check
        if self._last_seq is not None and seq_num > self._last_seq + 1:
            self.seq_gap_count += seq_num - self._last_seq - 1
        self._last_seq = seq_num

        anomalous = self._is_anomalous(observed_delay)
        self._anomaly_window.append(1 if anomalous else 0)
        return anomalous

    def _is_anomalous(self, d: float) -> bool:
        if len(self._history) < 3:
            return False
        hist = list(self._history)[:-1]  # exclude current when computing stats
        mu = sum(hist) / len(hist)
        variance = sum((x - mu) ** 2 for x in hist) / len(hist)
        sigma = math.sqrt(variance) if variance > 0 else 0.0
        if sigma == 0:
            return False
        return abs(d - mu) > self.alpha * sigma

    @property
    def anomaly_density(self) -> float:
        """ρ = fraction of anomalous messages in current window."""
        if not self._anomaly_window:
            return 0.0
        return sum(self._anomaly_window) / len(self._anomaly_window)

    @property
    def mean_delay(self) -> float:
        if not self._history:
            return 0.0
        return sum(self._history) / len(self._history)

    @property
    def delay_variance(self) -> float:
        if len(self._history) < 2:
            return 0.0
        mu = self.mean_delay
        return sum((x - mu) ** 2 for x in self._history) / len(self._history)


class DelayDetector:
    """
    Receiver-centric detector. One instance runs per receiving robot.

    Call observe() for every incoming message, then query is_suspicious()
    to get the current verdict for any sender.
    """

    def __init__(
        self,
        receiver_id: int,
        window: int = 10,
        alpha: float = 2.0,
        density_threshold: float = 0.4,
        seq_gap_threshold: int = 3,
        min_votes: int = 1,
        mean_delay_threshold: float = 1.0,   # absolute: flag if mean delay > this
        variance_threshold: float = 0.5,     # absolute: flag if delay variance > this
        use_cross: bool = True,              # ablation switch: cross-receiver indicator
    ):
        self.receiver_id = receiver_id
        self.density_threshold = density_threshold
        self.seq_gap_threshold = seq_gap_threshold
        self.min_votes = min_votes
        self.mean_delay_threshold = mean_delay_threshold
        self.variance_threshold = variance_threshold
        self.use_cross = use_cross

        self._records: Dict[int, DelayRecord] = defaultdict(
            lambda: DelayRecord(window=window, alpha=alpha)
        )
        # cross-receiver, indexed by sender first so _cross_receiver_flag only
        # scans this sender's own entries rather than every entry ever seen
        # from every sender (that full-dict scan on every observe() call was
        # an O(total messages) cost repeated per message, compounding into a
        # severe slowdown at higher team sizes / longer runs).
        self._cross_by_sender: Dict[int, Dict[int, List[float]]] = defaultdict(dict)
        self._suspicious: Dict[int, bool] = {}
        self._detection_time: Dict[int, int] = {}   # step at which flagged
        self._current_step = 0

    def observe(self, sender_id: int, seq_num: int, generated_at: int, received_at: int):
        """
        Process one received message.

        Parameters
        ----------
        sender_id    : robot that sent the message
        seq_num      : message sequence number
        generated_at : step at which the sender created it
        received_at  : step at which this receiver got it
        """
        self._current_step = received_at
        delay = received_at - generated_at

        rec = self._records[sender_id]
        rec.record(delay, seq_num)

        # Cross-receiver log (shared externally if needed)
        self._cross_by_sender[sender_id].setdefault(seq_num, []).append(delay)

        self._update_suspicion(sender_id)

    def _update_suspicion(self, sender_id: int):
        rec = self._records[sender_id]

        if len(rec._history) < 4:
            return

        temporal_flag = rec.anomaly_density >= self.density_threshold
        seq_flag      = rec.seq_gap_count >= self.seq_gap_threshold
        cross_flag    = self.use_cross and self._cross_receiver_flag(sender_id)
        mean_flag     = rec.mean_delay > self.mean_delay_threshold
        variance_flag = rec.delay_variance > self.variance_threshold

        vote = sum([temporal_flag, seq_flag, cross_flag, mean_flag, variance_flag])
        suspected = vote >= self.min_votes

        if suspected and sender_id not in self._detection_time:
            self._detection_time[sender_id] = self._current_step

        self._suspicious[sender_id] = suspected

    def _cross_receiver_flag(self, sender_id: int) -> bool:
        """
        True if the same sender's messages show high delay variance across
        receivers (indicating inconsistent/selective timing manipulation).
        """
        inconsistencies = 0
        for delays in self._cross_by_sender.get(sender_id, {}).values():
            if len(delays) < 2:
                continue
            spread = max(delays) - min(delays)
            if spread > 2:   # more than 2 steps spread = inconsistent
                inconsistencies += 1
        return inconsistencies >= 2

    def is_suspicious(self, sender_id: int) -> bool:
        return self._suspicious.get(sender_id, False)

    def detection_time(self, sender_id: int) -> Optional[int]:
        return self._detection_time.get(sender_id)

    def report(self) -> Dict:
        return {
            sid: {
                "suspicious": self._suspicious.get(sid, False),
                "anomaly_density": self._records[sid].anomaly_density,
                "mean_delay": self._records[sid].mean_delay,
                "delay_variance": self._records[sid].delay_variance,
                "seq_gaps": self._records[sid].seq_gap_count,
                "detected_at": self._detection_time.get(sid),
            }
            for sid in self._records
        }


class ConsensusDetector:
    """
    Aggregates suspicious votes from multiple DelayDetectors (one per robot).
    A sender is confirmed malicious if a majority of robots flag it.
    """

    def __init__(self, n_robots: int, quorum: float = 0.5):
        self.n_robots = n_robots
        self.quorum = quorum
        self._detectors: Dict[int, DelayDetector] = {}

    def register(self, detector: DelayDetector):
        self._detectors[detector.receiver_id] = detector

    def is_confirmed_malicious(self, sender_id: int) -> bool:
        votes = sum(
            1 for d in self._detectors.values() if d.is_suspicious(sender_id)
        )
        return votes / max(len(self._detectors), 1) >= self.quorum

    def confirmed_malicious(self) -> List[int]:
        all_senders = set()
        for d in self._detectors.values():
            all_senders.update(d._records.keys())
        return [s for s in all_senders if self.is_confirmed_malicious(s)]
