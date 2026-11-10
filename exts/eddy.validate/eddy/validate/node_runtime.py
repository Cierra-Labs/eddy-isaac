"""The Kit side of the OmniGraph nodes (HE4): the engine client from the node's `engineUrl` or the
extension setting, the stage the graph runs on, and the execution state. The work is in
`graph_core.compute_node` (tested outside Kit). The route call is synchronous: an Action Graph
waits for the answer (a cached audit answers in milliseconds, a fresh solve in about a second),
so trigger these nodes from events (a reset, a key, an impulse), never from every tick."""


def interop(engine_url=""):
    from .client import Interop, _settings

    url, key = _settings()
    return Interop(engine_url or url, api_key=key)


def stage():
    import omni.usd

    return omni.usd.get_context().get_stage()


def compute(kind, db):
    import omni.graph.core as og

    from .graph_core import compute_node

    ok, res = compute_node(kind, db, interop(str(db.inputs.engineUrl)), stage(), og.ExecutionAttributeState.ENABLED)
    if not ok:
        db.log_error(f"Eddy {kind}: {res}")
    return ok
