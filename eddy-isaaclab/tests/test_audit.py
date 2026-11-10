"""Unit tests for the hook, outside Isaac: `python -m unittest discover -s tests` (numpy needed).
With SS_URL set, the live test posts a 4096-environment batch to that engine."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if not os.environ.get("EDDY_TEST_INSTALLED"):  # set it to test the installed wheels instead of the checkout
    sys.path.insert(0, os.path.join(HERE, "..", "src"))
    sys.path.append(os.path.join(HERE, "..", "..", "..", "..", "sdks", "eddy-python"))

import numpy as np  # noqa: E402

from eddy_isaaclab import ForceAudit, contact_yield_check, steel, summarise  # noqa: E402


class FakeInterop:
    def __init__(self):
        self.calls = []

    def audit_batch(self, audits):
        self.calls.append(audits)
        out = []
        for a in audits:
            peaks = a["rollout"].to_dict()["frames"][-1]["contact_force"]
            out.append({"truth": [{"result_key": f"k{p}", "cached": False} for p in peaks], "report": {"pass": True, "rows": [{"check": "contact_yield", "truth": 100.0 / max(p, 1.0)} for p in peaks]}})
        return {"audits": out}


def make(envs=4096, client=None):
    a = ForceAudit(["finger", "palm"], [contact_yield_check("finger", 25.0, 0.06, 0.02, 0.02, "x_max", "x_min", steel())], client=client or FakeInterop())
    f = np.zeros((envs, 2, 3))
    f[:, 0, 2] = np.array([30.0, 60.0, 90.0, 61.0])[np.arange(envs) % 4]
    f[:, 1, 0] = 5.0
    return a, f


class TestForceAudit(unittest.TestCase):
    def test_peak_is_the_running_maximum(self):
        a, f = make(8)
        a.observe(f)
        g = f.copy()
        g[:, 0, 2] *= 0.5
        a.observe(g)
        self.assertTrue(np.allclose(a.peak[:, 0], f[:, 0, 2]))

    def test_every_env_is_an_item_without_dedupe(self):
        a, f = make()
        a.observe(f)
        audits, m = a.build_batch()
        self.assertEqual(len(audits), 4096)
        self.assertEqual(len(m), 4096)
        r = audits[1]["rollout"].to_dict()
        self.assertEqual(len(r["frames"]), 2)
        self.assertEqual(r["frames"][-1]["contact_force"], [60.0, 5.0])

    def test_dedupe_shares_items_by_bucket(self):
        a, f = make()
        a.observe(f)
        audits, m = a.build_batch(dedupe=True)
        # 30 -> 50, 60 -> 75, 61 -> 75, 90 -> 100: three buckets for the finger; the palm has no check (raw 5.0)
        self.assertEqual(len(audits), 3)
        self.assertEqual(sorted(tuple(x["rollout"].to_dict()["frames"][-1]["contact_force"]) for x in audits), [(50.0, 5.0), (75.0, 5.0), (100.0, 5.0)])
        self.assertEqual(m[1], m[3])  # 60 and 61 share the 75 N bucket

    def test_audit_resets_and_maps_envs(self):
        fake = FakeInterop()
        a, f = make(16, client=fake)
        a.observe(f)
        out = a.audit(dedupe=True)
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(set(out["env_to_audit"]), {str(e) for e in range(16)})
        self.assertIsNone(a.peak)
        s = summarise(out)
        self.assertEqual(s["audits"], 3)
        self.assertTrue(s["pass"])

    def test_nothing_observed_is_no_request(self):
        fake = FakeInterop()
        a = ForceAudit(["b"], [], client=fake)
        self.assertIsNone(a.audit())
        self.assertEqual(fake.calls, [])


@unittest.skipUnless(os.environ.get("SS_URL"), "SS_URL not set: no live engine")
class TestLive(unittest.TestCase):
    def test_4096_envs_one_batch(self):
        a = ForceAudit(["finger"], [contact_yield_check("finger", 25.0, 0.06, 0.02, 0.02, "x_max", "x_min", steel())], base_url=os.environ["SS_URL"])
        f = np.zeros((4096, 1, 3))
        f[:, 0, 2] = np.array([30.0, 60.0, 90.0])[np.arange(4096) % 3]
        a.observe(f)
        out = a.audit()
        s = summarise(out)
        self.assertEqual(s["audits"], 4096)
        self.assertEqual(s["distinct_keys"], 3)


if __name__ == "__main__":
    unittest.main()
