# Changelog

## [Unreleased]
### Added
- The box checks (`kit_check.py`, `graph_check.py`, `replicator_check.py`, and `isaaclab_check.py` at the
  repository root) can run against a hosted Eddy engine: they send the Eddy API key as `x-api-key`, read from
  `--api-key-file` or the `EDDY_API_KEY` / `SS_API_KEY` environment variables, never from the command line.
  Reports record only whether a key was sent. A local engine still needs no key.

## [0.2.1] - 2026-11-11
### Fixed
- The example Action Graph (`graph_setup.build_example_graph`) connects its nodes by attribute objects.
  OmniGraph 1.142 (Isaac Sim 6.0) refuses node-relative path strings such as `Impulse.outputs:execOut`
  in a connect edit, so 0.2.0 could not build the graph there. Verified inside Isaac Sim 6.0.1 with the
  extension's own OmniGraph nodes: truth solve, audit and calibrate all write `eddy:*` onto the prim.

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
