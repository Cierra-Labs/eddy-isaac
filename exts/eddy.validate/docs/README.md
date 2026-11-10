# eddy.validate — the Isaac Sim extension (IX5)

Engineering truth beside PhysX. The extension is a client of the Eddy
engine's `/v1/interop.*` routes; nothing of the engine runs inside Kit.

Install: **Window ▸ Extensions**, search "Eddy Validate" in the community
registry (add the registry once: Settings ▸ Extension Registries ▸ `+`,
`kit/community`, `https://dw290v42wisod.cloudfront.net/exts/kit/community`),
or add a checkout's `exts` folder to the extension search paths. The
published extension carries the `eddy_solve` client it needs. Settings:
`/exts/eddy.validate/engine_url` (default `http://127.0.0.1:8080`) and
`/exts/eddy.validate/api_key`.

Menu **Eddy**:

- **Validate selection** — the selected prims are flattened to USDA text
  and imported through `POST /v1/interop.import` (the typed subset:
  rigid bodies with Cube / Sphere / Cylinder / Capsule / Cone / Mesh
  colliders, mass and material APIs, the joint prims; anything else is
  listed or refused naming the prim); every box-shaped rigid body gets a
  stress check under 500 N on its top face (`POST /v1/interop.calibrate`,
  `load_limits`); the engine writes the sublayer (`POST /v1/interop.export`,
  `over` prims with the kernel's `physics:mass` / `centerOfMass` /
  `diagonalInertia` / `principalAxes` and the `eddy:` result attributes —
  result key, peak stress, safety factor, certificate), and the extension
  composes it over the stage (`eddy_validate.usda` beside the root layer,
  strongest sublayer). Their file is never rewritten.
- **Write Eddy sublayer for the stage** — the mass properties for every
  rigid body on the stage, the same way.

OmniGraph nodes (category *Eddy engineering truth*), for Action Graphs:

- **Eddy Truth Solve** — a box body's peak stress, safety factor and force limit under a face
  load (`POST /v1/interop.calibrate`, `load_limits`).
- **Eddy Audit** — a peak contact force graded against the stress solve (`POST /v1/interop.audit`,
  `contact_yield`; the force is rounded up to the bucket, one solve per bucket).
- **Eddy Calibrate** — PhysX compliant-contact stiffness, damping, restitution and offset from
  Hertz or the P1 column (`POST /v1/interop.calibrate`, `contacts`).

Each takes `execIn`, fires `execOut` when the engine answered, and with `writeToPrim` paints
`eddy:<kind>:*` on `targetPrimPath` (the result key beside every number). The call is
synchronous: trigger from events, not every tick. `graph_setup.build_example_graph(prim)` builds
an impulse-driven graph running all three; `graph_check.py` runs it inside Isaac Sim.

Replicator writer **EddyLabelWriter** (registered when `omni.replicator.core` is enabled):

```python
w = rep.WriterRegistry.get("EddyLabelWriter")
w.initialize(output_dir="/tmp/frames", prims=[{"prim_path": "/World/Finger", "size": [0.06, 0.02, 0.02],
             "material": {"e": 210e9, "nu": 0.3, "rho": 7850.0, "yield": 250e6}}])
w.attach([render_product])
```

Each frame: `rgb_<n>.png` and `eddy_labels_<n>.json` — per prim the peak contact force (rounded up to
its bucket, PhysX's raw value beside it), the stress margin (safety factor − 1) and the temperature at
the part's power, every label with the result key of its solve and the report URL that opens it. The
writer reads `eddy:obs:contact_force` (N) and `eddy:obs:power` (W) on each prim, which the simulation
keeps current; pass `observe=` to read them elsewhere. `replicator_check.py` runs it inside Isaac Sim.

`python eddy/validate/client.py` runs the same calls outside Kit against a
running engine (the self-test). `kit_check.py` beside this folder runs them
*inside* Isaac Sim's Python (`/isaac-sim/python.sh kit_check.py --url <engine>
--stage <stage>`): the extension enabled through the manager, the stage's
rigid bodies selected, both menu actions, the `eddy:` attributes read back —
PASS on Isaac Sim 6.0.1 (2026-09-17).
