"""HE4 inside Isaac Sim: an Action Graph triggers Eddy's truth solve, audit and calibrate and
writes the results onto a prim. Run with Isaac's Python beside a reachable engine:

    /isaac-sim/python.sh graph_check.py --url http://127.0.0.1:8090 --out /tmp/he4.json --save-stage /tmp/he4_graph.usda

Enables `eddy.validate` (from this checkout's exts/ folder, or `--exts <folder>` holding an
unpacked release's `eddy.validate`) and `omni.graph.action`, makes a stage with one steel finger
prim, builds the example graph (`graph_setup.build_example_graph`: OnImpulseEvent -> Eddy Truth
Solve -> Eddy Audit -> Eddy Calibrate, every node writing onto /World/Finger), fires the impulse,
evaluates, and reads the prim's `eddy:*` attributes back; every result key must open a report on
the engine (`GET /v1/reports/<key>`). Saves the stage with the graph, so the example ships as USD.
"""
import argparse
import json
import os
import sys
import time
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--url", default=os.environ.get("SS_URL", "http://127.0.0.1:8080"))
ap.add_argument("--exts", default="", help="the folder holding eddy.validate (default: this checkout's exts/)")
ap.add_argument("--peak", type=float, default=130.0, help="the peak contact force the audit grades (N)")
ap.add_argument("--force-script", action="store_true", help="build the graph from ScriptNodes even when the OGN types registered")
ap.add_argument("--out", default="")
ap.add_argument("--save-stage", default="")
args = ap.parse_args()
HERE = os.path.dirname(os.path.abspath(__file__))
EXTS = os.path.abspath(args.exts or os.path.join(HERE, ".."))

# this script sits in the checkout's eddy.validate folder, and Python puts a script's folder first on
# sys.path: `import eddy.validate` would then load the checkout, not the extension under test
if args.exts:
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != HERE]

from isaacsim import SimulationApp  # noqa: E402

app = SimulationApp({"headless": True})
report = {"engine_url": args.url, "exts": EXTS, "steps": []}


def step(name, ok, detail=""):
    report["steps"].append({"step": name, "ok": bool(ok), "detail": detail})
    print(f"{'ok ' if ok else 'FAIL'} {name}: {detail}", flush=True)


try:
    import carb.settings
    import omni.kit.app
    import omni.usd

    mgr = omni.kit.app.get_app().get_extension_manager()
    mgr.add_path(EXTS)
    for ext in ("omni.graph.action", "omni.graph.scriptnode", "eddy.validate"):
        mgr.set_extension_enabled_immediate(ext, True)
    step("extensions enabled", mgr.is_extension_enabled("eddy.validate") and mgr.is_extension_enabled("omni.graph.action"), "eddy.validate, omni.graph.action, omni.graph.scriptnode")
    carb.settings.get_settings().set("/exts/eddy.validate/engine_url", args.url)
    import eddy.validate as _ext

    report["extension_file"] = _ext.__file__
    step("extension under test", not args.exts or not os.path.abspath(_ext.__file__).startswith(HERE + os.sep), _ext.__file__)
    for _ in range(5):
        app.update()  # OmniGraph registers Python nodes as the extension loads
    from eddy.validate import client, graph_setup

    how_reg = graph_setup.ensure_registered()
    reg = graph_setup.registered()
    report["registered"] = reg
    step("node types registered", len(reg) == 3, f"{how_reg}: {reg}")
    step("eddy_solve origin", client.sdk_origin() is not None, client.sdk_origin())

    ctx = omni.usd.get_context()
    ctx.new_stage()
    stage = ctx.get_stage()
    from pxr import UsdGeom

    UsdGeom.Xform.Define(stage, "/World")
    cube = UsdGeom.Cube.Define(stage, "/World/Finger")
    cube.AddScaleOp().Set((0.06, 0.02, 0.02))
    graph, nodes, how = graph_setup.build_example_graph("/World/Finger", peak_force=args.peak, engine_url=args.url, force_script=args.force_script)
    step("action graph built", graph is not None, f"{how}: {sorted(nodes)}")
    report["graph_nodes_impl"] = how
    t0 = time.perf_counter()
    graph_setup.trigger(graph, nodes)
    for _ in range(3):
        app.update()
    report["evaluate_s"] = time.perf_counter() - t0
    prim = stage.GetPrimAtPath("/World/Finger")
    attrs = {a.GetName(): a.Get() for a in prim.GetAttributes() if a.GetName().startswith("eddy:")}
    report["prim_attrs"] = {k: (v if isinstance(v, (int, float, str, bool)) else str(v)) for k, v in attrs.items()}
    for kind in ("truth", "audit", "calibrate"):
        got = sorted(k for k in attrs if k.startswith(f"eddy:{kind}:"))
        step(f"eddy:{kind}:* written by the graph", bool(got), got)
    sf = attrs.get("eddy:audit:safety_factor")
    step("audit safety factor on the prim", isinstance(sf, float) and sf > 0, sf)
    keys = [v for k, v in attrs.items() if k.endswith(":result_key") and v]
    opened = {}
    for k in keys:
        try:
            with urllib.request.urlopen(f"{args.url.rstrip('/')}/v1/reports/{k}", timeout=60) as r:
                opened[k] = json.loads(r.read().decode("utf-8")).get("result_key") == k
        except Exception as e:  # noqa: BLE001
            opened[k] = f"refused: {e}"
    step("every result key opens its report", keys and all(v is True for v in opened.values()), opened)
    if args.save_stage:
        stage.GetRootLayer().Export(args.save_stage)
        step("stage with the graph saved", os.path.exists(args.save_stage), args.save_stage)
    report["pass"] = all(s["ok"] for s in report["steps"] if s["step"] != "node types registered") and any(s["ok"] for s in report["steps"] if s["step"].startswith("eddy:audit"))
except Exception as e:  # noqa: BLE001
    import traceback

    traceback.print_exc()
    report["pass"] = False
    report["error"] = str(e)
finally:
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
    print("GRAPH-CHECK", "PASS" if report.get("pass") else "FAIL", f"(nodes: {report.get('graph_nodes_impl', '?')})", flush=True)
    app.close()
