"""The extension's client side: the selection → USDA text → the engine →
the sublayer back onto the stage. Pure functions where Kit is not
needed (the self-test runs them outside Kit against a running engine).
"""
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
EXT_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))


def _sdk_paths():
    """Where `eddy_solve` comes from, in order: the copy the published extension carries
    (`pip_prebundle/`, written by integrations/publish/build_dists.py — the version tested
    with this extension), an `eddy-solve` pip-installed into Kit's Python, then a repository
    checkout's `sdks/eddy-python` (development)."""
    pre = os.path.join(EXT_ROOT, "pip_prebundle")
    repo = os.path.abspath(os.path.join(EXT_ROOT, "..", "..", "..", "..", "sdks", "eddy-python"))
    return pre, repo


_pre, _repo = _sdk_paths()
if os.path.isdir(_pre) and _pre not in sys.path:
    sys.path.insert(0, _pre)
try:
    from eddy_solve.interop import Interop
except Exception:  # noqa: BLE001
    if os.path.isdir(_repo) and _repo not in sys.path:
        sys.path.append(_repo)
    try:
        from eddy_solve.interop import Interop
    except Exception:  # pragma: no cover
        Interop = None


def sdk_origin():
    """The file `eddy_solve` was imported from (the checks report it)."""
    try:
        import eddy_solve

        return os.path.dirname(os.path.abspath(eddy_solve.__file__))
    except Exception:  # noqa: BLE001
        return None


def _settings():
    try:
        import carb.settings

        s = carb.settings.get_settings()
        return s.get("/exts/eddy.validate/engine_url") or "http://127.0.0.1:8080", s.get("/exts/eddy.validate/api_key") or None
    except Exception:  # noqa: BLE001
        return os.environ.get("SS_URL", "http://127.0.0.1:8080"), os.environ.get("SS_API_KEY")


def _flatten_selection(stage, paths):
    """The selected prims and their ancestors flattened into one USDA text — the engine reads the text form."""
    from pxr import Sdf, Usd

    layer = Sdf.Layer.CreateAnonymous("eddy_selection.usda")
    tmp = Usd.Stage.Open(layer)
    tmp.SetMetadata("metersPerUnit", stage.GetMetadata("metersPerUnit") or 1.0)
    tmp.SetMetadata("upAxis", stage.GetMetadata("upAxis") or "Z")
    flat = stage.Flatten()
    for p in paths:
        src = flat.GetPrimAtPath(p)
        if not src:
            continue
        # the target layer is empty: CopySpec refuses a path whose parent prim is not there
        # (Tf.ErrorException inside Kit — found by kit_check.py on Isaac Sim 6.0.1); the
        # ancestors are created first, as bare defs, so the copied prim keeps its stage path
        parent = Sdf.Path(p).GetParentPath()
        if parent and parent != Sdf.Path.absoluteRootPath:
            Sdf.CreatePrimInLayer(layer, parent)
        Sdf.CopySpec(flat, Sdf.Path(p), layer, Sdf.Path(p))
    # the stage's physics scene beside the selection, so the import reads its gravity
    for path in (Sdf.Path("/World/physicsScene"), Sdf.Path("/physicsScene")):
        if flat.GetPrimAtPath(path) and not layer.GetPrimAtPath(path):
            Sdf.CreatePrimInLayer(layer, path.GetParentPath())
            Sdf.CopySpec(flat, path, layer, path)
    return layer.ExportToString()


def import_selection(ix, usda_text):
    return ix.import_scene("usda", text=usda_text)


def sublayer_for(ix, imported, results=None, contacts=None, meters_per_unit=1.0):
    usd = {"form": "sublayer", "prim_paths": imported["report"]["prim_paths"], "meters_per_unit": meters_per_unit}
    if contacts:
        usd["contacts"] = contacts
    return ix.export_scene(imported["scene"], format="usda", usd=usd, results=results or [])


