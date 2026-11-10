"""What the OmniGraph nodes compute (HE4), with no Kit in sight: each function takes an
`eddy_solve.interop.Interop` and plain numbers, calls one engine route, and returns a flat dict
the node copies onto its outputs. `prim_attrs` / `write_prim_attrs` turn a result into the
`eddy:` attributes a prim carries (pxr only). Unit-tested outside Kit
(`tests/test_graph_core.py`).

Node            Route                               Outputs
EddyTruthSolve  POST /v1/interop.calibrate          resultKey, peakStress, safetyFactor, forceLimit
                (load_limits: a P1 stress solve)
EddyAudit       POST /v1/interop.audit              resultKey (the truth solve's), safetyFactor,
                (contact_yield on a peak force)     passed, bucketedForce, rolloutKey, reportJson
EddyCalibrate   POST /v1/interop.calibrate          stiffness, damping, restitution, contactOffset,
                (contacts: Hertz / the P1 column)   calibrationKey, resultKey (the solve's, when
                                                    the geometry needs one)
"""
import json


def material(e=210e9, nu=0.3, rho=7850.0, yield_strength=250e6):
    return {"e": float(e), "nu": float(nu), "rho": float(rho), "yield": float(yield_strength)}


def box(lx, ly, lz):
    return {"lx": float(lx), "ly": float(ly), "lz": float(lz)}


def truth_solve(ix, body, geometry, force_n, mat, load_region="z_max", fixed_region="z_min"):
    """A stress check of a box body under `force_n` on its load face (`-force_n` along the face's
    outward normal), fixed on the opposite face: the engine's P1 solve, keyed."""
    axis = {"x": 0, "y": 1, "z": 2}[load_region[0]]
    sign = 1.0 if load_region.endswith("max") else -1.0
    f = [0.0, 0.0, 0.0]
    f[axis] = -sign * float(force_n)
    cal = ix.calibrate(load_limits=[{"body": body, "geometry": geometry, "load_region": load_region, "fixed_region": fixed_region, "force": f, "material": mat}])
    l = cal["load_limits"][0]
    return {"resultKey": l["result_key"], "peakStress": float(l["peak_stress"]), "safetyFactor": float(l["safety_factor_at_probe"]), "forceLimit": float(l["force_limit"]), "calibrationKey": cal.get("calibration_key", "")}


def audit_peak(ix, body, peak_force_n, geometry, mat, bucket_n=25.0, load_region="z_max", fixed_region="z_min", min_safety_factor=1.0, engine="physx"):
    """A peak contact force (from PhysX, a sensor, a log) graded by the audit's yield check: the
    force is rounded up to the bucket and solved once per bucket; the row's truth is the safety
    factor, its key the solve's."""
    rollout = {"engine": engine, "version": "omnigraph", "device": "", "bodies": [body], "frames": [
        {"t": 0.0, "pos": [[0.0, 0.0, 0.0]], "contact_force": [0.0]},
        {"t": 1.0, "pos": [[0.0, 0.0, 0.0]], "contact_force": [float(peak_force_n)]},
    ]}
    check = {"kind": "contact_yield", "body": body, "bucket": float(bucket_n), "geometry": geometry, "load_region": load_region, "fixed_region": fixed_region, "material": mat, "min_safety_factor": float(min_safety_factor)}
    out = ix.audit_batch([{"rollout": rollout, "checks": [check]}])
    ad = out["audits"][0]
    row = next(r for r in ad["report"]["rows"] if r.get("check") == "contact_yield")
    return {
        "resultKey": row.get("truth_key") or (ad["truth"][0]["result_key"] if ad.get("truth") else ""),
        "safetyFactor": float(row["truth"]),
        "passed": bool(row["pass"]),
        "bucketedForce": float(row["foreign"]),
        "rolloutKey": ad.get("rollout_key", ""),
        "reportJson": json.dumps(ad["report"], sort_keys=True),
    }


def calibrate_contact(ix, body, geometry, force_n, mat, effective_mass, damping_ratio=None, friction=None):
    """PhysX compliant-contact parameters from the truth: Hertz for a sphere / cylinder (closed
    form, no solve), the P1 column for a flat pad (a solve, keyed)."""
    c = {"body": body, "geometry": geometry, "force": float(force_n), "material": mat, "effective_mass": float(effective_mass)}
    if damping_ratio is not None:
        c["damping_ratio"] = float(damping_ratio)
    if friction is not None:
        c["friction"] = float(friction)
    cal = ix.calibrate(contacts=[c])
    k = cal["contacts"][0]
    px = k.get("physx") or {}
    keys = [t["result_key"] for t in cal.get("truth", []) if str(t.get("what", "")).endswith(body)]
    return {
        "stiffness": float(px.get("compliant_contact_stiffness", k.get("stiffness", 0.0))),
        "damping": float(px.get("compliant_contact_damping", k.get("damping", 0.0))),
        "restitution": float(k.get("restitution", 0.0)),
        "contactOffset": float(px.get("contact_offset", 0.0)),
        "calibrationKey": cal.get("calibration_key", ""),
        "resultKey": keys[0] if keys else "",
        "referee": k.get("referee", ""),
    }


