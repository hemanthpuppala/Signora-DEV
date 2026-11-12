"""Request and response bodies of the identity API (they become the frontend contract types)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from signora.modules.identity_access.access import Actor
from signora.modules.identity_access.domain.permissions import (
    OWNER_DESCRIPTION,
    OWNER_LABEL,
    Permission,
)

# Long enough for any passphrase; short enough that nobody makes the server hash a megabyte.
PasswordInput = Annotated[str, StringConstraints(min_length=1, max_length=1024)]
NameInput = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
WORKSPACE_LOGO_PATH = "/api/v1/workspace/logo"
EmailInput = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=254)]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoleRef(BaseModel):
    id: uuid.UUID
    name: str
    description: str


class DisplayRole(BaseModel):
    """What people read: "Owner" for the workspace creator, otherwise the role's own words."""

    name: str
    description: str

    @staticmethod
    def of(*, is_creator: bool, name: str, description: str) -> DisplayRole:
        if is_creator:
            return DisplayRole(name=OWNER_LABEL, description=OWNER_DESCRIPTION)
        return DisplayRole(name=name, description=description)


class SignupRequest(_Body):
    email: EmailInput


class TokenRequest(_Body):
    token: Annotated[str, StringConstraints(min_length=16, max_length=128)]


class SignupCompleteRequest(TokenRequest):
    workspace_name: NameInput
    website: Annotated[str, StringConstraints(max_length=2048)] | None = Field(
        default=None, description="Optional; kept as its domain (scoutboard.com)"
    )
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
    role_description: str
    inviter_name: str


class AcceptInviteRequest(TokenRequest):
    name: NameInput
    password: PasswordInput


class MemberView(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    role: RoleRef
    display_role: DisplayRole
    is_creator: bool
    joined_at: datetime


class DirectoryEntryView(BaseModel):
    id: uuid.UUID
    name: str
    email: str


class RoleDetailView(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    description: str
    is_system: bool
    permissions: list[str]


class ChangeRoleRequest(_Body):
    role_id: uuid.UUID


class WebsiteRequest(_Body):
    website: Annotated[str, StringConstraints(max_length=2048)] | None = Field(
        description="Kept as its domain; empty or null removes it (and the logo)"
    )


class NameRequest(_Body):
    name: NameInput


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
    website: str | None = Field(description="The company's website as its domain, when given")
    logo_url: str | None = Field(
        description="The company's logo (PNG), changing with it; null while it has none"
    )

    @staticmethod
    def of(actor: Actor, *, name: str | None = None) -> WorkspaceView:
        logo = actor.workspace_logo
        return WorkspaceView(
            id=actor.workspace_id,
            name=actor.workspace_name if name is None else name,
            website=actor.workspace_website,
            logo_url=None if logo is None else f"{WORKSPACE_LOGO_PATH}?v={logo[:16]}",
        )


class RoleView(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    description: str


class MeResponse(BaseModel):
    user: UserView
    workspace: WorkspaceView
    role: RoleView
    display_role: DisplayRole
    permissions: list[Permission] = Field(
        description="Effective permissions; drives what the UI shows"
    )
    is_creator: bool

    @staticmethod
    def of(actor: Actor) -> MeResponse:
        return MeResponse(
            user=UserView(id=actor.user_id, email=actor.email, name=actor.name),
            workspace=WorkspaceView.of(actor),
            role=RoleView(
                id=actor.role_id,
                key=actor.role_key,
                name=actor.role_name,
                description=actor.role_description,
            ),
            display_role=DisplayRole.of(
                is_creator=actor.is_creator,
                name=actor.role_name,
                description=actor.role_description,
            ),
            permissions=sorted(actor.permissions),
            is_creator=actor.is_creator,
        )
