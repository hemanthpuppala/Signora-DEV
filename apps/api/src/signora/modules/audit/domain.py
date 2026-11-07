"""Audit domain: chains, actors, canonical form and hashing (backbone LLD topic 4).

Pure Python: no database or web-framework imports (import contract 4).
"""

from __future__ import annotations

import hashlib
import ipaddress
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from signora.kernel.canonical import canonical_json

GENESIS_HASH = bytes(32)
# Reserved id of the system workspace (its row is created by the Phase 2 migration).
SYSTEM_WORKSPACE_ID = uuid.UUID(int=0)

ActorType = Literal["user", "recipient", "system"]
JsonScalar = str | int | bool | None


class ChainKind(StrEnum):
    SYSTEM = "system"
    WORKSPACE = "workspace"
    ENVELOPE = "envelope"


@dataclass(frozen=True)
class AuditChain:
    kind: ChainKind
    chain_id: uuid.UUID
    workspace_id: uuid.UUID

    @staticmethod
    def envelope(workspace_id: uuid.UUID, envelope_id: uuid.UUID) -> AuditChain:
        return AuditChain(ChainKind.ENVELOPE, envelope_id, workspace_id)

    @staticmethod
    def workspace(workspace_id: uuid.UUID) -> AuditChain:
        return AuditChain(ChainKind.WORKSPACE, workspace_id, workspace_id)

    @staticmethod
    def system() -> AuditChain:
        return AuditChain(ChainKind.SYSTEM, SYSTEM_WORKSPACE_ID, SYSTEM_WORKSPACE_ID)

    @property
    def lock_key(self) -> int:
        """Advisory-lock key: the random tail of the chain UUID as a signed 64-bit integer."""
        return int.from_bytes(self.chain_id.bytes[8:], "big", signed=True)


@dataclass(frozen=True)
class Actor:
    type: ActorType
    id: uuid.UUID | None = None
    label: str | None = None  # name/email as it was at the time of the action

    @staticmethod
    def system() -> Actor:
        return Actor("system")


@dataclass(frozen=True)
class Subject:
    type: str
    id: uuid.UUID


@dataclass(frozen=True)
class AuditEntry:
    chain: AuditChain
    seq: int
    occurred_at: datetime
    actor: Actor
    action: str
    subject: Subject | None
    request_id: str | None
    ip: str | None
    user_agent: str | None
    data: Mapping[str, Any] = field(default_factory=dict)
    hash: bytes = GENESIS_HASH


def canonical_ip(ip: str | None) -> str | None:
    """Canonical text form: compressed IPv6, IPv4-mapped IPv6 reduced to IPv4 (LLD §4.3)."""
    if ip is None:
        return None
    address = ipaddress.ip_address(ip)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return str(address.ipv4_mapped)
    return str(address)


def canonical_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("audit timestamps must be timezone-aware")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def check_data(value: Any, path: str = "data") -> None:
    """Audit data may hold only strings, integers, booleans, null, lists and objects."""
    if isinstance(value, bool | int | str) or value is None:
        return
    if isinstance(value, float):
        raise TypeError(f"{path}: floating-point numbers are not allowed in audit data")
    if isinstance(value, list | tuple):
        for index, item in enumerate(value):
            check_data(item, f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path}: object keys must be strings")
            check_data(item, f"{path}.{key}")
        return
    raise TypeError(f"{path}: unsupported type {type(value).__name__}")


def hashed_fields(entry: AuditEntry) -> dict[str, Any]:
    """Every column except ``hash``, in canonical form (LLD §4.3)."""
    return {
        "chain_kind": entry.chain.kind.value,
        "chain_id": str(entry.chain.chain_id),
        "seq": entry.seq,
        "workspace_id": str(entry.chain.workspace_id),
        "occurred_at": canonical_timestamp(entry.occurred_at),
        "actor_type": entry.actor.type,
        "actor_id": str(entry.actor.id) if entry.actor.id else None,
        "actor_label": entry.actor.label,
        "action": entry.action,
        "subject_type": entry.subject.type if entry.subject else None,
        "subject_id": str(entry.subject.id) if entry.subject else None,
        "request_id": entry.request_id,
        "ip": canonical_ip(entry.ip),
        "user_agent": entry.user_agent,
        "data": dict(entry.data),
    }


def compute_hash(previous_hash: bytes, entry: AuditEntry) -> bytes:
    return hashlib.sha256(previous_hash + canonical_json(hashed_fields(entry))).digest()


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    entries_checked: int
    head_seq: int
    head_hash: bytes
    failed_seq: int | None = None
    reason: str | None = None
