# eddy-isaac

Eddy's bridges into NVIDIA Isaac Sim and Isaac Lab. Eddy is an engineering engine: finite-element
stress, contact, thermal and flow solves behind one typed API, every answer content-addressed by a
result key. These packages put those answers beside PhysX; nothing of Eddy runs inside the step.

| Piece | Install | What it does |
|---|---|---|
| `eddy.validate` (Kit extension 0.2.0) | Isaac Sim: Window > Extensions > the community registry, search "Eddy Validate" (or add `exts/` as an extension search path) | Menu Eddy > Validate selection: a stress check per rigid body painted onto the stage through a sublayer. OmniGraph nodes for truth solve, audit and calibrate. A Replicator writer that labels frames with Eddy's numbers, each with its result key |
| `eddy-isaaclab` (0.1.0) | `pip install eddy-isaaclab` into Isaac Lab's Python | The episode-end audit: the peak contact force per body per environment, graded in one batch at reset |
| `eddy-solve` (0.1.0) | `pip install eddy-solve` | The Python client both of the above use |

Every piece needs a reachable Eddy engine (its URL in the extension settings `/exts/eddy.validate/engine_url`,
or `base_url=` in Python).

Checks run inside the real apps: `exts/eddy.validate/kit_check.py` (Isaac Sim's `python.sh`) and
`isaaclab_check.py` (Isaac Lab). Both take `--url <engine>`.

Licence: Apache-2.0. This repository is generated from Eddy's source by `integrations/publish/build_dists.py`;
changes are made there.
