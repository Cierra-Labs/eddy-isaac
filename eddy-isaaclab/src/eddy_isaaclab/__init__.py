"""eddy_isaaclab — Eddy's engineering truth beside Isaac Lab: the episode-end
contact-force audit (`ForceAudit`), packaged from the IX5 hook.

    pip install eddy-isaaclab
    from eddy_isaaclab import ForceAudit, contact_yield_check, steel

Importing this package never imports Isaac Lab, Isaac Sim, torch or numpy;
the training loop hands it tensors and it reads them where they are.
"""
from .audit import ForceAudit, ForeignRollout, Interop, contact_yield_check, selftest, steel, summarise

__version__ = "0.1.0"

__all__ = ["ForceAudit", "ForeignRollout", "Interop", "contact_yield_check", "selftest", "steel", "summarise", "__version__"]
