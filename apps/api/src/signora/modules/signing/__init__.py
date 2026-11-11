"""Signing module: the signer's and countersigner's path from the link to the completed copy
(Phase 8 LLD).

Public interface — other modules import only from here.
"""

from signora.modules.signing.routes import router

__all__ = ["router"]
