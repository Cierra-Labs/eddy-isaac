"""The Isaac Lab hook as a single file (IX5) — since HE2 a shim over the
installable package `eddy_isaaclab` (`integrations/isaac/eddy-isaaclab`).

    pip install eddy-isaaclab           # the published package
    from eddy_isaaclab import ForceAudit, contact_yield_check, steel

From a repository checkout this file still works as before: it puts the
package's `src/` and the Python SDK (`sdks/eddy-python`) on `sys.path` when
they are not installed, then re-exports the package.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(HERE, "eddy-isaaclab", "src"), os.path.join(HERE, "..", "..", "sdks", "eddy-python")):
    _p = os.path.abspath(_p)
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.append(_p)  # after site-packages: an installed package wins

from eddy_isaaclab import ForceAudit, ForeignRollout, Interop, contact_yield_check, selftest, steel, summarise  # noqa: E402,F401

if __name__ == "__main__":
    selftest(os.environ.get("SS_URL", "http://127.0.0.1:8080"))
