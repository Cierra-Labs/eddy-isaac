"""The extension exercised inside Isaac Sim (IX5): run with Isaac's Python beside a reachable
engine —

    /isaac-sim/python.sh kit_check.py --url http://127.0.0.1:8090 --stage <a stage the engine exported>

Enables `eddy.validate` through the Kit extension manager (the repo's exts folder as a search
path), points its `engine_url` setting at the engine, opens the stage, selects its rigid bodies
and runs the two menu actions as the menu would call them: *Validate selection* (the selection
flattened to USDA → `POST /v1/interop.import` → one stress check per box-shaped body →
the sublayer the engine writes composed over the stage) and *Write Eddy sublayer for the
stage*. Then it reads the composed stage back: every selected body must carry the `eddy:`
attributes the sublayer paints, and the sublayer file must sit beside the stage. Headless Kit
has no popup window: the dialog class is stubbed when its extension is absent, and the report
says so — the rest of the path is the real one.

Where the extension comes from (HE2): `--ext-source repo` (this checkout, the default),
`--ext-source zip --ext-zip <path or URL of the GitHub release asset>` (the published bytes,
unpacked into a fresh folder), or `--ext-source registry` (pulled through Kit's extension
manager from the community registry, ~24 h after the release). For zip and registry the
check also requires the extension to run on the `eddy_solve` it carries (`pip_prebundle`).
"""
import argparse
import json
import os
import sys
import time

COMMUNITY = "https://dw290v42wisod.cloudfront.net/exts/kit/community"

ap = argparse.ArgumentParser()
ap.add_argument("--url", default=os.environ.get("SS_URL", "http://127.0.0.1:8080"))
ap.add_argument("--stage", required=True)
ap.add_argument("--out", default="")
ap.add_argument("--ext-source", choices=("repo", "zip", "registry"), default="repo", help="repo: this checkout's exts/ folder; zip: a release zip (the published GitHub asset, a path or an https URL); registry: pulled from a Kit registry (the community one by default)")
ap.add_argument("--ext-zip", default="", help="with --ext-source zip: the release zip's path or URL")
ap.add_argument("--registry-url", default=COMMUNITY)
ap.add_argument("--registry-name", default="kit/community")
ap.add_argument("--ext-version", default="", help="with --ext-source registry: the version to pull (default: the newest listed)")
args = ap.parse_args()
HERE = os.path.dirname(os.path.abspath(__file__))
EXTS = os.path.abspath(os.path.join(HERE, ".."))

# this script sits in the checkout's eddy.validate folder, and Python puts a script's folder first on
# sys.path: `import eddy.validate` would then load the checkout, not the extension under test
if args.ext_source != "repo":
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != HERE]


def fetch_zip(src):
    """The release zip unpacked into a fresh folder; returns its exts/ folder (the archive's layout)."""
    import tempfile
    import urllib.request
    import zipfile

    root = tempfile.mkdtemp(prefix="eddy_ext_")
    path = src
    if src.startswith(("http://", "https://")):
        path = os.path.join(root, "release.zip")
        urllib.request.urlretrieve(src, path)
    with zipfile.ZipFile(path) as z:
        z.extractall(os.path.join(root, "x"))
    exts = os.path.join(root, "x", "exts")
    if not os.path.isdir(os.path.join(exts, "eddy.validate")):
        raise RuntimeError(f"{src}: no exts/eddy.validate inside")
    return exts


def pull_from_registry(mgr):
    """Adds the registry (when absent) through the registry extension's settings, refreshes the
    index and pulls eddy.validate. Kit API names differ between releases: every call is guarded
    and the report says which one answered."""
    import carb.settings

    s = carb.settings.get_settings()
    key = "/exts/omni.kit.registry.nucleus/registries"
    regs = list(s.get(key) or [])
    if not any(isinstance(r, dict) and r.get("url") == args.registry_url for r in regs):
        regs.append({"name": args.registry_name, "url": args.registry_url})
        s.set(key, regs)
    mgr.set_extension_enabled_immediate("omni.kit.registry.nucleus", True)
    for fn in ("refresh_registry", "sync_registry"):
        if hasattr(mgr, fn):
            getattr(mgr, fn)()
    listed = [e for e in (mgr.get_registry_extensions() or []) if e.get("name") == "eddy.validate"]
    if args.ext_version:
        listed = [e for e in listed if str(e.get("version", "")).startswith(args.ext_version) or args.ext_version in e.get("id", "")]
    if not listed:
        raise RuntimeError(f"eddy.validate not listed by {args.registry_url} (registries now {s.get(key)})")
    ext_id = sorted(listed, key=lambda e: e.get("id", ""))[-1]["id"]
    ok = mgr.pull_extension(ext_id)
    return ext_id, ok


from isaacsim import SimulationApp  # noqa: E402

app = SimulationApp({"headless": True})
report = {"engine_url": args.url, "stage": args.stage, "ext_source": args.ext_source, "steps": []}


