"""The Replicator labels outside Kit (HE5): a fake engine checks the batching and the caching;
with SS_URL set, frames are labelled by that engine and every label's key must open its report."""
import importlib.util
import json
import os
import sys
import unittest
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
EXT = os.path.abspath(os.path.join(HERE, ".."))


def _load(name):
    spec = importlib.util.spec_from_file_location(f"_eddy_{name}", os.path.join(EXT, "eddy", "validate", f"{name}.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


labels = _load("labels")
client = _load("client")
STEEL = {"e": 210e9, "nu": 0.3, "rho": 7850.0, "yield": 250e6}


class FakeInterop:
    def __init__(self):
        self.audits, self.calibrates = [], []

    def audit_batch(self, audits):
        self.audits.append(audits)
        out = []
        for a in audits:
            f = a["rollout"]["frames"][-1]["contact_force"][0]
            out.append({"truth": [{"result_key": f"b3:s{f:g}"}], "report": {"rows": [{"check": "contact_yield", "truth": 1000.0 / f, "pass": f < 1000, "foreign": f, "truth_key": f"b3:s{f:g}"}]}})
        return {"audits": out}

    def calibrate(self, thermal_limits):
        self.calibrates.append(thermal_limits)
        return {"thermal_limits": [{"peak_temperature": 293.15 + 10 * t["power"], "power_limit": 6.0, "result_key": f"b3:t{t['power']:g}"} for t in thermal_limits]}


def specs():
    return [labels.PrimSpec("/World/Finger", [0.06, 0.02, 0.02], STEEL), labels.PrimSpec("/World/Palm", [0.1, 0.1, 0.02], STEEL, quantities=("temperature",))]


class TestLabels(unittest.TestCase):
    def test_a_frame_is_two_requests_and_every_label_is_keyed(self):
        ix = FakeInterop()
        fl = labels.FrameLabeler(ix, specs(), engine_url="http://e:1/")
        doc = fl.label(0, {"/World/Finger": {"contact_force": 130.0, "power": 1.2}, "/World/Palm": {"contact_force": 40.0, "power": 2.0}})
        self.assertEqual((len(ix.audits), len(ix.calibrates)), (1, 1))
        q = {(l["prim"], l["quantity"]): l for l in doc["labels"]}
        self.assertEqual(set(q), {("/World/Finger", "peak_contact_force"), ("/World/Finger", "stress_margin"), ("/World/Finger", "temperature"), ("/World/Palm", "temperature")})
        f = q[("/World/Finger", "peak_contact_force")]
        self.assertEqual((f["value"], f["observed"], f["result_key"]), (150.0, 130.0, "b3:s150"))
        m = q[("/World/Finger", "stress_margin")]
        self.assertAlmostEqual(m["value"], 1000.0 / 150.0 - 1.0)
        self.assertEqual(m["result_key"], f["result_key"])
        t = q[("/World/Finger", "temperature")]
        self.assertEqual((t["at_power"], t["result_key"], t["report"]), (1.5, "b3:t1.5", "http://e:1/v1/reports/b3:t1.5"))
        self.assertTrue(all(l["result_key"] for l in doc["labels"]))

    def test_repeated_buckets_cost_nothing(self):
        ix = FakeInterop()
        fl = labels.FrameLabeler(ix, specs())
        fl.label(0, {"/World/Finger": {"contact_force": 130.0, "power": 1.2}})
        fl.label(1, {"/World/Finger": {"contact_force": 140.0, "power": 1.4}})  # same buckets: 150 N, 1.5 W
        self.assertEqual((len(ix.audits), len(ix.calibrates), fl.requests), (1, 1, 2))
        fl.label(2, {"/World/Finger": {"contact_force": 160.0}})
        self.assertEqual(len(ix.audits), 2)

    def test_unknown_prims_and_missing_observations_are_skipped(self):
        ix = FakeInterop()
        doc = labels.FrameLabeler(ix, specs()).label(3, {"/World/Other": {"contact_force": 1.0}, "/World/Finger": {}})
        self.assertEqual(doc, {"frame": 3, "labels": []})
        self.assertEqual((ix.audits, ix.calibrates), ([], []))


@unittest.skipUnless(os.environ.get("SS_URL"), "SS_URL not set: no live engine")
class TestLive(unittest.TestCase):
    def test_frames_against_the_engine(self):
        url = os.environ["SS_URL"].rstrip("/")
        fl = labels.FrameLabeler(client.Interop(url), specs(), engine_url=url)
        docs = [fl.label(i, {"/World/Finger": {"contact_force": 30.0 * (i + 1), "power": 0.7 * (i + 1)}, "/World/Palm": {"power": 1.0}}) for i in range(4)]
        keys = {l["result_key"] for d in docs for l in d["labels"]}
        for k in keys:
            with urllib.request.urlopen(f"{url}/v1/reports/{k}", timeout=120) as r:
                self.assertEqual(json.loads(r.read().decode("utf-8"))["result_key"], k)
        temps = [l["value"] for l in docs[3]["labels"] if l["quantity"] == "temperature" and l["prim"] == "/World/Finger"]
        self.assertGreater(temps[0], 293.15)
        self.assertLessEqual(fl.requests, 8)


if __name__ == "__main__":
    unittest.main()
