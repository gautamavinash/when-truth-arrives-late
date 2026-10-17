"""
Detector library for the comparison study. All detectors share one interface and
are evaluated offline on observer traces (gen_traces.py):

    det = make(name, **params)
    for (step, sender, seq, generated_at, received_at) in trace:
        det.observe(sender, seq, generated_at, received_at)
    det.first_flag   # {sender: first time (received_at) it was flagged}

Detectors (all one-sided: they look for *late* messages):
  fixed        original receiver-centric detector with absolute thresholds
               (anomaly density, cumulative sequence gaps, mean delay, delay variance;
               min_votes indicators needed). The cross-receiver indicator needs several
               receivers and is not used with a single observer.
  calibrated   population-relative detector (detection/calibrated.py).
  cusum_self / cusum_pop   Page (1954) CUSUM on the standardized delay.
  ewma_self  / ewma_pop    Roberts (1959) EWMA control chart on the standardized delay.
  mad_self   / mad_pop     median/MAD outlier test (Leys et al., 2013) with persistence.

"_self": the in-control mean/std come from the sender's own first n0 messages (the
textbook per-stream setup). "_pop": they come from the population of senders the
observer hears (median of sender window means / median per-sender std), the same
reference information the calibrated detector uses. Every scale is floored at EPS so
that a degenerate (near-zero) std cannot make tiny fluctuations look significant.
"""
import math
import os
import sys
from collections import defaultdict, deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from detection.detector import DelayDetector  # noqa: E402
from detection.calibrated import CalibratedDetector  # noqa: E402

EPS = 0.05
BIG = 10 ** 9
MIN_SENDERS = 3   # population statistics need at least this many senders with enough samples