def step(name, ok, detail=""):
    report["steps"].append({"step": name, "ok": bool(ok), "detail": detail})
    print(f"{'ok ' if ok else 'FAIL'} {name}: {detail}", flush=True)


try:
    import carb.settings
    import omni.kit.app
    import omni.usd

    mgr = omni.kit.app.get_app().get_extension_manager()
    if args.ext_source == "repo":
        mgr.add_path(EXTS)
        where = f"search path {EXTS}"
    elif args.ext_source == "zip":
        z = fetch_zip(args.ext_zip)
        mgr.add_path(z)
        where = f"release zip {args.ext_zip} unpacked at {z}"
    else:
        ext_id, pulled = pull_from_registry(mgr)
        where = f"pulled {ext_id} from {args.registry_url} ({pulled})"
    step("extension found", True, where)
    mgr.set_extension_enabled_immediate("eddy.validate", True)
    step("extension enabled", mgr.is_extension_enabled("eddy.validate"), "eddy.validate through the extension manager")
    carb.settings.get_settings().set("/exts/eddy.validate/engine_url", args.url)
    import eddy.validate as ext
    from eddy.validate import client

    from_checkout = os.path.abspath(ext.__file__).startswith(HERE + os.sep)
    step("module imported", args.ext_source == "repo" or not from_checkout, f"{ext.__file__}")
    origin = client.sdk_origin()
    report["eddy_solve_origin"] = origin
    # a published extension must run on the client it carries, never on this checkout's
    step("eddy_solve origin", origin is not None and (args.ext_source == "repo" or "pip_prebundle" in origin), origin)
    dialog = "real"
    try:
        from omni.kit.window.popup_dialog import MessageDialog  # noqa: F401
    except Exception as e:  # noqa: BLE001
        import types

        class MessageDialog:  # the headless stand-in: what the window would say goes to the report
            def __init__(self, title="", message="", **kw):
                self.message = message

            def show(self):
                report.setdefault("dialogs", []).append(self.message)
                print("   dialog:", self.message, flush=True)

        stub = types.ModuleType("omni.kit.window.popup_dialog")
        stub.MessageDialog = MessageDialog
        sys.modules["omni.kit.window.popup_dialog"] = stub
        dialog = f"stubbed (headless: {str(e)[:60]})"
    step("popup dialog", True, dialog)

    ctx = omni.usd.get_context()
    ctx.open_stage(args.stage)
    stage = ctx.get_stage()
    from pxr import Usd, UsdPhysics

    bodies = [p.GetPath().pathString for p in Usd.PrimRange(stage.GetPseudoRoot()) if p.HasAPI(UsdPhysics.RigidBodyAPI)]
    ctx.get_selection().set_selected_prim_paths(bodies, True)
    sel = list(ctx.get_selection().get_selected_prim_paths())
    step("stage opened and bodies selected", len(sel) == len(bodies) and bodies, f"{len(bodies)} rigid bodies selected: {bodies}")

    t0 = time.perf_counter()
    out = client.validate_selection(ctx, force_n=500.0)
    step("Validate selection", out is not None and "export_key" in out, f"export key {out['export_key'][:16]}… in {time.perf_counter() - t0:.2f} s" if out else "no result")
    root = stage.GetRootLayer()
    subs = list(root.subLayerPaths)
    step("sublayer composed", any("eddy_validate" in s for s in subs), f"root sublayers: {subs}")
    painted = {}
    for b in bodies:
        prim = stage.GetPrimAtPath(b)
        names = sorted(a.GetName() for a in prim.GetAttributes() if a.GetName().startswith("eddy:"))
        painted[b] = names
    step("eddy: attributes on the selected bodies", all(painted[b] for b in bodies), json.dumps(painted))
    sf = {b: stage.GetPrimAtPath(b).GetAttribute("eddy:safety_factor").Get() for b in bodies if stage.GetPrimAtPath(b).HasAttribute("eddy:safety_factor")}
    step("safety factors keyed", True, json.dumps(sf))

    t0 = time.perf_counter()
    out2 = client.write_sublayer_for_stage(ctx)
    step("Write Eddy sublayer for the stage", out2 is not None and "export_key" in out2, f"export key {out2['export_key'][:16]}… in {time.perf_counter() - t0:.2f} s" if out2 else "no result")
    base = os.path.dirname(root.realPath) if root.realPath else os.getcwd()
    files = sorted(f for f in os.listdir(base) if f.startswith("eddy_validate"))
    step("sublayer file beside the stage", bool(files), f"{base}: {files}")
    report["pass"] = all(s["ok"] for s in report["steps"])
except Exception as e:  # noqa: BLE001
    import traceback

    traceback.print_exc()
    report["pass"] = False
    report["error"] = str(e)
finally:
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
    print("KIT-CHECK", "PASS" if report.get("pass") else "FAIL", flush=True)
    app.close()
