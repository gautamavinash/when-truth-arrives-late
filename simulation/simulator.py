"""
Discrete-time simulation engine for ORMSTC-based multi-robot exploration
with optional SLA / BLA attack injection and delay detection.

Each time step:
  1. Every robot creates a broadcast message.
  2. For the adversary, the message is intercepted by the attack proxy
     (SLA or BLA), which schedules its delayed delivery.
  3. The attack proxy flushes any messages that are now due.
  4. Legitimate robots receive all due messages and update their known state.
  5. Every robot plans its next move.
  6. Every robot executes its move.
  7. Metrics are collected.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from simulation.grid_env import GridEnv
from simulation.robot import ORMSTCRobot, Message
from detection.detector import DelayDetector, ConsensusDetector
from detection.calibrated import CalibratedDetector


@dataclass
class StepMetrics:
    step: int
    covered: int
    uncovered: int
    collisions: int
    redundant: int
    all_done: bool
    suspected_robots: List[int] = field(default_factory=list)


class Simulator:
    def __init__(
        self,
        env: GridEnv,
        n_robots: int,
        adversary_ids: Optional[List[int]] = None,
        attack_proxies: Optional[Dict[int, object]] = None,   # adversary_id -> SequentialLagAttacker/BoundedLagAttacker
        enable_detection: bool = True,
        detection_window: int = 10,
        detection_alpha: float = 2.0,
        seed: int = 42,
        max_steps: int = 2000,
        detector_variants: Optional[Dict[str, dict]] = None,
        channel_jitter: int = 0,        # honest channel: extra random delay 0..J steps per message
        channel_loss: float = 0.0,      # honest channel: independent per-message drop probability
        channel_model: str = "uniform", # "uniform": U{0..J} jitter + Bernoulli loss; "shift": heavy-tailed jitter + bursty (Gilbert-Elliott) loss
        attack_onset: int = 0,          # step at which compromised robots start attacking (0 = from the start)
        record_trace_for: Optional[int] = None,   # robot id whose received-message stream is recorded
        attack_onsets: Optional[Dict[int, int]] = None,   # per-attacker start step (overrides attack_onset)
        mitigation: Optional[dict] = None,    # closed loop: {'det': name, 'params': {...}, 'mode': 'none'|'drop_all'|'drop_intent'}
    ):
        self.env = env
        self.n_robots = n_robots
        self.adversary_ids = set(adversary_ids or [])
        self.attack_proxies = attack_proxies or {}
        self.enable_detection = enable_detection
        self.max_steps = max_steps

        starts = env.random_free_starts(n_robots, seed=seed)
        self.robots: List[ORMSTCRobot] = [
            ORMSTCRobot(i, starts[i], env) for i in range(n_robots)
        ]

        # Detection: one detector per legitimate (non-compromised) robot
        self.detectors: List[DelayDetector] = []
        self.detectors_by_receiver: Dict[int, DelayDetector] = {}
        self.consensus: Optional[ConsensusDetector] = None
        if enable_detection and self.adversary_ids:
            for r in self.robots:
                if r.robot_id not in self.adversary_ids:
                    d = DelayDetector(
                        receiver_id=r.robot_id,
                        window=detection_window,
                        alpha=detection_alpha,
                        min_votes=1,
                    )
                    self.detectors.append(d)
                    self.detectors_by_receiver[d.receiver_id] = d
            self.consensus = ConsensusDetector(n_robots)
            for d in self.detectors:
                self.consensus.register(d)

        # Optional study mode: several passive detector configurations observe the
        # same message stream (detectors never influence the simulation), including
        # attack-free missions, and first-confirmation steps are recorded.
        self.variants: Dict[str, dict] = {}
        if detector_variants:
            for name, kw in detector_variants.items():
                kw = dict(kw)
                cls = CalibratedDetector if kw.pop("calibrated", False) else DelayDetector
                dets = {
                    r.robot_id: cls(receiver_id=r.robot_id, window=detection_window,
                                    alpha=detection_alpha, **kw)
                    for r in self.robots if r.robot_id not in self.adversary_ids
                }
                self.variants[name] = {"dets": dets, "first_confirmed": {}, "first_local": {}}

        # Optional noisy channel applied to every delivered message (attacker or not).
        # With jitter=loss=0 this is bypassed entirely, preserving the original behavior.
        import random as _random
        self.channel_jitter = channel_jitter
        self.channel_loss = channel_loss
        self._chan_rng = _random.Random(seed * 7919 + 13)
        self._pending: List[Message] = []
        self.channel_model = channel_model
        self._ge_bad = False                      # Gilbert-Elliott channel state ("shift" model)
        self.attack_onset = attack_onset
        # Closed-loop response: one detector watches every delivered message (all receivers see the same stream in this
        # simulator); once it flags a sender, receivers treat that sender's later messages according to `mode`.
        self._mit, self._mit_mode, self.mit_flag_step = None, "none", {}
        self._max_age = None
        if mitigation and mitigation.get("mode") in ("stale_drop", "stale_intent"):
            # freshness response, no detector: every receiver treats any message older than T on arrival as stale
            self._mit_mode, self._max_age = mitigation["mode"], mitigation.get("T", 2)
        elif mitigation and mitigation.get("mode", "none") != "none":
            import study_detectors as _sd
            self._mit = _sd.make(mitigation["det"], **mitigation.get("params", {}))
            self._mit_mode = mitigation["mode"]
        self.attack_onsets = attack_onsets or {}
        self.record_trace_for = record_trace_for
        self.trace: List[tuple] = []

        self.step = 0
        self.history: List[StepMetrics] = []

        # Track all globally visited cells
        self.global_visited: set = set(starts)

    # ── main loop ─────────────────────────────────────────────────────────────

    def run(self) -> List[StepMetrics]:
        while self.step < self.max_steps:
            metrics = self._tick()
            self.history.append(metrics)
            if metrics.all_done:
                break
        return self.history

    def _tick(self) -> StepMetrics:
        t = self.step

        # 1. Each robot creates its outgoing message
        outbox: Dict[int, Message] = {}
        for robot in self.robots:
            msg = robot.make_message(t)
            outbox[robot.robot_id] = msg

        # 2 & 3. Attack intercept + flush for each adversary's messages
        delivered: List[Message] = []
        for robot_id, msg in outbox.items():
            proxy = self.attack_proxies.get(robot_id) if (robot_id in self.adversary_ids and t >= self.attack_onsets.get(robot_id, self.attack_onset)) else None
            if proxy is not None:
                proxy.intercept(msg, t)
            else:
                msg.received_at = t
                delivered.append(msg)

        for proxy in self.attack_proxies.values():
            delivered.extend(proxy.flush(t))

        if self.channel_model == "shift":
            # one shared two-state loss chain per step; heavy-tailed jitter (geometric, mean ~1, capped at 8)
            rng = self._chan_rng
            self._ge_bad = (rng.random() >= 0.2) if self._ge_bad else (rng.random() < 0.02)
            p_loss = 0.5 if self._ge_bad else 0.01
            for msg in delivered:
                if rng.random() < p_loss:
                    continue
                extra = 0
                while extra < 8 and rng.random() < 0.5:
                    extra += 1
                msg.received_at = t + extra
                self._pending.append(msg)
            delivered = [m for m in self._pending if m.received_at <= t]
            self._pending = [m for m in self._pending if m.received_at > t]
        elif self.channel_jitter or self.channel_loss:
            for msg in delivered:
                if self._chan_rng.random() < self.channel_loss:
                    continue
                msg.received_at = t + self._chan_rng.randint(0, self.channel_jitter)
                self._pending.append(msg)
            delivered = [m for m in self._pending if m.received_at <= t]
            self._pending = [m for m in self._pending if m.received_at > t]

        if self.record_trace_for is not None:
            for msg in delivered:
                if msg.robot_id != self.record_trace_for:
                    self.trace.append((t, msg.robot_id, msg.seq_num, msg.generated_at, msg.received_at))

        # 4. Robots receive messages + detection observes
        for msg in delivered:
            flagged = False
            if self._mit is not None:
                self._mit.observe(msg.robot_id, msg.seq_num, msg.generated_at, msg.received_at)
                flagged = msg.robot_id in self._mit.first_flag
                if flagged:
                    self.mit_flag_step.setdefault(msg.robot_id, t)
            stale = self._max_age is not None and (msg.received_at - msg.generated_at) > self._max_age
            for robot in self.robots:
                if robot.robot_id != msg.robot_id:
                    if stale and self._mit_mode == "stale_drop":
                        pass                                        # discard the stale message entirely
                    elif stale and self._mit_mode == "stale_intent":
                        from dataclasses import replace as _replace
                        robot.receive(_replace(msg, next_move=None))   # keep its visited cells, drop its stale intent
                    elif flagged and self._mit_mode == "drop_all":
                        pass                                        # ignore the flagged sender entirely
                    elif flagged and self._mit_mode == "drop_intent":
                        from dataclasses import replace as _replace
                        robot.receive(_replace(msg, next_move=None))   # keep late-but-true visited cells, drop stale intent
                    else:
                        robot.receive(msg)

                    for v in self.variants.values():
                        vd = v["dets"].get(robot.robot_id)
                        if vd is not None:
                            vd.observe(sender_id=msg.robot_id, seq_num=msg.seq_num,
                                       generated_at=msg.generated_at, received_at=msg.received_at)

                    if self.enable_detection:
                        det = self.detectors_by_receiver.get(robot.robot_id)
                        if det is not None:
                            det.observe(
                                sender_id=msg.robot_id,
                                seq_num=msg.seq_num,
                                generated_at=msg.generated_at,
                                received_at=msg.received_at,
                            )

        # 5. Plan
        for robot in self.robots:
            robot.plan()

        # 6. Move + collision tracking
        # A collision is counted for every robot that moves into a cell occupied by another robot after this step's
        # moves (earlier versions reported only the final step's count, which was always 0).
        before = {robot.robot_id: robot.pos for robot in self.robots}
        for robot in self.robots:
            robot.move(self.global_visited)
            self.global_visited.add(robot.pos)
        occ: Dict = {}
        for robot in self.robots:
            occ.setdefault(robot.pos, []).append(robot.robot_id)
        collisions = sum(1 for robot in self.robots
                         if robot.pos != before[robot.robot_id] and len(occ[robot.pos]) > 1)
        self.total_collisions = getattr(self, "total_collisions", 0) + collisions

        # 7. Metrics
        total_free = self.env.total_free()
        covered = len(self.global_visited - self.env.obstacle_set)
        uncovered = total_free - covered
        redundant = sum(r.redundant for r in self.robots)
        all_done = all(r.done for r in self.robots)

        suspected = []
        if self.consensus:
            suspected = self.consensus.confirmed_malicious()

        for v in self.variants.values():
            votes: Dict[int, int] = {}
            for d in v["dets"].values():
                for sid, flagged in d._suspicious.items():
                    if flagged:
                        votes[sid] = votes.get(sid, 0) + 1
                        v["first_local"].setdefault(sid, t)
            quorum = 0.5 * len(v["dets"])
            for sid, c in votes.items():
                if c >= quorum and sid not in v["first_confirmed"]:
                    v["first_confirmed"][sid] = t

        self.step += 1
        return StepMetrics(
            step=t,
            covered=covered,
            uncovered=uncovered,
            collisions=collisions,
            redundant=redundant,
            all_done=all_done,
            suspected_robots=suspected,
        )

    # ── summary ───────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        if not self.history:
            return {}
        final = self.history[-1]
        total_free = self.env.total_free()
        n_attackers = len(self.adversary_ids)

        malicious_robots = [r for r in self.robots if r.robot_id in self.adversary_ids]
        malicious_coverage_total = sum(r.coverage for r in malicious_robots)
        malicious_coverage_mean = (
            malicious_coverage_total / n_attackers if n_attackers else 0
        )
        legitimate_coverage = sum(
            r.coverage for r in self.robots if r.robot_id not in self.adversary_ids
        )
        legitimate_avg_coverage = legitimate_coverage / max(self.n_robots - n_attackers, 1)

        suspected = set(final.suspected_robots)
        adv = self.adversary_ids
        tp = len(adv & suspected)
        fp = len(suspected - adv)
        fn = len(adv - suspected)
        detection_recall = tp / n_attackers if n_attackers else None
        detection_precision = tp / (tp + fp) if (tp + fp) else None
        detection_all_correct = (fn == 0 and fp == 0) if adv else None

        study = {}
        for name, v in self.variants.items():
            conf = v["first_confirmed"]
            conf_set = set(conf)
            tp = len(adv & conf_set); fp = len(conf_set - adv)
            lat = [conf[a] for a in adv if a in conf]
            loc = [v["first_local"][a] for a in adv if a in v["first_local"]]
            study[f"{name}__recall"] = tp / n_attackers if n_attackers else None
            study[f"{name}__fp"] = fp
            study[f"{name}__correct"] = (tp == n_attackers and fp == 0)
            study[f"{name}__lat_mean"] = sum(lat) / len(lat) if lat else None
            study[f"{name}__lat_max"] = max(lat) if len(lat) == n_attackers and lat else None
            study[f"{name}__local_first"] = min(loc) if loc else None

        out = {
            "completion_step": self.step,
            "total_free_cells": total_free,
            "covered_cells": final.covered,
            "uncovered_cells": final.uncovered,
            "coverage_efficiency": final.covered / total_free if total_free else 0,
            "total_collisions": getattr(self, "total_collisions", 0),
            "total_redundant": final.redundant,
            "n_attackers": n_attackers,
            "malicious_coverage": malicious_coverage_mean,       # mean per-attacker (comparable to prior single-attacker runs)
            "malicious_coverage_total": malicious_coverage_total,
            "legitimate_avg_coverage": legitimate_avg_coverage,
            "detection_recall": detection_recall,
            "detection_precision": detection_precision,
            "detection_all_correct": detection_all_correct,
        }
        out.update(study)
        return out