def _median(v):
    v = sorted(v)
    n = len(v)
    return v[n // 2] if n % 2 else 0.5 * (v[n // 2 - 1] + v[n // 2])


POP_WINDOW = 10   # sensitivity hooks (defaults used everywhere unless a study overrides them)
LOO = False


class _Pop:
    """Per-step population statistics over the last `window` delays of every sender."""

    def __init__(self, window=None, min_samples=3, loo=None):
        self.window = POP_WINDOW if window is None else window
        self.min_samples = min_samples
        self.loo = LOO if loo is None else loo
        self.d = defaultdict(lambda: deque(maxlen=self.window))
        self._step, self._cache = None, None

    def add(self, sender, delay):
        self.d[sender].append(delay)

    def _compute(self, exclude=None):
        means, sds = [], []
        for sid, dq in self.d.items():
            n = len(dq)
            if n < self.min_samples or sid == exclude:
                continue
            m = sum(dq) / n
            means.append(m)
            sds.append(math.sqrt(sum((x - m) ** 2 for x in dq) / n))
        return (_median(means), max(_median(sds), EPS)) if len(means) >= MIN_SENDERS else None

    def stats(self, now, sender=None):
        if self.loo:
            return self._compute(exclude=sender)
        if self._step != now:
            self._cache = self._compute()
            self._step = now
        return self._cache


class _Base:
    def __init__(self):
        self.first_flag = {}

    def _flag(self, sender, t):
        self.first_flag.setdefault(sender, t)


class Fixed(_Base):
    def __init__(self, window=10, alpha=2.0, density_threshold=0.4, seq_gap_threshold=3,
                 mean_delay_threshold=1.0, variance_threshold=0.5, min_votes=1):
        super().__init__()
        self.det = DelayDetector(receiver_id=-1, window=window, alpha=alpha,
                                 density_threshold=density_threshold, seq_gap_threshold=seq_gap_threshold,
                                 mean_delay_threshold=mean_delay_threshold, variance_threshold=variance_threshold,
                                 min_votes=min_votes, use_cross=False)

    def observe(self, sender, seq, gen, rec):
        self.det.observe(sender, seq, gen, rec)
        if sender in self.det._detection_time:
            self._flag(sender, self.det._detection_time[sender])


class Calibrated(_Base):
    def __init__(self, k=4.0, delta=0.0, persist=3, min_samples=3, window=None, loo=None):
        super().__init__()
        self.det = CalibratedDetector(receiver_id=-1, window=POP_WINDOW if window is None else window, k=k, delta=delta,
                                      persist=persist, min_samples=min_samples, scale_floor=EPS,
                                      min_senders=MIN_SENDERS, loo=LOO if loo is None else loo)

    def observe(self, sender, seq, gen, rec):
        self.det.observe(sender, seq, gen, rec)
        if sender in self.det._detection_time:
            self._flag(sender, self.det._detection_time[sender])


class _Ref(_Base):
    """Reference (mu0, sigma0) provider shared by CUSUM/EWMA."""

    def __init__(self, ref, n0):
        super().__init__()
        self.ref, self.n0 = ref, n0
        self.pop = _Pop() if ref == "pop" else None
        self.first_n = defaultdict(list)

    def _ref(self, sender, delay, now):
        """Return (mu0, sigma0) or None while the reference is not yet available."""
        if self.ref == "pop":
            self.pop.add(sender, delay)
            st_ = self.pop.stats(now, sender)
            return None if st_ is None else (st_[0], max(st_[1], EPS))
        fn = self.first_n[sender]
        if len(fn) < self.n0:
            fn.append(delay)
            return None
        mu = sum(fn) / len(fn)
        sd = math.sqrt(sum((x - mu) ** 2 for x in fn) / len(fn))
        return mu, max(sd, EPS)


class Cusum(_Ref):
    def __init__(self, ref="self", k=0.5, h=4.0, n0=5):
        super().__init__(ref, n0)
        self.k, self.h = k, h
        self.S = defaultdict(float)

    def observe(self, sender, seq, gen, rec):
        delay = rec - gen
        r = self._ref(sender, delay, rec)
        if r is None:
            return
        mu, sd = r
        self.S[sender] = max(0.0, self.S[sender] + (delay - mu) / sd - self.k)
        if self.S[sender] > self.h:
            self._flag(sender, rec)


class Ewma(_Ref):
    def __init__(self, ref="self", lam=0.2, L=3.0, n0=5):
        super().__init__(ref, n0)
        self.lam, self.L = lam, L
        self.z = {}

    def observe(self, sender, seq, gen, rec):
        delay = rec - gen
        r = self._ref(sender, delay, rec)
        if r is None:
            return
        mu, sd = r
        x = (delay - mu) / sd
        self.z[sender] = self.lam * x + (1 - self.lam) * self.z.get(sender, 0.0)
        if self.z[sender] > self.L * math.sqrt(self.lam / (2 - self.lam)):
            self._flag(sender, rec)


class Mad(_Base):
    def __init__(self, ref="self", c=3.0, persist=2, n0=5, window=10):
        super().__init__()
        self.ref, self.c, self.persist, self.n0, self.window = ref, c, persist, n0, window
        self.hist = defaultdict(lambda: deque(maxlen=200))
        self.streak = defaultdict(int)
        self.recent = defaultdict(lambda: deque(maxlen=window))
        self._step, self._cache = None, None

    def _pooled(self, now):
        if self._step != now:
            pooled = [x for dq in self.recent.values() for x in dq]
            if len(pooled) >= 5 and len([1 for dq in self.recent.values() if len(dq) >= 3]) >= MIN_SENDERS:
                med = _median(pooled)
                mad = 1.4826 * _median([abs(x - med) for x in pooled])
                self._cache = (med, max(mad, EPS))
            else:
                self._cache = None
            self._step = now
        return self._cache

    def observe(self, sender, seq, gen, rec):
        delay = rec - gen
        if self.ref == "self":
            h = self.hist[sender]
            ok = len(h) >= self.n0
            if ok:
                med = _median(list(h))
                mad = max(1.4826 * _median([abs(x - med) for x in h]), EPS)
            h.append(delay)
            if not ok:
                return
        else:
            self.recent[sender].append(delay)
            ref = self._pooled(rec)
            if ref is None:
                return
            med, mad = ref
        exceed = (delay - med) > self.c * mad
        self.streak[sender] = self.streak[sender] + 1 if exceed else 0
        if self.streak[sender] >= self.persist:
            self._flag(sender, rec)


class MaxAge(_Base):
    """Freshness check: flag a sender after `persist` consecutive messages older than T on arrival."""

    def __init__(self, T=3.0, persist=2):
        super().__init__()
        self.T, self.persist = T, persist
        self.streak = defaultdict(int)

    def observe(self, sender, seq, gen, rec):
        self.streak[sender] = self.streak[sender] + 1 if (rec - gen) > self.T else 0
        if self.streak[sender] >= self.persist:
            self._flag(sender, rec)


# --------------------------------------------------------------------------- registry
MODELS = {}   # learned models (fitted on held-out traces) for the ETD-style / HOTD-style detectors


def _etd(**p):
    import study_ml
    return study_ml.EtdStyle(MODELS['etd'], **p)


def _hotd(**p):
    import study_ml
    return study_ml.HotdStyle(MODELS['hotd'], **p)


FACTORY = {
    "maxage": lambda **p: MaxAge(**p),
    "etd_pop": lambda **p: __import__("study_ml").EtdStyle(MODELS['etd_pop'], pop=True, **p),
    "hotd_pop": lambda **p: __import__("study_ml").HotdStyle(MODELS['hotd_pop'], pop=True, **p),
    "iforest_pop": lambda **p: __import__("study_ml").IForestDet(MODELS['forest_pop_model'], pop=True, **p),
    "etd_style": _etd,
    "hotd_style": _hotd,
    "iforest": lambda **p: __import__("study_ml").IForestDet(MODELS, **p),
    "bocpd_pop": lambda **p: __import__("study_ml").BocpdDet(ref="pop", **p),
    "bocpd_self": lambda **p: __import__("study_ml").BocpdDet(ref="self", **p),
    "fixed": lambda **p: Fixed(**p),
    "calibrated": lambda **p: Calibrated(**p),
    "cusum_self": lambda **p: Cusum(ref="self", **p),
    "cusum_pop": lambda **p: Cusum(ref="pop", **p),
    "ewma_self": lambda **p: Ewma(ref="self", **p),
    "ewma_pop": lambda **p: Ewma(ref="pop", **p),
    "mad_self": lambda **p: Mad(ref="self", **p),
    "mad_pop": lambda **p: Mad(ref="pop", **p),
}

# random-search spaces (identical budget for every detector: SEARCH_N draws, same RNG seed)
SPACE = {
    "maxage": dict(T=[0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0], persist=[1, 2, 3, 4, 5]),
    "etd_pop": dict(tau=[1.5, 2.0, 3.0, 5.0], smin=[2.0, 3.0, 4.0, 6.0, 8.0], persist=[1, 2, 3, 4]),
    "hotd_pop": dict(theta=[0.5, 0.7, 0.9, 0.95, 0.99], persist=[1, 2, 3, 4, 5]),
    "iforest_pop": dict(theta=[0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.9], persist=[1, 2, 3, 4]),
    "iforest": dict(theta=[0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.9], persist=[1, 2, 3, 4]),
    "bocpd_pop": dict(delta=[0.5, 1.0, 2.0], theta=[0.9, 0.95, 0.99], hazard=[0.01, 0.1], persist=[1, 2, 3]),
    "bocpd_self": dict(delta=[0.5, 1.0, 2.0], theta=[0.9, 0.95, 0.99], hazard=[0.01, 0.1], persist=[1, 2, 3], n0=[3, 5, 10, 20]),
    "etd_style": dict(tau=[1.5, 2.0, 3.0, 5.0], smin=[2.0, 3.0, 4.0, 6.0, 8.0], persist=[1, 2, 3, 4]),
    "hotd_style": dict(theta=[0.5, 0.7, 0.9, 0.95, 0.99], persist=[1, 2, 3, 4, 5]),
    "fixed": dict(alpha=[2.0, 3.0], density_threshold=[0.3, 0.4, 0.5, 0.6, 0.8],
                  seq_gap_threshold=[2, 3, 5, 8, BIG], mean_delay_threshold=[0.5, 1.0, 1.5, 2.0, 3.0, BIG],
                  variance_threshold=[0.25, 0.5, 1.0, 2.0, 4.0, BIG], min_votes=[1, 2]),
    "calibrated": dict(k=[2.5, 3.0, 4.0, 5.0, 6.0], delta=[0.0, 0.25, 0.5], persist=[1, 2, 3, 4, 5],
                       min_samples=[2, 3, 5]),
    "cusum_self": dict(k=[0.25, 0.5, 1.0, 1.5], h=[2.0, 3.0, 4.0, 6.0, 8.0, 12.0], n0=[3, 5, 10, 20]),
    "cusum_pop": dict(k=[0.25, 0.5, 1.0, 1.5], h=[2.0, 3.0, 4.0, 6.0, 8.0, 12.0]),
    "ewma_self": dict(lam=[0.1, 0.2, 0.3, 0.5], L=[2.5, 3.0, 4.0, 5.0, 6.0], n0=[3, 5, 10, 20]),
    "ewma_pop": dict(lam=[0.1, 0.2, 0.3, 0.5], L=[2.5, 3.0, 4.0, 5.0, 6.0]),
    "mad_self": dict(c=[2.5, 3.0, 4.0, 5.0], persist=[1, 2, 3, 4], n0=[3, 5, 10, 20]),
    "mad_pop": dict(c=[2.5, 3.0, 4.0, 5.0, 6.0], persist=[1, 2, 3, 4]),
}
SEARCH_N = 36
ORIG_FIXED = {}   # original DelayDetector defaults (window 10, alpha 2, density .4, seq 3, mean 1.0, var .5, 1 vote)


def make(name, **params):
    return FACTORY[name](**params)
