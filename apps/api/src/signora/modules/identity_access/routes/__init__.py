"""HTTP routes of the identity module, combined into one router."""

from fastapi import APIRouter

from signora.modules.identity_access.routes import auth

router = APIRouter()
router.include_router(auth.router)

__all__ = ["router"]
