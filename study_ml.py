"""
Learned baselines adapted to one-hop broadcast delay streams (numpy/scipy only).

ETD-style  (after Zhai et al., IEEE TIFS 2023: delay/node/message/connection features, a one-class model of normal
            behaviour, trust scores, and K-Means separation of malicious nodes). Adaptation: the forwarding delay
            ETD must estimate from trajectories is observed directly on one hop; the one-class model is a
            Gaussian (Mahalanobis) model fitted on attack-free sender behaviour; 'trust' is the model score; the
            two clusters of 1-D K-Means (exact, deterministic) split the senders heard by the observer.
HOTD-style (after Zhai et al., JPDC: supervised cross-layer time-delay detection). Adaptation: an L2-regularised
            logistic regression on the same per-sender window features, trained on labelled held-out traces.

These are NOT the published systems: no code, trajectories or multi-hop layers are available. Per-sender window
features (last W=10 messages): mean delay, delay std, max delay, sequence gaps, mean inter-arrival time.
"""
import math
from collections import defaultdict, deque

import numpy as np
from scipy.optimize import minimize

W = 10
MIN_WIN = 5
NF = 5


class _Win:
    __slots__ = ("d", "seq", "rec")

    def __init__(self):
        self.d, self.seq, self.rec = deque(maxlen=W), deque(maxlen=W), deque(maxlen=W)


def features(win):
    d = list(win.d)
    n = len(d)
    m = sum(d) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / n)
    seq = list(win.seq)
    gaps = sum(max(0, seq[i] - seq[i - 1] - 1) for i in range(1, len(seq)))
    rec = list(win.rec)
    ia = (rec[-1] - rec[0]) / max(len(rec) - 1, 1)
    return np.array([m, sd, max(d), gaps, ia], dtype=float)


POP_EPS = 0.05
POP_MIN_SENDERS = 3


def pop_transform(f, latest):
    """Population-normalised features: the same five features expressed relative to the median sender the
    observer hears (delay level and spread in units of the median per-sender delay std, floored like the
    population-referenced detectors). Returns None until POP_MIN_SENDERS senders have features."""
    if len(latest) < POP_MIN_SENDERS:
        return None
    M = np.median(np.array(list(latest.values())), axis=0)
    s = max(M[1], POP_EPS)
    return np.array([(f[0] - M[0]) / s, f[1] / s, (f[2] - M[2]) / s, f[3] - M[3], f[4] / max(M[4], POP_EPS)])


def iter_features(trace, pop=False):
    """Yield (receive_time, sender, feature_vector) for every message once its sender has MIN_WIN samples."""
    st = defaultdict(_Win)
    latest = {}
    for (_t, sender, seq, gen, rec) in trace:
        w = st[sender]
        w.d.append(rec - gen); w.seq.append(seq); w.rec.append(rec)
        if len(w.d) >= MIN_WIN:
            f = features(w)
            if pop:
                latest[sender] = f
                f = pop_transform(f, latest)
                if f is None:
                    continue
            yield rec, sender, f


def fit_models(missions):
    """missions: list of mission dicts (trace, adv, cond). Fits the raw-feature models and, on population-normalised
    features, the *_pop variants."""
    out = _fit(missions, pop=False)
    pm = _fit(missions, pop=True)
    out.update(etd_pop=pm["etd"], hotd_pop=pm["hotd"],
               forest_pop_model=dict(fm=pm["fm"], fs=pm["fs"], forest=pm["forest"]))
    return out


