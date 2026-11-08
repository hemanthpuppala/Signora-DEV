"""Documents module: agreements, their versions, uploads and processing (Phase 4 LLD).

Public interface — other modules import only from here.
"""

from signora.modules.documents.routes import router

__all__ = ["router"]
