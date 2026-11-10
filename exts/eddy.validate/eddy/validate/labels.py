"""Eddy's numbers as labels on synthetic-data frames (HE5), with no Kit in sight. A frame's
observations (per prim: the peak contact force PhysX reported, the heat the part dissipates)
become labels, each carrying the result key of the engine solve that produced its number:

    peak_contact_force  the force the stress solve used (N; PhysX's raw peak rounded up to the
                        bucket, the raw value beside it)   key: the audit's truth solve
    stress_margin       margin of safety = safety factor - 1 at that force (yield / peak von
                        Mises - 1; negative = yields)       key: the same solve
    temperature         the part's peak temperature at that power (K; the power rounded up to its
                        bucket)                             key: the conduction solve

One frame costs at most two requests (one audit batch, one calibrate with every thermal limit)
and repeated buckets cost none: answers are cached per (prim, quantity, bucket) for the
writer's life. `GET /v1/reports/<result_key>` on the engine opens the solve behind any label.
"""
import math

QUANTITIES = ("peak_contact_force", "stress_margin", "temperature")


def round_up(value, bucket):
    return math.ceil(float(value) / bucket) * bucket if bucket and bucket > 0 else float(value)


class PrimSpec:
    """What Eddy needs to label one prim: a box body's size, its material, the load and fixed
    faces for the stress check, and (for temperature) the heat and sink faces, the conductivity,
    the ambient and the allowed temperature."""

    def __init__(self, prim_path, size, material, body=None, quantities=QUANTITIES, force_bucket=25.0, load_region="z_max", fixed_region="z_min",
                 power_bucket=0.5, heat_region="z_max", sink_region="z_min", conductivity=45.0, ambient=293.15, allowed_temperature=353.15):
        self.prim_path = prim_path
        self.body = body or prim_path.rsplit("/", 1)[-1]
        self.size = [float(x) for x in size]
        self.material = dict(material)
        self.quantities = tuple(quantities)
        self.force_bucket, self.load_region, self.fixed_region = float(force_bucket), load_region, fixed_region
        self.power_bucket, self.heat_region, self.sink_region = float(power_bucket), heat_region, sink_region
        self.k, self.ambient, self.allowed = float(conductivity), float(ambient), float(allowed_temperature)

    def geometry(self):
        return {"lx": self.size[0], "ly": self.size[1], "lz": self.size[2]}

    def yield_check(self):
        return {"kind": "contact_yield", "body": self.body, "bucket": self.force_bucket, "geometry": self.geometry(), "load_region": self.load_region, "fixed_region": self.fixed_region, "material": self.material, "min_safety_factor": 1.0}

    def thermal_limit(self, power):
        return {"body": self.body, "geometry": self.geometry(), "heat_region": self.heat_region, "sink_region": self.sink_region, "power": power, "ambient": self.ambient, "allowed_temperature": self.allowed, "k": self.k}


class FrameLabeler:
    def __init__(self, ix, specs, engine_url=""):
        self.ix = ix
        self.specs = {s.prim_path: s for s in specs}
        self.engine_url = engine_url.rstrip("/")
        self.cache = {}  # (prim, "stress"|"thermal", bucket) -> answer
        self.requests = 0

    def _report(self, key):
        return f"{self.engine_url}/v1/reports/{key}" if self.engine_url else f"/v1/reports/{key}"

    def _stress(self, todo):
        """todo: [(spec, bucketed force)] not cached -> one audit batch."""
        if not todo:
            return
        audits = []
        for s, f in todo:
            frames = [{"t": 0.0, "pos": [[0.0, 0.0, 0.0]], "contact_force": [0.0]}, {"t": 1.0, "pos": [[0.0, 0.0, 0.0]], "contact_force": [f]}]
            audits.append({"rollout": {"engine": "physx", "version": "replicator", "device": "", "bodies": [s.body], "frames": frames}, "checks": [s.yield_check()]})
        out = self.ix.audit_batch(audits)
        self.requests += 1
        for (s, f), ad in zip(todo, out["audits"]):
            row = next(r for r in ad["report"]["rows"] if r.get("check") == "contact_yield")
            key = row.get("truth_key") or ad["truth"][0]["result_key"]
            self.cache[(s.prim_path, "stress", f)] = {"safety_factor": float(row["truth"]), "force": float(row["foreign"]), "result_key": key, "pass": bool(row["pass"])}

    def _thermal(self, todo):
        if not todo:
            return
        cal = self.ix.calibrate(thermal_limits=[s.thermal_limit(p) for s, p in todo])
        self.requests += 1
        for (s, p), t in zip(todo, cal["thermal_limits"]):
            self.cache[(s.prim_path, "thermal", p)] = {"temperature": float(t["peak_temperature"]), "power_limit": float(t["power_limit"]), "result_key": t["result_key"]}

    def label(self, frame, observations):
        """observations: {prim_path: {"contact_force": N, "power": W}} (either may be absent).
        Returns the frame's label document."""
        stress, thermal, plan = [], [], []
        for prim, obs in observations.items():
            s = self.specs.get(prim)
            if s is None:
                continue
            if "contact_force" in obs and ({"peak_contact_force", "stress_margin"} & set(s.quantities)):
                f = round_up(obs["contact_force"], s.force_bucket)
                plan.append((s, "stress", f, float(obs["contact_force"])))
                if (prim, "stress", f) not in self.cache and (s, f) not in stress:
                    stress.append((s, f))
            if "power" in obs and "temperature" in s.quantities:
                p = round_up(obs["power"], s.power_bucket)
                plan.append((s, "thermal", p, float(obs["power"])))
                if (prim, "thermal", p) not in self.cache and (s, p) not in thermal:
                    thermal.append((s, p))
        self._stress(stress)
        self._thermal(thermal)
        labels = []
        for s, kind, b, raw in plan:
            a = self.cache[(s.prim_path, kind, b)]
            if kind == "stress":
                if "peak_contact_force" in s.quantities:
                    labels.append({"prim": s.prim_path, "quantity": "peak_contact_force", "value": a["force"], "unit": "N", "observed": raw, "bucket": s.force_bucket, "result_key": a["result_key"], "report": self._report(a["result_key"])})
                if "stress_margin" in s.quantities:
                    labels.append({"prim": s.prim_path, "quantity": "stress_margin", "value": a["safety_factor"] - 1.0, "unit": "1", "safety_factor": a["safety_factor"], "at_force": a["force"], "result_key": a["result_key"], "report": self._report(a["result_key"])})
            else:
                labels.append({"prim": s.prim_path, "quantity": "temperature", "value": a["temperature"], "unit": "K", "observed_power": raw, "at_power": b, "power_limit": a["power_limit"], "result_key": a["result_key"], "report": self._report(a["result_key"])})
        return {"frame": int(frame), "labels": labels}