def _fit(missions, pop):
    X, y = [], []
    for m in missions:
        adv = set(m["adv"]) if m["cond"] != "baseline" else set()
        for _rec, sender, f in iter_features(m["trace"], pop=pop):
            X.append(f); y.append(1 if sender in adv else 0)
    X = np.array(X); y = np.array(y)
    benign = X[y == 0]
    mu = benign.mean(0)
    cov = np.cov(benign.T) + 1e-3 * np.eye(NF)
    etd = dict(mu=mu, cov_inv=np.linalg.inv(cov))
    fm, fs = X.mean(0), X.std(0) + 1e-9
    Z = (X - fm) / fs
    pos_w = (y == 0).sum() / max((y == 1).sum(), 1)
    sw = np.where(y == 1, pos_w, 1.0)
    lam = 1e-2

    def loss(p):
        w, b = p[:-1], p[-1]
        z = Z @ w + b
        ll = sw * (np.logaddexp(0, z) - y * z)
        g = sw * (1 / (1 + np.exp(-z)) - y)
        return ll.mean() + lam * (w @ w), np.concatenate([Z.T @ g / len(y) + 2 * lam * w, [g.mean()]])

    res = minimize(loss, np.zeros(NF + 1), jac=True, method="L-BFGS-B")
    hotd = dict(w=res.x[:-1], b=res.x[-1], fm=fm, fs=fs)
    Zb = (benign - fm) / fs
    forest = IsolationForest(Zb, n_trees=100, psi=256, seed=0)
    return dict(etd=etd, hotd=hotd, fm=fm, fs=fs, forest=forest, n_samples=int(len(y)), n_pos=int(y.sum()))


class _FF:
    """Common feature tracking (raw, or population-normalised when pop=True)."""

    def __init__(self, pop=False):
        self.st = defaultdict(_Win)
        self.first_flag = {}
        self.pop = pop
        self.latest = {}

    def _feat(self, sender, seq, gen, rec):
        w = self.st[sender]
        w.d.append(rec - gen); w.seq.append(seq); w.rec.append(rec)
        if len(w.d) < MIN_WIN:
            return None
        f = features(w)
        if not self.pop:
            return f
        self.latest[sender] = f
        return pop_transform(f, self.latest)


class EtdStyle(_FF):
    def __init__(self, model, tau=2.0, smin=3.0, persist=2, pop=False):
        super().__init__(pop)
        self.mu, self.ci = model["mu"], model["cov_inv"]
        self.tau, self.smin, self.persist = tau, smin, persist
        self.score = {}
        self.streak = defaultdict(int)
        self.cl_step, self.high = None, set()

    def _cluster(self):
        vals = sorted(self.score.values())
        n = len(vals)
        if n < 3:
            self.high = set(); return
        best, bi = -1.0, None
        pre = np.cumsum(vals)
        for i in range(1, n):          # exact 1-D 2-means: maximise between-cluster sum of squares
            lo_m, hi_m = pre[i - 1] / i, (pre[-1] - pre[i - 1]) / (n - i)
            bss = i * (n - i) / n * (hi_m - lo_m) ** 2
            if bss > best:
                best, bi = bss, i
        lo_m, hi_m = pre[bi - 1] / bi, (pre[-1] - pre[bi - 1]) / (n - bi)
        thr = vals[bi]
        if hi_m / max(lo_m, 1e-9) >= self.tau:
            self.high = {s for s, v in self.score.items() if v >= thr}
        else:
            self.high = set()

    def observe(self, sender, seq, gen, rec):
        f = self._feat(sender, seq, gen, rec)
        if f is None:
            return
        dlt = f - self.mu
        self.score[sender] = math.sqrt(max(float(dlt @ self.ci @ dlt), 0.0))
        if self.cl_step != rec:
            self._cluster(); self.cl_step = rec
        hit = sender in self.high and self.score[sender] >= self.smin
        self.streak[sender] = self.streak[sender] + 1 if hit else 0
        if self.streak[sender] >= self.persist:
            self.first_flag.setdefault(sender, rec)


