# eddy-isaaclab

Engineering truth beside Isaac Lab. During an episode the hook keeps the peak
contact force per body per environment; at reset it posts every environment's
peaks to an Eddy engine as **one** `POST /v1/interop.audit` batch. The engine
rounds each peak up to the bucket you declare and runs one finite-element
stress solve per distinct (body, bucket), so 4096 environments with the same
gripper cost a handful of solves, and every answer carries the result key of
the solve that produced it.

```bash
pip install eddy-isaaclab
```

```python
from eddy_isaaclab import ForceAudit, contact_yield_check, steel

audit = ForceAudit(
    bodies=["finger"],
    checks=[contact_yield_check("finger", 25.0, 0.06, 0.02, 0.02, "x_max", "x_min", steel())],
    base_url="http://127.0.0.1:8080",   # your Eddy engine
)

# every step (a ContactSensor's net forces, [num_envs, num_bodies, 3])
audit.observe(sensor.data.net_forces_w)

# at reset: one batch for the environments that ended
report = audit.audit(env_ids)
```

- `audit(env_ids, dedupe=True)` rounds the peaks up to the bucket on the client
  and sends one item per distinct bucket (`report["env_to_audit"]` maps each
  environment to its item). The grades are the same; the request is smaller.
- `observe_poses(root_pos_w, root_quat_w, t)` records trajectories too, so the
  free-fall, energy and rest checks run in the same batch.
- Nothing calls the engine inside the step, and importing the package never
  imports Isaac Lab, torch or numpy.

Self-test without Isaac (needs numpy and a reachable engine):

```bash
pip install "eddy-isaaclab[selftest]"
python -m eddy_isaaclab --url http://127.0.0.1:8080
```

The in-Isaac check (`isaaclab_check.py`) lives in the source repository and
runs with Isaac's own Python: `isaaclab.sh -p isaaclab_check.py --url <engine>
--num_envs 8 --hook-source installed`.

Licence: Apache-2.0.
