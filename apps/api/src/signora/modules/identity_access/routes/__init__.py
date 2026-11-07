"""HTTP routes of the identity module, combined into one router."""

from fastapi import APIRouter

from signora.modules.identity_access.routes import auth, signup

router = APIRouter()
router.include_router(auth.router)
router.include_router(signup.router)

__all__ = ["router"]