def compose_sublayer(stage, text, name="eddy_validate.usda"):
    """Writes the sublayer next to the root layer and composes it (non-destructively) over the stage."""
    from pxr import Sdf

    root = stage.GetRootLayer()
    base = os.path.dirname(root.realPath) if root.realPath else os.getcwd()
    path = os.path.join(base, name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    ident = Sdf.Layer.FindOrOpen(path).identifier
    if ident not in root.subLayerPaths:
        root.subLayerPaths.insert(0, ident)
    return path


def validate_selection(ctx, force_n=500.0, material=None):
    """The menu action: import the selection, a stress check on every box-shaped rigid body under
    `force_n` on its top face, the results painted back through the sublayer."""
    from omni.kit.window.popup_dialog import MessageDialog

    url, key = _settings()
    ix = Interop(url, api_key=key)
    stage = ctx.get_stage()
    paths = list(ctx.get_selection().get_selected_prim_paths())
    if not paths:
        MessageDialog(title="Eddy Validate", message="Select the prims to validate first.").show()
        return None
    text = _flatten_selection(stage, paths)
    imp = import_selection(ix, text)
    mat = material or {"e": 210e9, "nu": 0.3, "rho": 7850.0, "yield": 250e6}
    limits = []
    for b in imp["scene"]["bodies"]:
        if b.get("fixed") or "box" not in (b.get("shape") or {}):
            continue
        d = b["shape"]["box"]
        limits.append({"body": b["id"], "geometry": {"lx": d["lx"], "ly": d["ly"], "lz": d["lz"]}, "load_region": "z_max", "fixed_region": "z_min", "force": [0.0, 0.0, -force_n], "material": mat})
    results = []
    if limits:
        cal = ix.calibrate(load_limits=limits)
        for l in cal["load_limits"]:
            results.append({"body": l["body"], "result_key": l["result_key"]})
    out = sublayer_for(ix, imp, results=results, meters_per_unit=float(stage.GetMetadata("metersPerUnit") or 1.0))
    path = compose_sublayer(stage, out["text"])
    MessageDialog(title="Eddy Validate", message=f"{len(imp['scene']['bodies'])} bodies imported, {len(results)} stress checks keyed; sublayer {path} composed (export key {out['export_key'][:16]}…)").show()
    return out


def write_sublayer_for_stage(ctx):
    from omni.kit.window.popup_dialog import MessageDialog
    from pxr import Usd

    url, key = _settings()
    ix = Interop(url, api_key=key)
    stage = ctx.get_stage()
    text = stage.Flatten().ExportToString()
    imp = import_selection(ix, text)
    out = sublayer_for(ix, imp, meters_per_unit=float(stage.GetMetadata("metersPerUnit") or 1.0))
    path = compose_sublayer(stage, out["text"])
    MessageDialog(title="Eddy Validate", message=f"mass properties for {len(imp['scene']['bodies'])} bodies written to {path}").show()
    return out


def selftest(base_url="http://127.0.0.1:8080"):
    """Outside Kit: the same calls on a sample stage text (needs a running engine)."""
    ix = Interop(base_url)
    stage = """#usda 1.0
(
    metersPerUnit = 1
    upAxis = "Z"
)
def Xform "World" {
    def Xform "Bracket" (prepend apiSchemas = ["PhysicsRigidBodyAPI", "PhysicsMassAPI"]) {
        float physics:mass = 2.0
        double3 xformOp:translate = (0, 0, 0.5)
        uniform token[] xformOpOrder = ["xformOp:translate"]
        def Cube "geom" (prepend apiSchemas = ["PhysicsCollisionAPI"]) { double size = 0.1 }
    }
}
"""
    imp = import_selection(ix, stage)
    b = imp["scene"]["bodies"][0]
    d = b["shape"]["box"]
    cal = ix.calibrate(load_limits=[{"body": b["id"], "geometry": {"lx": d["lx"], "ly": d["ly"], "lz": d["lz"]}, "load_region": "z_max", "fixed_region": "z_min", "force": [0.0, 0.0, -500.0], "material": {"e": 210e9, "nu": 0.3, "rho": 7850.0, "yield": 250e6}}])
    out = sublayer_for(ix, imp, results=[{"body": b["id"], "result_key": cal["load_limits"][0]["result_key"]}])
    assert 'over "Bracket"' in out["text"] and "eddy:safety_factor" in out["text"], out["text"]
    print("extension self-test ok:", out["export_key"])
    return out


if __name__ == "__main__":
    selftest(os.environ.get("SS_URL", "http://127.0.0.1:8080"))
