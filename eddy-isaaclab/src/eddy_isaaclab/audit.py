"""The Isaac Lab episode-end hook (IX5, packaged in HE2): track the peak net
contact force per body across an episode from a `ContactSensor`
(`sensor.data.net_forces_w`, shape `[num_envs, num_bodies, 3]`), and at
reset post the peaks as one `POST /v1/interop.audit` batch. The audit
quantises to the declared bucket server-side and solves one P1 case per
distinct (body, bucket); 4096 environments with the same gripper cost one
solve per bucket.

    from eddy_isaaclab import ForceAudit, contact_yield_check, steel
    audit = ForceAudit(bodies=["finger_l", "finger_r"],
                       checks=[contact_yield_check("finger_l", 25.0, 0.06, 0.02, 0.02, "x_max", "x_min", steel()),
                               contact_yield_check("finger_r", 25.0, 0.06, 0.02, 0.02, "x_max", "x_min", steel())])
    # in the step loop
    audit.observe(sensor.data.net_forces_w)
    # in reset_idx / at termination
    report = audit.audit(env_ids)

Poses can be recorded too (`observe_poses(root_pos_w, root_quat_w, t)`) so
the trajectory checks (free fall, energy, rest, the reference sim) run on the
same batch. Nothing here calls the engine inside the step, and nothing here
imports Isaac Lab: the module imports with the standard library and
`eddy_solve` alone (torch and numpy are imported when a tensor arrives).
"""
import math

from eddy_solve.interop import ForeignRollout, Interop, contact_yield_check  # noqa: F401


def steel():
    return {"e": 210e9, "nu": 0.3, "rho": 7850.0, "yield": 250e6}


def _round_up(value, size):
    """The server's quantisation (round up to the bucket), applied client-side so identical
    buckets become identical request items."""
    return math.ceil(value / size) * size if size and size > 0 else value


