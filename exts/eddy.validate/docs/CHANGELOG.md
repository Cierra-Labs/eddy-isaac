# Changelog

## [0.2.0] - 2026-11-10
### Added
- Packaged for the Kit community registry (HE2): icon, preview, changelog, repository, licence.
- The published extension carries the `eddy_solve` client it was tested with (`pip_prebundle/`), so it
  needs no pip install inside Kit; an `eddy-solve` installed into Kit's Python, then a repository
  checkout, are the fallbacks.
- OmniGraph nodes (HE4): **Eddy Truth Solve**, **Eddy Audit**, **Eddy Calibrate** (`eddy/validate/nodes`),
  each writing its result onto a prim as `eddy:<kind>:*` attributes beside the result key, and
  `graph_setup.build_example_graph`: an impulse event running all three on one prim.
- Replicator writer `EddyLabelWriter` (HE5): per frame, the RGB image and `eddy_labels_<frame>.json` with
  peak contact force, stress margin and temperature per configured prim, each label carrying the result
  key of the solve that produced it; at most two engine requests per frame, repeated buckets cached.

## [0.1.0] - 2026-09-17
### Added
- Menu **Eddy ▸ Validate selection** and **Write Eddy sublayer for the stage** (IX5), verified inside
  Isaac Sim 6.0.1.
