"""The example Action Graph (HE4), inside Kit: an impulse event runs Eddy Truth Solve, then Eddy
Audit, then Eddy Calibrate, each writing its result onto a prim as `eddy:<kind>:*` attributes.

    from eddy.validate import graph_setup
    graph, nodes, how = graph_setup.build_example_graph("/World/Finger", peak_force=130.0)
    graph_setup.trigger(graph, nodes)          # fires the impulse and evaluates the graph
    # /World/Finger now carries eddy:truth:*, eddy:audit:*, eddy:calibrate:*

The node types are the extension's OmniGraph Python nodes (`nodes/Ogn*.ogn`, registered by
OmniGraph when the extension loads). Should a Kit release not register them, `how` says so and
the graph is built from `omni.graph.scriptnode.ScriptNode`s running the same `graph_core`
functions, so the path is still the real one (an Action Graph evaluating, the route called, the
prim written).
"""
EXT = "eddy.validate"
NODE_TYPES = {"truth": f"{EXT}.EddyTruthSolve", "audit": f"{EXT}.EddyAudit", "calibrate": f"{EXT}.EddyCalibrate"}

SCRIPT = '''
def setup(db):
    pass


def compute(db):
    import types
    from eddy.validate import graph_core, node_runtime
    kind = "{kind}"
    inp = types.SimpleNamespace(**{{k: getattr(db.inputs, k) for k in {names!r}}})
    holder = types.SimpleNamespace(inputs=inp, outputs=types.SimpleNamespace())
    ok, res = graph_core.compute_node(kind, holder, node_runtime.interop(str(inp.engineUrl)), node_runtime.stage())
    if not ok:
        db.log_error(str(res))
        return False
    for k, v in vars(holder.outputs).items():
        setattr(db.outputs, k, v)
    import omni.graph.core as og
    db.outputs.execOut = og.ExecutionAttributeState.ENABLED
    return True
'''

# the inputs each kind reads, with their OmniGraph types (the ScriptNode fallback creates them)
INPUTS = {
    "truth": {"engineUrl": "string", "body": "token", "force": "double", "size": "double[3]", "loadRegion": "token", "fixedRegion": "token", "youngsModulus": "double", "poissonRatio": "double", "density": "double", "yieldStrength": "double", "targetPrimPath": "string", "writeToPrim": "bool"},
    "audit": {"engineUrl": "string", "body": "token", "peakForce": "double", "bucket": "double", "size": "double[3]", "loadRegion": "token", "fixedRegion": "token", "youngsModulus": "double", "poissonRatio": "double", "density": "double", "yieldStrength": "double", "minSafetyFactor": "double", "targetPrimPath": "string", "writeToPrim": "bool"},
    "calibrate": {"engineUrl": "string", "body": "token", "geometryKind": "token", "radius": "double", "padSize": "double[3]", "force": "double", "effectiveMass": "double", "youngsModulus": "double", "poissonRatio": "double", "density": "double", "yieldStrength": "double", "targetPrimPath": "string", "writeToPrim": "bool"},
}
OUT_TYPES = {"resultKey": "string", "safetyFactor": "double", "passed": "bool", "bucketedForce": "double", "reportJson": "string", "peakStress": "double", "forceLimit": "double", "stiffness": "double", "damping": "double", "restitution": "double", "contactOffset": "double", "calibrationKey": "string"}


def registered():
    """The extension's node types OmniGraph knows."""
    import omni.graph.core as og

    try:
        names = og.get_registered_nodes()
    except Exception:  # noqa: BLE001
        names = []
    return sorted(n for n in names if n.startswith(EXT + "."))


def ensure_registered():
    """Asks OmniGraph to register the Python nodes when it has not (API names vary by release)."""
    import os

    import omni.graph.core as og

    if registered():
        return "registered when the extension loaded"
    here = os.path.dirname(os.path.abspath(__file__))
    for fn in ("register_ogn_nodes",):
        if hasattr(og, fn):
            try:
                getattr(og, fn)(os.path.join(here, "__init__.py"), EXT)
                if registered():
                    return f"registered through og.{fn}"
            except Exception as e:  # noqa: BLE001
                return f"og.{fn} refused: {str(e)[:120]}"
    return "not registered"


def _values(kind, prim, peak_force, url, size):
    base = {"engineUrl": url, "targetPrimPath": prim, "writeToPrim": True, "body": prim.rsplit("/", 1)[-1], "size": list(size)}
    if kind == "truth":
        base.update(force=500.0)
    elif kind == "audit":
        base.update(peakForce=float(peak_force), bucket=25.0)
    else:
        base.update(geometryKind="sphere", radius=0.01, force=20.0, effectiveMass=0.2)
        base.pop("size")
    return base


def build_example_graph(prim_path, peak_force=130.0, engine_url="", size=(0.06, 0.02, 0.02), graph_path="/World/EddyAuditGraph", kinds=("truth", "audit", "calibrate"), force_script=False):
    """Creates the Action Graph on the open stage. Returns (graph, {name: node}, how)."""
    import omni.graph.core as og

    keys = og.Controller.Keys
    how = "ogn" if (not force_script and all(NODE_TYPES[k] in registered() for k in kinds)) else "scriptnode"
    create = [("Impulse", "omni.graph.action.OnImpulseEvent")]
    for k in kinds:
        create.append((k.capitalize(), NODE_TYPES[k] if how == "ogn" else "omni.graph.scriptnode.ScriptNode"))
    connect = []
    prev = "Impulse"
    for k in kinds:
        connect.append((f"{prev}.outputs:execOut", f"{k.capitalize()}.inputs:execIn"))
        prev = k.capitalize()
    graph, nodes, _, _ = og.Controller.edit({"graph_path": graph_path, "evaluator_name": "execution"}, {keys.CREATE_NODES: create})
    by = {n.get_prim_path().rsplit("/", 1)[-1]: n for n in nodes}
    if how == "scriptnode":
        for k in kinds:
            node = by[k.capitalize()]
            for name, t in INPUTS[k].items():
                og.Controller.create_attribute(node, f"inputs:{name}", t, og.AttributePortType.ATTRIBUTE_PORT_TYPE_INPUT)
            for name in __import__("eddy.validate.graph_core", fromlist=["OUTPUTS"]).OUTPUTS[k]:
                og.Controller.create_attribute(node, f"outputs:{name}", OUT_TYPES[name], og.AttributePortType.ATTRIBUTE_PORT_TYPE_OUTPUT)
            og.Controller.set(og.Controller.attribute("inputs:script", node), SCRIPT.format(kind=k, names=tuple(INPUTS[k])))
    sets = [(og.Controller.attribute("inputs:onlyPlayback", by["Impulse"]), False)]
    for k in kinds:
        for name, v in _values(k, prim_path, peak_force, engine_url, size).items():
            sets.append((og.Controller.attribute(f"inputs:{name}", by[k.capitalize()]), v))
    og.Controller.edit(graph, {keys.CONNECT: connect, keys.SET_VALUES: sets})
    return graph, by, how


def trigger(graph, nodes):
    """Fires the impulse and evaluates the graph once (synchronously)."""
    import omni.graph.core as og

    og.Controller.set(og.Controller.attribute("state:enableImpulse", nodes["Impulse"]), True)
    og.Controller.evaluate_sync(graph)
