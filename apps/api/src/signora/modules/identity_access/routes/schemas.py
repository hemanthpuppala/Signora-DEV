"""Request and response bodies of the identity API (they become the frontend contract types)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from signora.modules.identity_access.access import Actor

# Long enough for any passphrase; short enough that nobody makes the server hash a megabyte.
PasswordInput = Annotated[str, StringConstraints(min_length=1, max_length=1024)]
NameInput = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
EmailInput = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=254)]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoleRef(BaseModel):
    id: uuid.UUID
    name: str


class SignupRequest(_Body):
    email: EmailInput


class TokenRequest(_Body):
    token: Annotated[str, StringConstraints(min_length=16, max_length=128)]


class SignupCompleteRequest(TokenRequest):
    workspace_name: NameInput
    name: NameInput
    password: PasswordInput


class ResetRequest(TokenRequest):
    password: PasswordInput


class ChangePasswordRequest(_Body):
    current_password: PasswordInput
    new_password: PasswordInput


class AcceptedResponse(BaseModel):
    status: Literal["check_email", "changed"] = "check_email"


class EmailResponse(BaseModel):
    email: str


class InviteRequest(_Body):
    email: EmailInput
    role_id: uuid.UUID


class InviteView(BaseModel):
    id: uuid.UUID
    email: str
    role: RoleRef
    invited_by_name: str
    created_at: datetime
    expires_at: datetime
    expired: bool


class InviteDetailsView(BaseModel):
    email: str
    workspace_name: str
    role_name: str
    inviter_name: str


class AcceptInviteRequest(TokenRequest):
    name: NameInput
    password: PasswordInput


class LoginRequest(_Body):
    email: EmailInput
    password: PasswordInput


class UserView(BaseModel):
    id: uuid.UUID
    email: str
    name: str


class WorkspaceView(BaseModel):
    id: uuid.UUID
    name: str


class RoleView(BaseModel):
    id: uuid.UUID
    key: str
    name: str


class MeResponse(BaseModel):
    user: UserView
    workspace: WorkspaceView
    role: RoleView
    permissions: list[str] = Field(description="Effective permissions; drives what the UI shows")
    is_creator: bool

    @staticmethod
    def of(actor: Actor) -> MeResponse:
        return MeResponse(
            user=UserView(id=actor.user_id, email=actor.email, name=actor.name),
            workspace=WorkspaceView(id=actor.workspace_id, name=actor.workspace_name),
            role=RoleView(id=actor.role_id, key=actor.role_key, name=actor.role_name),
            permissions=sorted(actor.permissions),
            is_creator=actor.is_creator,
        )
