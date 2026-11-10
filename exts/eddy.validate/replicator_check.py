"""HE5 inside Isaac Sim: a Replicator run writes frames plus Eddy labels, and every label's key
opens the solve that produced it. Run with Isaac's Python beside a reachable engine:

    /isaac-sim/python.sh replicator_check.py --url http://127.0.0.1:8090 --out-dir /tmp/he5_frames --out /tmp/he5.json

Enables omni.replicator.core and `eddy.validate` (this checkout's exts/, or `--exts`), registers
`EddyLabelWriter`, builds a stage with a steel finger, a light and a camera, attaches the writer
to a 320 x 240 render product, and steps `--frames` frames; before each, the finger's
`eddy:obs:contact_force` / `eddy:obs:power` change (what a simulation or a sensor script would
keep current). Then it reads `eddy_labels_*.json` back: every frame labelled, every label keyed,
every key opened with `GET /v1/reports/<key>`; the RGB frames counted.
"""
import argparse
import glob
import json
import os
import sys
import time
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--url", default=os.environ.get("SS_URL", "http://127.0.0.1:8080"))
ap.add_argument("--exts", default="")
ap.add_argument("--frames", type=int, default=6)
ap.add_argument("--out-dir", required=True)
ap.add_argument("--out", default="")
args = ap.parse_args()
HERE = os.path.dirname(os.path.abspath(__file__))
EXTS = os.path.abspath(args.exts or os.path.join(HERE, ".."))

# this script sits in the checkout's eddy.validate folder, and Python puts a script's folder first on
# sys.path: `import eddy.validate` would then load the checkout, not the extension under test
if args.exts:
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != HERE]

from isaacsim import SimulationApp  # noqa: E402

app = SimulationApp({"headless": True})
report = {"engine_url": args.url, "out_dir": args.out_dir, "steps": []}


def step(name, ok, detail=""):
    report["steps"].append({"step": name, "ok": bool(ok), "detail": detail})
    print(f"{'ok ' if ok else 'FAIL'} {name}: {detail}", flush=True)


try:
    import carb.settings
    import omni.kit.app
    import omni.usd

    mgr = omni.kit.app.get_app().get_extension_manager()
    mgr.add_path(EXTS)
    for ext in ("omni.replicator.core", "eddy.validate"):
        mgr.set_extension_enabled_immediate(ext, True)
    step("extensions enabled", mgr.is_extension_enabled("omni.replicator.core") and mgr.is_extension_enabled("eddy.validate"), "omni.replicator.core, eddy.validate")
    carb.settings.get_settings().set("/exts/eddy.validate/engine_url", args.url)
    import eddy.validate as _ext

    report["extension_file"] = _ext.__file__
    step("extension under test", not args.exts or not os.path.abspath(_ext.__file__).startswith(HERE + os.sep), _ext.__file__)
    import omni.replicator.core as rep

    from eddy.validate import replicator_writer

    reg = replicator_writer.register()
    step("writer registered", reg in ("registered",) or "already" in reg, reg)

    ctx = omni.usd.get_context()
    ctx.new_stage()
    stage = ctx.get_stage()
    from pxr import Sdf, UsdGeom, UsdLux

    UsdGeom.Xform.Define(stage, "/World")
    cube = UsdGeom.Cube.Define(stage, "/World/Finger")
    cube.AddScaleOp().Set((0.06, 0.02, 0.02))
    UsdLux.DomeLight.Define(stage, "/World/Dome").CreateIntensityAttr(1000.0)
    prim = cube.GetPrim()
    fa = prim.CreateAttribute("eddy:obs:contact_force", Sdf.ValueTypeNames.Double, custom=True)
    pa = prim.CreateAttribute("eddy:obs:power", Sdf.ValueTypeNames.Double, custom=True)
    fa.Set(0.0)
    pa.Set(0.0)
    cam = rep.create.camera(position=(0.25, 0.25, 0.2), look_at="/World/Finger")
    rp = rep.create.render_product(cam, (320, 240))
    os.makedirs(args.out_dir, exist_ok=True)
    w = rep.WriterRegistry.get("EddyLabelWriter")
    w.initialize(output_dir=args.out_dir, engine_url=args.url, prims=[{"prim_path": "/World/Finger", "size": [0.06, 0.02, 0.02], "material": {"e": 210e9, "nu": 0.3, "rho": 7850.0, "yield": 250e6}}])
    w.attach([rp])
    t0 = time.perf_counter()
    for i in range(args.frames):
        fa.Set(40.0 * (i + 1))
        pa.Set(0.8 * (i + 1))
        rep.orchestrator.step(rt_subframes=1)
    rep.orchestrator.wait_until_complete()
    report["run_s"] = time.perf_counter() - t0
    docs = []
    for p in sorted(glob.glob(os.path.join(args.out_dir, "eddy_labels_*.json"))):
        with open(p, encoding="utf-8") as f:
            docs.append(json.load(f))
    rgbs = sorted(glob.glob(os.path.join(args.out_dir, "rgb_*.png")))
    step("frames labelled", len(docs) >= args.frames, f"{len(docs)} label files, {len(rgbs)} rgb frames")
    labels = [l for d in docs for l in d["labels"]]
    errors = [d.get("error") for d in docs if d.get("error")]
    step("no labelling errors", not errors, errors[:2])
    quantities = sorted({l["quantity"] for l in labels})
    step("three quantities", quantities == ["peak_contact_force", "stress_margin", "temperature"], quantities)
    step("every label keyed", labels and all(l.get("result_key") for l in labels), f"{len(labels)} labels")
    opened = {}
    for k in sorted({l["result_key"] for l in labels}):
        try:
            with urllib.request.urlopen(f"{args.url.rstrip('/')}/v1/reports/{k}", timeout=60) as r:
                opened[k] = json.loads(r.read().decode("utf-8")).get("result_key") == k
        except Exception as e:  # noqa: BLE001
            opened[k] = f"refused: {e}"
    step("every key opens the solve that produced it", opened and all(v is True for v in opened.values()), opened)
    report["sample_labels"] = docs[-1]["labels"] if docs else []
    report["engine_requests"] = docs[-1].get("engine_requests_so_far") if docs else None
    report["pass"] = all(s["ok"] for s in report["steps"])
except Exception as e:  # noqa: BLE001
    import traceback

    traceback.print_exc()
    report["pass"] = False
    report["error"] = str(e)
finally:
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
    print("REPLICATOR-CHECK", "PASS" if report.get("pass") else "FAIL", flush=True)
    app.close()
