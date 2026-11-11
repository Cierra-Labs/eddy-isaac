"""The Isaac Lab hook exercised inside Isaac Lab (IX5): a vectorised scene of N environments,
each a steel block dropped onto the ground with a `ContactSensor` on it, stepped for a fixed
episode; every step the hook keeps the running peak of `sensor.data.net_forces_w`, and at the
episode's end one `POST /v1/interop.audit` batch grades every environment's peak through the
yield check — identical peaks share one truth solve. Run with Isaac's Python beside a reachable
engine:

    /isaac-sim/python.sh isaaclab_check.py --url http://127.0.0.1:8090 --num_envs 8 --steps 120

`--hook-source installed` (HE2) imports the pip-installed `eddy_isaaclab` (and the `eddy_solve`
it depends on) and refuses to fall back to this checkout; the report names the files imported.
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

from isaaclab.app import AppLauncher  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--url", default=os.environ.get("SS_URL", "http://127.0.0.1:8080"))
ap.add_argument("--api-key-file", default=os.environ.get("EDDY_API_KEY_FILE", ""), help="a file holding the Eddy API key, sent as x-api-key (default: EDDY_API_KEY or SS_API_KEY from the environment); never put the key itself on the command line")
ap.add_argument("--num_envs", type=int, default=8)
ap.add_argument("--steps", type=int, default=120)
ap.add_argument("--out", default="")
ap.add_argument("--hook-source", choices=("repo", "installed"), default="repo", help="repo: this checkout's hook and SDK; installed: the pip-installed eddy-isaaclab / eddy-solve only")
AppLauncher.add_app_launcher_args(ap)
args = ap.parse_args()


def _read_api_key():
    """The Eddy API key for a hosted engine (HE13.2): a file first, then the environment; None for a local engine."""
    if args.api_key_file:
        with open(args.api_key_file, encoding="utf-8") as f:
            return f.read().strip() or None
    return os.environ.get("EDDY_API_KEY") or os.environ.get("SS_API_KEY") or None


API_KEY = _read_api_key()


if args.hook_source == "repo":
    sys.path.insert(0, HERE)
args.headless = True
launcher = AppLauncher(args)
app = launcher.app

import torch  # noqa: E402

import isaaclab.sim as sim_utils  # noqa: E402
from isaaclab.assets import AssetBaseCfg, RigidObject, RigidObjectCfg  # noqa: E402
from isaaclab.scene import InteractiveScene, InteractiveSceneCfg  # noqa: E402
from isaaclab.sensors import ContactSensor, ContactSensorCfg  # noqa: E402
from isaaclab.utils import configclass  # noqa: E402

if args.hook_source == "repo":
    from eddy_isaaclab_hook import ForceAudit, contact_yield_check, steel  # noqa: E402
else:
    from eddy_isaaclab import ForceAudit, contact_yield_check, steel  # noqa: E402


def origins():
    import eddy_solve

    mods = {"eddy_solve": eddy_solve.__file__}
    try:
        import eddy_isaaclab

        mods["eddy_isaaclab"] = eddy_isaaclab.__file__
        mods["eddy_isaaclab_version"] = eddy_isaaclab.__version__
    except ImportError:
        pass
    return mods

LX, LY, LZ = 0.1, 0.1, 0.05  # the block (m)
DROP = 0.5  # m


@configclass
class BlockSceneCfg(InteractiveSceneCfg):
    ground = AssetBaseCfg(prim_path="/World/ground", spawn=sim_utils.GroundPlaneCfg())
    light = AssetBaseCfg(prim_path="/World/light", spawn=sim_utils.DomeLightCfg(intensity=2000.0))
    block = RigidObjectCfg(
        prim_path="{ENV_REGEX_NS}/Block",
        spawn=sim_utils.CuboidCfg(
            size=(LX, LY, LZ),
            rigid_props=sim_utils.RigidBodyPropertiesCfg(),
            mass_props=sim_utils.MassPropertiesCfg(density=7850.0),
            collision_props=sim_utils.CollisionPropertiesCfg(),
            activate_contact_sensors=True,
            visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=(0.3, 0.3, 0.9)),
        ),
        init_state=RigidObjectCfg.InitialStateCfg(pos=(0.0, 0.0, DROP)),
    )
    contact = ContactSensorCfg(prim_path="{ENV_REGEX_NS}/Block", update_period=0.0, history_length=1)


def main():
    report = {"engine_url": args.url, "api_key_sent": bool(API_KEY), "num_envs": args.num_envs, "steps": args.steps, "hook_source": args.hook_source, "imported": origins()}
    if args.hook_source == "installed":
        # this folder (the hook's src/ sits under it) and the superstring checkout's SDK
        checkout = [HERE, os.path.abspath(os.path.join(HERE, "..", "..", "sdks"))]
        leaked = [k for k, v in report["imported"].items() if k != "eddy_isaaclab_version" and any(os.path.abspath(v).startswith(c + os.sep) for c in checkout)]
        if leaked:
            raise SystemExit(f"--hook-source installed imported {leaked} from the checkout {checkout}")
    sim_cfg = sim_utils.SimulationCfg(dt=1.0 / 240.0, device=args.device)
    sim = sim_utils.SimulationContext(sim_cfg)
    scene = InteractiveScene(BlockSceneCfg(num_envs=args.num_envs, env_spacing=1.0))
    sim.reset()
    block: RigidObject = scene["block"]
    sensor: ContactSensor = scene["contact"]
    # a different drop height per environment: a different impact peak per environment, so
    # the batch carries several distinct buckets and the cache answers the repeats
    root = block.data.default_root_state.clone()
    root[:, :3] += scene.env_origins
    root[:, 2] = DROP * (1.0 + 0.5 * (torch.arange(args.num_envs, device=root.device) % 4).float())
    block.write_root_pose_to_sim(root[:, :7])
    block.write_root_velocity_to_sim(root[:, 7:])
    scene.write_data_to_sim()
    audit = ForceAudit(["block"], [contact_yield_check("block", 50.0, LX, LY, LZ, "z_max", "z_min", steel())], base_url=args.url, api_key=API_KEY)
    t0 = time.perf_counter()
    for k in range(args.steps):
        scene.write_data_to_sim()
        sim.step()
        scene.update(sim_cfg.dt)
        audit.observe(sensor.data.net_forces_w)  # [E, 1, 3]
        audit.observe_poses(block.data.root_pos_w.unsqueeze(1), block.data.root_quat_w.unsqueeze(1), (k + 1) * sim_cfg.dt)
    stepped = time.perf_counter() - t0
    peaks = audit.peak[:, 0].tolist()
    t0 = time.perf_counter()
    out = audit.audit()
    audited = time.perf_counter() - t0
    truths = [t for ad in out["audits"] for t in ad["truth"]]
    keys = {t["result_key"] for t in truths}
    rows = [[r for r in ad["report"]["rows"] if r["check"] == "contact_yield"] for ad in out["audits"]]
    report.update({
        "peaks_n": [round(p, 2) for p in peaks],
        "stepped_s": stepped,
        "audit_s": audited,
        "audits": len(out["audits"]),
        "truth_solves": len(truths),
        "distinct_keys": len(keys),
        "cached": sum(1 for t in truths if t["cached"]),
        "safety_factors": [[round(r["truth"], 1) for r in rs] for rs in rows],
        "pass": all(ad["report"]["pass"] for ad in out["audits"]),
        "sensor_device": str(sensor.data.net_forces_w.device),
    })
    print(json.dumps(report, indent=2), flush=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
    print("ISAACLAB-CHECK", "PASS" if report["pass"] and report["audits"] == args.num_envs else "FAIL", flush=True)


try:
    main()
finally:
    app.close()