class ForceAudit:
    def __init__(self, bodies, checks, base_url="http://127.0.0.1:8080", api_key=None, engine_version="isaac-lab", device="cuda", sample_every=1, client=None):
        self.bodies = list(bodies)
        self.checks = checks
        self.ix = client if client is not None else Interop(base_url, api_key=api_key)
        self.version = engine_version
        self.device = device
        self.sample_every = max(1, int(sample_every))
        self.peak = None
        self.frames = {}  # env id -> ForeignRollout (when poses are recorded)
        self.k = 0
        # the bucket per body, from the contact_yield checks (bodies without one keep raw peaks)
        self.buckets = {}
        for c in checks:
            if c.get("kind") == "contact_yield" and c.get("bucket"):
                self.buckets[c["body"]] = float(c["bucket"])

    def observe(self, net_forces_w):
        """Every step: keep the running peak |F| per env per body (a torch tensor or a numpy array `[E, B, 3]`)."""
        if hasattr(net_forces_w, "detach"):
            import torch

            f = torch.linalg.norm(net_forces_w.detach(), dim=-1)
            self.peak = f.clone() if self.peak is None else torch.maximum(self.peak, f)
        else:
            import numpy as np

            f = np.linalg.norm(np.asarray(net_forces_w, dtype=float), axis=-1)
            self.peak = f.copy() if self.peak is None else np.maximum(self.peak, f)

    def observe_poses(self, root_pos_w, root_quat_w, t, env_ids=None):
        """Optional: record poses per env (`[E, B, 3]`, `[E, B, 4]` w-first) for the trajectory checks."""
        self.k += 1
        if self.k % self.sample_every:
            return
        envs = range(root_pos_w.shape[0]) if env_ids is None else env_ids
        for e in envs:
            r = self.frames.setdefault(int(e), ForeignRollout("physx", self.bodies, version=self.version, device=self.device))
            r.add(float(t), root_pos_w[e].tolist(), quat=root_quat_w[e].tolist())

    def _peak_rollout(self, peaks):
        r = ForeignRollout("physx", self.bodies, version=self.version, device=self.device)
        zero = [[0.0, 0.0, 0.0] for _ in self.bodies]
        r.add(0.0, zero, contact_force=[0.0] * len(self.bodies))
        r.add(1.0, zero, contact_force=peaks)
        return r

    def bucketed(self, peaks):
        """The peaks rounded up to each body's bucket (what the server grades)."""
        return [_round_up(float(p), self.buckets.get(b, 0.0)) for b, p in zip(self.bodies, peaks)]

    def build_batch(self, env_ids=None, dedupe=False):
        """The request the reset posts, without posting it: `(audits, env_to_item)`.

        With `dedupe=False` (the IX5 behaviour) every env is its own audit item. With
        `dedupe=True` the peaks are rounded up to the bucket client-side and envs with the
        same bucketed peaks share one item (the server would grade them identically: the
        audit row's `foreign` value is the bucketed force either way); only envs without
        recorded poses are deduplicated."""
        if self.peak is None:
            return [], {}
        envs = range(self.peak.shape[0]) if env_ids is None else [int(e) for e in env_ids]
        audits, env_to_item, seen = [], {}, {}
        for e in envs:
            peaks = [float(x) for x in self.peak[e].tolist()]
            r = self.frames.get(e)
            if r is not None and len(r.frames) >= 2:
                r.frames[-1]["contact_force"] = peaks
                env_to_item[e] = len(audits)
                audits.append({"rollout": r, "checks": self.checks})
                continue
            if dedupe:
                key = tuple(self.bucketed(peaks))
                if key in seen:
                    env_to_item[e] = seen[key]
                    continue
                seen[key] = len(audits)
                env_to_item[e] = len(audits)
                audits.append({"rollout": self._peak_rollout(list(key)), "checks": self.checks})
            else:
                env_to_item[e] = len(audits)
                audits.append({"rollout": self._peak_rollout(peaks), "checks": self.checks})
        return audits, env_to_item

    def audit(self, env_ids=None, dedupe=False):
        """At episode end: one batch — the peak per env as a two-frame rollout when no poses were
        recorded (the audit needs two frames), the recorded rollout otherwise. Returns the
        server's answer (with `env_to_audit` added when `dedupe=True`); identical peaks across
        envs hit the same truth solve."""
        audits, env_to_item = self.build_batch(env_ids, dedupe=dedupe)
        if not audits:
            return None
        out = self.ix.audit_batch(audits)
        if dedupe:
            out["env_to_audit"] = {str(e): i for e, i in env_to_item.items()}
        for e in env_to_item:
            self.frames.pop(e, None)
        self.peak = None
        self.k = 0
        return out


def summarise(out):
    """The numbers a training loop logs from an audit answer: audits, truth solves, distinct
    truth keys, cached solves, pass, the minimum safety factor."""
    truths = [t for ad in out["audits"] for t in ad["truth"]]
    sfs = [r["truth"] for ad in out["audits"] for r in ad["report"]["rows"] if r.get("check") == "contact_yield"]
    return {
        "audits": len(out["audits"]),
        "truth_solves": len(truths),
        "distinct_keys": len({t["result_key"] for t in truths}),
        "cached": sum(1 for t in truths if t.get("cached")),
        "pass": all(ad["report"]["pass"] for ad in out["audits"]),
        "min_safety_factor": min(sfs) if sfs else None,
    }


def selftest(base_url="http://127.0.0.1:8080", envs=4096, every=512):
    """4096 environments with three distinct peaks: three truth solves, the rest cached (no Isaac needed)."""
    import numpy as np

    a = ForceAudit(["finger"], [contact_yield_check("finger", 25.0, 0.1, 0.02, 0.02, "x_max", "x_min", steel())], base_url=base_url)
    f = np.zeros((envs, 1, 3))
    f[:, 0, 2] = np.array([30.0, 60.0, 90.0])[np.arange(envs) % 3]
    a.observe(f)
    out = a.audit(env_ids=range(0, envs, every))
    s = summarise(out)
    print("audits", s["audits"], "truth solves", s["truth_solves"], "distinct keys", s["distinct_keys"], "cached", s["cached"])
    return out
