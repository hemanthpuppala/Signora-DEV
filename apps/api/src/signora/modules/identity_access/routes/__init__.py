"""HTTP routes of the identity module, combined into one router."""

from fastapi import APIRouter

from signora.modules.identity_access.routes import auth, invites, passwords, signup

router = APIRouter()
router.include_router(auth.router)
router.include_router(signup.router)
router.include_router(passwords.router)
router.include_router(invites.router)

__all__ = ["router"]