class HotdStyle(_FF):
    def __init__(self, model, theta=0.9, persist=2, pop=False):
        super().__init__(pop)
        self.w, self.b, self.fm, self.fs = model["w"], model["b"], model["fm"], model["fs"]
        self.theta, self.persist = theta, persist
        self.streak = defaultdict(int)

    def observe(self, sender, seq, gen, rec):
        f = self._feat(sender, seq, gen, rec)
        if f is None:
            return
        z = float(((f - self.fm) / self.fs) @ self.w + self.b)
        p = 1 / (1 + math.exp(-max(min(z, 50), -50)))
        self.streak[sender] = self.streak[sender] + 1 if p > self.theta else 0
        if self.streak[sender] >= self.persist:
            self.first_flag.setdefault(sender, rec)


# =========================================================================== Isolation Forest (from scratch)
class IsolationForest:
    """Liu, Ting & Zhou (ICDM 2008). Trees stored as padded arrays for vectorised scoring of one point."""

    def __init__(self, X, n_trees=100, psi=256, seed=0):
        rng = np.random.default_rng(seed)
        psi = min(psi, len(X))
        self.psi = psi
        self.limit = int(math.ceil(math.log2(max(psi, 2))))
        trees = []
        for _ in range(n_trees):
            sub = X[rng.choice(len(X), psi, replace=False)]
            trees.append(self._build(sub, rng))
        M = max(len(t[0]) for t in trees)
        T = len(trees)
        self.feat = np.full((T, M), -1, dtype=np.int64)
        self.thr = np.zeros((T, M))
        self.left = np.zeros((T, M), dtype=np.int64)
        self.right = np.zeros((T, M), dtype=np.int64)
        self.leaf_c = np.zeros((T, M))
        for ti, (f, th, lf, rt, lc) in enumerate(trees):
            n = len(f)
            self.feat[ti, :n], self.thr[ti, :n], self.left[ti, :n], self.right[ti, :n], self.leaf_c[ti, :n] = f, th, lf, rt, lc
        self.T = T
        self.c_psi = self._c(psi)
        self.rows = np.arange(T)

    @staticmethod
    def _c(n):
        if n <= 1: return 0.0
        if n == 2: return 1.0
        return 2.0 * (math.log(n - 1) + 0.5772156649) - 2.0 * (n - 1) / n

    def _build(self, sub, rng):
        feat, thr, lf, rt, lc = [], [], [], [], []

        def new_node():
            feat.append(-1); thr.append(0.0); lf.append(0); rt.append(0); lc.append(0.0)
            return len(feat) - 1

        stack = [(new_node(), sub, 0)]
        while stack:
            node, data, depth = stack.pop()
            n = len(data)
            if depth >= self.limit or n <= 1 or np.all(data.max(0) == data.min(0)):
                lc[node] = depth + self._c(n)          # leaf: depth + c(size)
                continue
            for _ in range(10):                          # pick a splittable random feature
                q = int(rng.integers(data.shape[1]))
                lo, hi = data[:, q].min(), data[:, q].max()
                if hi > lo: break
            else:
                lc[node] = depth + self._c(n); continue
            p = rng.uniform(lo, hi)
            mask = data[:, q] < p
            l, r = new_node(), new_node()
            feat[node], thr[node], lf[node], rt[node] = q, p, l, r
            stack.append((l, data[mask], depth + 1)); stack.append((r, data[~mask], depth + 1))
        return np.array(feat), np.array(thr), np.array(lf), np.array(rt), np.array(lc)

    def score(self, x):
        idx = np.zeros(self.T, dtype=np.int64)
        for _ in range(self.limit + 1):
            f = self.feat[self.rows, idx]
            internal = f >= 0
            if not internal.any(): break
            fx = x[np.where(internal, f, 0)]
            go_left = fx < self.thr[self.rows, idx]
            nxt = np.where(go_left, self.left[self.rows, idx], self.right[self.rows, idx])
            idx = np.where(internal, nxt, idx)
        eh = self.leaf_c[self.rows, idx].mean()
        return 2.0 ** (-eh / self.c_psi) if self.c_psi > 0 else 0.5