# ---- the nodes' shared compute (db-shaped in, db-shaped out)

OUTPUTS = {
    "audit": ("resultKey", "safetyFactor", "passed", "bucketedForce", "reportJson"),
    "truth": ("resultKey", "peakStress", "safetyFactor", "forceLimit"),
    "calibrate": ("stiffness", "damping", "restitution", "contactOffset", "calibrationKey", "resultKey"),
}


def run_node(kind, inp, ix):
    """The route call for one node kind from its inputs (any object with the .ogn's input names)."""
    mat = material(inp.youngsModulus, inp.poissonRatio, inp.density, inp.yieldStrength)
    if kind == "audit":
        return audit_peak(ix, str(inp.body), inp.peakForce, box(*inp.size), mat, inp.bucket, str(inp.loadRegion), str(inp.fixedRegion), inp.minSafetyFactor)
    if kind == "truth":
        return truth_solve(ix, str(inp.body), box(*inp.size), inp.force, mat, str(inp.loadRegion), str(inp.fixedRegion))
    if kind == "calibrate":
        g = str(inp.geometryKind)
        geom = {"kind": "sphere", "r": float(inp.radius)} if g == "sphere" else {"kind": "flat", "lx": float(inp.padSize[0]), "ly": float(inp.padSize[1]), "h": float(inp.padSize[2])}
        return calibrate_contact(ix, str(inp.body), geom, inp.force, mat, inp.effectiveMass)
    raise ValueError(kind)


def compute_node(kind, db, ix, stage=None, enabled=None):
    """One node's compute: the route, the outputs, the prim attributes; `enabled` is
    og.ExecutionAttributeState.ENABLED inside Kit. Returns (ok, result or error)."""
    try:
        res = run_node(kind, db.inputs, ix)
    except Exception as e:  # noqa: BLE001 — a refused route is the node's error, not Kit's crash
        return False, f"{type(e).__name__}: {e}"
    for k in OUTPUTS[kind]:
        setattr(db.outputs, k, res[k])
    if db.inputs.writeToPrim and str(db.inputs.targetPrimPath) and stage is not None:
        res["written"] = write_prim_attrs(stage, str(db.inputs.targetPrimPath), prim_attrs(kind, res))
    if enabled is not None:
        db.outputs.execOut = enabled
    return True, res


# ---- results onto prims

_TYPES = {bool: "Bool", float: "Double", int: "Int", str: "String"}


def prim_attrs(kind, result):
    """The `eddy:<kind>:*` attributes a result paints on a prim: (name, value) pairs, every one
    beside the result key that reproduces it."""
    pick = {
        "truth": ("resultKey", "peakStress", "safetyFactor", "forceLimit"),
        "audit": ("resultKey", "safetyFactor", "passed", "bucketedForce", "rolloutKey"),
        "calibrate": ("calibrationKey", "resultKey", "stiffness", "damping", "restitution", "contactOffset"),
    }[kind]
    snake = {"resultKey": "result_key", "peakStress": "peak_stress", "safetyFactor": "safety_factor", "forceLimit": "force_limit", "bucketedForce": "bucketed_force", "rolloutKey": "rollout_key", "calibrationKey": "calibration_key", "contactOffset": "contact_offset"}
    return [(f"eddy:{kind}:{snake.get(k, k)}", result[k]) for k in pick if k in result and result[k] != ""]


def write_prim_attrs(stage, prim_path, attrs):
    """Creates (custom) and sets each attribute on the prim; returns the names written. The prim
    must exist: an Action Graph writes onto the stage it runs on, it never invents prims."""
    from pxr import Sdf

    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        raise ValueError(f"no prim at {prim_path}")
    names = []
    for name, value in attrs:
        tname = getattr(Sdf.ValueTypeNames, _TYPES[type(value)])
        a = prim.GetAttribute(name)
        if not a:
            a = prim.CreateAttribute(name, tname, custom=True)
        a.Set(value)
        names.append(name)
    return names
