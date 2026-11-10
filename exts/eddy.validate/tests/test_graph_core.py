"""The OmniGraph nodes' compute outside Kit (HE4): `python -m unittest discover -s tests` from the
extension folder. A fake engine checks the request shapes and the db mapping; with SS_URL set the
same computes run against that engine and every result key must open its report; with usd-core
(`pip install usd-core`) the prim writing runs on a real USD stage."""
import importlib.util
import json
import os
import sys
import types
import unittest
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
EXT = os.path.abspath(os.path.join(HERE, ".."))


def _load(name):
    spec = importlib.util.spec_from_file_location(f"_eddy_{name}", os.path.join(EXT, "eddy", "validate", f"{name}.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


gc = _load("graph_core")
client = _load("client")  # puts eddy_solve on the path (prebundle, installed, or the checkout)

try:
    from pxr import Usd, UsdGeom

    HAVE_USD = True
except ImportError:
    HAVE_USD = False

STEEL = dict(youngsModulus=210e9, poissonRatio=0.3, density=7850.0, yieldStrength=250e6)


def db_for(kind, **over):
    base = dict(engineUrl="", body="finger", targetPrimPath="", writeToPrim=False, **STEEL)
    base.update({
        "audit": dict(peakForce=130.0, bucket=25.0, size=(0.06, 0.02, 0.02), loadRegion="x_max", fixedRegion="x_min", minSafetyFactor=1.0),
        "truth": dict(force=500.0, size=(0.06, 0.02, 0.02), loadRegion="z_max", fixedRegion="z_min"),
        "calibrate": dict(geometryKind="sphere", radius=0.01, padSize=(0.02, 0.02, 0.005), force=20.0, effectiveMass=0.2),
    }[kind])
    base.update(over)
    return types.SimpleNamespace(inputs=types.SimpleNamespace(**base), outputs=types.SimpleNamespace())


class FakeInterop:
    def __init__(self):
        self.calls = []

    def calibrate(self, **kw):
        self.calls.append(("calibrate", kw))
        if "load_limits" in kw:
            return {"load_limits": [{"result_key": "b3:truth", "peak_stress": 1e6, "safety_factor_at_probe": 250.0, "force_limit": 1.25e5}], "calibration_key": "b3:cal"}
        return {"contacts": [{"physx": {"compliant_contact_stiffness": 1.6e7, "compliant_contact_damping": 2.5e3, "contact_offset": 1e-4}, "restitution": 0.05, "referee": "Hertz"}], "truth": [], "calibration_key": "b3:cal2"}

    def audit_batch(self, audits):
        self.calls.append(("audit", audits))
        f = audits[0]["rollout"]["frames"][-1]["contact_force"][0]
        b = audits[0]["checks"][0]["bucket"]
        bucketed = -(-f // b) * b
        return {"audits": [{"rollout_key": "b3:roll", "truth": [{"result_key": "b3:aud"}], "report": {"pass": True, "rows": [{"check": "contact_yield", "truth": 660.0, "pass": True, "foreign": bucketed, "truth_key": "b3:aud"}]}}]}


class TestCompute(unittest.TestCase):
    def test_audit_maps_inputs_and_outputs(self):
        ix = FakeInterop()
        db = db_for("audit")
        ok, res = gc.compute_node("audit", db, ix, enabled="ENABLED")
        self.assertTrue(ok, res)
        kind, audits = ix.calls[0]
        self.assertEqual(kind, "audit")
        chk = audits[0]["checks"][0]
        self.assertEqual((chk["kind"], chk["load_region"], chk["geometry"]), ("contact_yield", "x_max", {"lx": 0.06, "ly": 0.02, "lz": 0.02}))
        self.assertEqual(db.outputs.bucketedForce, 150.0)
        self.assertEqual(db.outputs.resultKey, "b3:aud")
        self.assertTrue(db.outputs.passed)
        self.assertEqual(db.outputs.execOut, "ENABLED")

    def test_truth_pushes_into_the_load_face(self):
        ix = FakeInterop()
        ok, _ = gc.compute_node("truth", db_for("truth"), ix)
        self.assertTrue(ok)
        self.assertEqual(ix.calls[0][1]["load_limits"][0]["force"], [0.0, 0.0, -500.0])
        ok, _ = gc.compute_node("truth", db_for("truth", loadRegion="x_min", fixedRegion="x_max"), ix)
        self.assertEqual(ix.calls[1][1]["load_limits"][0]["force"], [500.0, 0.0, 0.0])

    def test_calibrate_reads_the_physx_form(self):
        db = db_for("calibrate")
        ok, res = gc.compute_node("calibrate", db, FakeInterop())
        self.assertTrue(ok)
        self.assertEqual((db.outputs.stiffness, db.outputs.damping, db.outputs.calibrationKey), (1.6e7, 2.5e3, "b3:cal2"))

    def test_a_refused_route_is_a_node_error(self):
        class Refusing:
            def audit_batch(self, audits):
                raise RuntimeError("INTEROP_INVALID: nope")

        ok, err = gc.compute_node("audit", db_for("audit"), Refusing())
        self.assertFalse(ok)
        self.assertIn("INTEROP_INVALID", err)

    def test_prim_attrs_carry_the_key(self):
        a = dict(gc.prim_attrs("audit", {"resultKey": "b3:k", "safetyFactor": 2.0, "passed": True, "bucketedForce": 150.0, "rolloutKey": "b3:r", "reportJson": "{}"}))
        self.assertEqual(a["eddy:audit:result_key"], "b3:k")
        self.assertEqual(a["eddy:audit:safety_factor"], 2.0)
        self.assertNotIn("eddy:audit:report_json", a)

    def test_ogn_files_match_the_compute(self):
        gs = _load("graph_setup")
        files = {"truth": "OgnEddyTruthSolve", "audit": "OgnEddyAudit", "calibrate": "OgnEddyCalibrate"}
        for kind, name in files.items():
            with open(os.path.join(EXT, "eddy", "validate", "nodes", f"{name}.ogn"), encoding="utf-8") as f:
                spec = json.load(f)[name[3:]]
            self.assertEqual(spec["language"], "Python")
            ins = {k: v["type"] for k, v in spec["inputs"].items() if k != "execIn"}
            outs = {k: v["type"] for k, v in spec["outputs"].items() if k != "execOut"}
            self.assertEqual(ins, gs.INPUTS[kind], kind)
            self.assertEqual(set(outs), set(gc.OUTPUTS[kind]), kind)
            self.assertEqual({k: gs.OUT_TYPES[k] for k in outs}, outs, kind)
            self.assertTrue(os.path.exists(os.path.join(EXT, "eddy", "validate", "nodes", f"{name}.py")))
            self.assertEqual(gs.NODE_TYPES[kind], f"eddy.validate.{name[3:]}")

    @unittest.skipUnless(HAVE_USD, "usd-core not installed")
    def test_writes_onto_a_prim(self):
        st = Usd.Stage.CreateInMemory()
        UsdGeom.Cube.Define(st, "/World/Finger")
        db = db_for("audit", targetPrimPath="/World/Finger", writeToPrim=True)
        ok, res = gc.compute_node("audit", db, FakeInterop(), stage=st)
        self.assertTrue(ok)
        p = st.GetPrimAtPath("/World/Finger")
        self.assertEqual(p.GetAttribute("eddy:audit:result_key").Get(), "b3:aud")
        self.assertTrue(p.GetAttribute("eddy:audit:passed").Get())
        with self.assertRaises(ValueError):
            gc.write_prim_attrs(st, "/World/Nothing", [("eddy:x", 1.0)])


@unittest.skipUnless(os.environ.get("SS_URL"), "SS_URL not set: no live engine")
class TestLive(unittest.TestCase):
    def setUp(self):
        self.url = os.environ["SS_URL"].rstrip("/")
        self.ix = client.Interop(self.url)

    def opens(self, key):
        with urllib.request.urlopen(f"{self.url}/v1/reports/{key}", timeout=120) as r:
            return json.loads(r.read().decode("utf-8"))["result_key"] == key

    def test_three_nodes_against_the_engine(self):
        for kind in ("truth", "audit", "calibrate"):
            db = db_for(kind)
            ok, res = gc.compute_node(kind, db, self.ix)
            self.assertTrue(ok, res)
            if res.get("resultKey"):
                self.assertTrue(self.opens(res["resultKey"]), kind)
        db = db_for("audit")
        gc.compute_node("audit", db, self.ix)
        self.assertEqual(db.outputs.bucketedForce, 150.0)
        self.assertGreater(db.outputs.safetyFactor, 1.0)


if __name__ == "__main__":
    unittest.main()