class IForestDet(_FF):
    def __init__(self, model, theta=0.65, persist=2, pop=False):
        super().__init__(pop)
        self.fm, self.fs, self.forest = model["fm"], model["fs"], model["forest"]
        self.theta, self.persist = theta, persist
        self.streak = defaultdict(int)

    def observe(self, sender, seq, gen, rec):
        f = self._feat(sender, seq, gen, rec)
        if f is None: return
        sc = self.forest.score((f - self.fm) / self.fs)
        self.streak[sender] = self.streak[sender] + 1 if sc > self.theta else 0
        if self.streak[sender] >= self.persist:
            self.first_flag.setdefault(sender, rec)


# =========================================================================== Bayesian online change-point detection
from scipy.special import stdtr, gammaln   # noqa: E402
from study_detectors import _Ref            # noqa: E402


class _Bocpd:
    """Adams & MacKay (2007): run-length posterior, Normal-Gamma conjugate model, constant hazard."""

    def __init__(self, hazard, rmax=60, mu0=0.0, kappa0=1.0, alpha0=1.0, beta0=1.0):
        self.h, self.rmax = hazard, rmax
        self.prior = (mu0, kappa0, alpha0, beta0)
        self.p = np.array([1.0])
        self.mu = np.array([mu0]); self.ka = np.array([kappa0]); self.al = np.array([alpha0]); self.be = np.array([beta0])

    def update(self, x):
        df = 2 * self.al
        scale2 = self.be * (self.ka + 1) / (self.al * self.ka)
        z = (x - self.mu) / np.sqrt(scale2)
        logpdf = gammaln((df + 1) / 2) - gammaln(df / 2) - 0.5 * np.log(df * np.pi * scale2) - (df + 1) / 2 * np.log1p(z * z / df)
        pred = np.exp(logpdf)
        growth = self.p * pred * (1 - self.h)
        cp = float((self.p * pred * self.h).sum())
        newp = np.concatenate([[cp], growth])
        s = newp.sum()
        newp = newp / s if s > 0 else np.concatenate([[1.0], np.zeros(len(growth))])
        mu0, ka0, al0, be0 = self.prior
        self.mu, self.ka, self.al, self.be = (
            np.concatenate([[mu0], (self.ka * self.mu + x) / (self.ka + 1)]),
            np.concatenate([[ka0], self.ka + 1]),
            np.concatenate([[al0], self.al + 0.5]),
            np.concatenate([[be0], self.be + self.ka * (x - self.mu) ** 2 / (2 * (self.ka + 1))]))
        self.p = newp
        if len(self.p) > self.rmax:                      # truncate the oldest run lengths
            self.p[self.rmax - 1] += self.p[self.rmax:].sum()
            self.p = self.p[:self.rmax]
            self.mu, self.ka, self.al, self.be = self.mu[:self.rmax], self.ka[:self.rmax], self.al[:self.rmax], self.be[:self.rmax]

    def prob_shift_above(self, delta):
        """Posterior probability that the current mean exceeds delta, averaged over run lengths."""
        df = 2 * self.al
        scale = np.sqrt(self.be / (self.al * self.ka))
        sf = 1.0 - stdtr(df, (delta - self.mu) / scale)
        return float((self.p * sf).sum())


class BocpdDet(_Ref):
    def __init__(self, ref="pop", delta=1.0, theta=0.95, hazard=0.02, persist=2, n0=5):
        super().__init__(ref, n0)
        self.delta, self.theta, self.hazard, self.persist = delta, theta, hazard, persist
        self.bo = {}
        self.streak = defaultdict(int)

    def observe(self, sender, seq, gen, rec):
        delay = rec - gen
        r = self._ref(sender, delay, rec)
        if r is None: return
        mu, sd = r
        b = self.bo.setdefault(sender, _Bocpd(self.hazard))
        b.update((delay - mu) / sd)
        self.streak[sender] = self.streak[sender] + 1 if b.prob_shift_above(self.delta) > self.theta else 0
        if self.streak[sender] >= self.persist:
            self.first_flag.setdefault(sender, rec)
