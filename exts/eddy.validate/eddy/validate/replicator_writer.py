"""The Replicator writer (HE5): every frame Replicator renders, the RGB image (optional) and a
label file with Eddy's numbers for the configured prims, each label carrying the result key of
the solve that produced it (`labels.FrameLabeler`).

    import omni.replicator.core as rep
    from eddy.validate import replicator_writer
    replicator_writer.register()                       # the extension does this when Replicator is on
    w = rep.WriterRegistry.get("EddyLabelWriter")
    w.initialize(output_dir="/tmp/eddy_frames", prims=[
        {"prim_path": "/World/Finger", "size": [0.06, 0.02, 0.02],
         "material": {"e": 210e9, "nu": 0.3, "rho": 7850.0, "yield": 250e6}}])
    w.attach([render_product])

Per frame the writer observes each prim (by default its `eddy:obs:contact_force` (N) and
`eddy:obs:power` (W) attributes, which the simulation or a sensor script keeps current; pass
`observe=callable(stage, prim_path) -> dict` to read them elsewhere) and writes
`eddy_labels_<frame>.json` beside `rgb_<frame>.png`. A label without a key is never written: a
refused solve is logged and the frame's labels say `"error"`.
"""
import json
import os

from .labels import FrameLabeler, PrimSpec

_CLASS = None
_REGISTERED = False


def read_prim_observations(stage, prim_path):
    prim = stage.GetPrimAtPath(prim_path)
    out = {}
    if not prim or not prim.IsValid():
        return out
    for attr, key in (("eddy:obs:contact_force", "contact_force"), ("eddy:obs:power", "power")):
        a = prim.GetAttribute(attr)
        if a and a.HasValue():
            out[key] = float(a.Get())
    return out


def _backend(output_dir):
    from omni.replicator.core import BackendDispatch

    try:
        return BackendDispatch(output_dir=output_dir)
    except TypeError:
        return BackendDispatch({"paths": {"out_dir": output_dir}})


def writer_class():
    """The writer class, defined when Replicator is importable (the extension may load first)."""
    global _CLASS
    if _CLASS is not None:
        return _CLASS
    from omni.replicator.core import AnnotatorRegistry, Writer

    class EddyLabelWriter(Writer):
        def __init__(self, output_dir, prims, engine_url="", api_key=None, rgb=True, observe=None, frame_padding=4):
            from .client import Interop, _settings

            url, key = _settings()
            self.version = "0.2.0"
            self._out = output_dir
            os.makedirs(output_dir, exist_ok=True)
            self._labeler = FrameLabeler(Interop(engine_url or url, api_key=api_key or key), [p if isinstance(p, PrimSpec) else PrimSpec(**p) for p in prims], engine_url=engine_url or url)
            self._observe = observe or read_prim_observations
            self._pad = frame_padding
            self._frame = 0
            self.annotators = [AnnotatorRegistry.get_annotator("rgb")] if rgb else []
            self._backend = _backend(output_dir) if rgb else None

        def write(self, data):
            import omni.usd

            n = f"{self._frame:0{self._pad}d}"
            if self._backend is not None:
                for k, v in data.items():
                    if k == "rgb" or k.endswith("-rgb") or k.endswith("_rgb"):
                        self._backend.write_image(f"rgb_{n}.png", v)
                        break
            stage = omni.usd.get_context().get_stage()
            obs = {p: self._observe(stage, p) for p in self._labeler.specs}
            try:
                doc = self._labeler.label(self._frame, obs)
            except Exception as e:  # noqa: BLE001
                doc = {"frame": self._frame, "labels": [], "error": f"{type(e).__name__}: {e}"}
            doc["observations"] = obs
            doc["engine_requests_so_far"] = self._labeler.requests
            with open(os.path.join(self._out, f"eddy_labels_{n}.json"), "w", encoding="utf-8") as f:
                json.dump(doc, f, indent=2)
            self._frame += 1

        def on_final_frame(self):
            pass

    _CLASS = EddyLabelWriter
    return _CLASS


def register():
    """Registers the writer with Replicator (once); returns why not when Replicator is absent."""
    global _REGISTERED
    if _REGISTERED:
        return "registered"
    try:
        from omni.replicator.core import WriterRegistry

        cls = writer_class()
    except Exception as e:  # noqa: BLE001
        return f"omni.replicator.core not importable ({str(e)[:80]})"
    try:
        WriterRegistry.register(cls)
        _REGISTERED = True
        return "registered"
    except Exception as e:  # noqa: BLE001
        return f"refused: {e}"
