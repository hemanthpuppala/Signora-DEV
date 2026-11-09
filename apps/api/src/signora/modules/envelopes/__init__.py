"""Envelopes module: sending one approved version to its parties (Phase 7 LLD).

Public interface — other modules import only from here.
"""

from signora.modules.envelopes.routes import router

__all__ = ["router"]
