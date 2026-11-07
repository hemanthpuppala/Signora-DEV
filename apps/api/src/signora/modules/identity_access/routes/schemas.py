"""Request and response bodies of the identity API (they become the frontend contract types)."""

from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from signora.modules.identity_access.access import Actor

# Long enough for any passphrase; short enough that nobody makes the server hash a megabyte.
PasswordInput = Annotated[str, StringConstraints(min_length=1, max_length=1024)]
NameInput = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
EmailInput = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=254)]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


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
