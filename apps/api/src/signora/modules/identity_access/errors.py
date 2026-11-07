"""Errors of the identity module (Phase 2 LLD "Interfaces and error codes")."""

from __future__ import annotations

from signora.kernel.errors import Conflict, DomainError, PermissionDenied


class InvalidCredentials(DomainError):
    """Unknown email or wrong password: deliberately the same error."""

    code = "invalid-credentials"
    status = 401
    title = "Email or password is incorrect"


class AccessRemoved(PermissionDenied):
    code = "access-removed"
    title = "Your access to this workspace was removed"


class CsrfFailed(PermissionDenied):
    code = "csrf-failed"
    title = "This request is missing its security token; reload the page and try again"


class LinkExpired(DomainError):
    """Unknown, used and expired links look the same."""

    code = "link-expired"
    status = 410
    title = "This link has expired or was already used"


class AccountExists(Conflict):
    code = "account-exists"
    title = "An account already exists for this email; log in instead"


class AlreadyMember(Conflict):
    code = "already-member"
    title = "This person is already a member of the workspace"


class EmailInOtherWorkspace(Conflict):
    code = "email-in-other-workspace"
    title = "This email already belongs to another workspace on Signora"


class CreatorProtected(Conflict):
    code = "creator-protected"
    title = "The workspace creator cannot be changed or removed"


class CannotRemoveSelf(Conflict):
    code = "cannot-remove-self"
    title = "You cannot remove yourself; ask another member who manages people"
