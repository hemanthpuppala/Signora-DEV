"""Reading and writing a version's parties, fields and places (Phase 6 LLD §9, §11).

Each read and write is a constant number of statements over O(R + F + P) rows.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from signora.modules.review.editing import (
    Settled,
    Stored,
    StoredField,
    StoredParty,
    StoredPlace,
    is_sensitive,
    unchanged,
)
from signora.modules.review.proposal import Proposal
from signora.modules.review.views import (
    DependencyView,
    FieldView,
    PlacementView,
    RoleView,
    option_words,
)


def replace_fields(
    session: Session, *, workspace_id: uuid.UUID, version_id: uuid.UUID, proposal: Proposal
) -> None:
    """Replace the version's parties, fields and places with a proposal (detection's handoff,
    ADR-R1), keep the document's flags, and move the revision on, so an editor holding the earlier
    set cannot save over the new one (§1.6)."""
    params = {"v": version_id}
    session.execute(
        text(
            "INSERT INTO version_reviews (version_id, workspace_id, flags) "
            "VALUES (:v, :w, CAST(:flags AS jsonb)) ON CONFLICT (version_id) DO UPDATE SET "
            "flags = EXCLUDED.flags, revision = version_reviews.revision + 1, updated_by = NULL, "
            "updated_at = now()"
        ),
        {"v": version_id, "w": workspace_id, "flags": json.dumps(proposal.flags)},
    )
    session.execute(text("DELETE FROM version_fields WHERE version_id = :v"), params)
    session.execute(text("DELETE FROM version_roles WHERE version_id = :v"), params)
    party_ids: dict[str, uuid.UUID] = {}
    if proposal.parties:
        rows = session.execute(
            text(
                "INSERT INTO version_roles (workspace_id, version_id, slug, label, kind, position) "
                "SELECT :w, :v, r.slug, r.label, r.kind, r.position FROM jsonb_to_recordset("
                "CAST(:roles AS jsonb)) AS r(slug text, label text, kind text, position int) "
                "RETURNING id, slug"
            ),
            {
                "w": workspace_id,
                "v": version_id,
                "roles": json.dumps(
                    [
                        {"slug": p.slug, "label": p.label, "kind": p.kind, "position": p.position}
                        for p in proposal.parties
                    ]
                ),
            },
        ).all()
        party_ids = {row.slug: row.id for row in rows}
    if not proposal.fields:
        return
    fields = [
        {
            "key": field.key,
            "label": field.label,
            "holds": field.holds,
            "filled_by": field.filled_by,
            "role_id": str(party_ids[field.party]) if field.party in party_ids else None,
            "required": field.required,
            "sensitive": field.sensitive,
            "needs_review": field.needs_review,
        }
        for field in proposal.fields
    ]
    field_ids = {
        row.key: row.id
        for row in session.execute(
            text(
                "INSERT INTO version_fields (workspace_id, version_id, key, label, holds, "
                "filled_by, role_id, required, sensitive, needs_review, origin) "
                "SELECT :w, :v, f.key, f.label, f.holds, f.filled_by, f.role_id, f.required, "
                "f.sensitive, f.needs_review, 'detected' FROM jsonb_to_recordset(CAST(:fields AS "
                "jsonb)) AS f(key text, label text, holds text, filled_by text, role_id uuid, "
                "required boolean, sensitive boolean, needs_review text) RETURNING id, key"
            ),
            {"w": workspace_id, "v": version_id, "fields": json.dumps(fields)},
        )
    }
    dependencies = [
        {
            "id": str(field_ids[f.key]),
            "on_id": str(field_ids[f.depends_on[0]]),
            "option": f.depends_on[1],
        }
        for f in proposal.fields
        if f.depends_on is not None and f.depends_on[0] in field_ids
    ]
    if dependencies:
        session.execute(
            text(
                "UPDATE version_fields AS f SET depends_on_field_id = d.on_id, "
                "depends_on_option = d.option FROM jsonb_to_recordset(CAST(:deps AS jsonb)) "
                "AS d(id uuid, on_id uuid, option text) WHERE f.id = d.id"
            ),
            {"deps": json.dumps(dependencies)},
        )
    places = [
        {
            "field_id": str(field_ids[field.key]),
            "page": place.page,
            "x0": place.rect[0],
            "y0": place.rect[1],
            "x1": place.rect[2],
            "y1": place.rect[3],
            "kind": place.kind,
            "pdf_field": place.pdf_field,
            "option_value": place.option_value,
            "option_text": place.option_text,
        }
        for field in proposal.fields
        for place in field.places
    ]
    session.execute(
        text(
            "INSERT INTO field_placements (workspace_id, version_id, field_id, page, x0, y0, x1, "
            "y1, kind, pdf_field, option_value, option_text) SELECT :w, :v, p.field_id, p.page, "
            "p.x0, p.y0, p.x1, p.y1, p.kind, p.pdf_field, p.option_value, p.option_text FROM "
            "jsonb_to_recordset(CAST(:places AS jsonb)) AS p(field_id uuid, page int, "
            "x0 float8, y0 float8, x1 float8, y1 float8, kind text, pdf_field text, "
            "option_value text, option_text text)"
        ),
        {"w": workspace_id, "v": version_id, "places": json.dumps(places)},
    )


def read_set(session: Session, version_id: uuid.UUID) -> tuple[list[RoleView], list[FieldView]]:
    """A version's parties (with their field counts) and fields with their places, in reading
    order: two indexed queries for the fields, one for the parties."""
    fields: dict[uuid.UUID, dict[str, Any]] = {}
    for row in session.execute(
        text(
            "SELECT f.id, f.key, f.label, f.holds, f.holds_label, f.filled_by, r.slug AS role, "
            "f.role_id, f.required, f.sensitive, d.key AS depends_key, f.depends_on_option, "
            "f.needs_review, f.origin "
            "FROM version_fields f LEFT JOIN version_roles r ON r.id = f.role_id "
            "LEFT JOIN version_fields d ON d.id = f.depends_on_field_id "
            "WHERE f.version_id = :v ORDER BY f.id"
        ),
        {"v": version_id},
    ):
        fields[row.id] = {
            "id": row.id,
            "key": row.key,
            "label": row.label,
            "holds": row.holds,
            "holds_label": row.holds_label,
            "filled_by": row.filled_by,
            "role": row.role,
            "party_id": row.role_id,
            "origin": row.origin,
            "required": row.required,
            "sensitive": row.sensitive,
            "depends_on": DependencyView(key=row.depends_key, option=row.depends_on_option)
            if row.depends_key
            else None,
            "needs_review": row.needs_review,
            "placements": [],
        }
    for row in session.execute(
        text(
            "SELECT id, field_id, page, x0, y0, x1, y1, kind, option_value, option_text "
            "FROM field_placements WHERE version_id = :v ORDER BY page, y0, x0"
        ),
        {"v": version_id},
    ):
        fields[row.field_id]["placements"].append(
            PlacementView(
                id=row.id,
                page=row.page,
                rect=(row.x0, row.y0, row.x1, row.y1),
                kind=row.kind,
                option_value=row.option_value,
                option_text=option_words(row.option_text),
            )
        )
    views = sorted(
        (FieldView(**field) for field in fields.values()),
        key=lambda f: (
            (f.placements[0].page, f.placements[0].rect[1], f.placements[0].rect[0])
            if f.placements
            else (0, 0.0, 0.0)
        ),
    )
    counts: dict[str, int] = {}
    for view in views:
        if view.role:
            counts[view.role] = counts.get(view.role, 0) + 1
    roles = [
        RoleView(
            id=row.id,
            slug=row.slug,
            label=row.label,
            kind=row.kind,
            kind_label=row.kind_label,
            position=row.position,
            field_count=counts.get(row.slug, 0),
        )
        for row in session.execute(
            text(
                "SELECT id, slug, label, kind, kind_label, position FROM version_roles "
                "WHERE version_id = :v ORDER BY position"
            ),
            {"v": version_id},
        )
    ]
    return roles, views


def read_review(session: Session, version_id: uuid.UUID) -> tuple[int, dict[str, bool]]:
    """A version's revision and the document's flags (0 and none before detection stored any)."""
    row = session.execute(
        text("SELECT revision, flags FROM version_reviews WHERE version_id = :v"), {"v": version_id}
    ).one_or_none()
    return (row.revision, dict(row.flags)) if row is not None else (0, {})


def read_stored(session: Session, version_id: uuid.UUID) -> Stored:
    """A version's set as editing compares it: by id, with each place's PDF field name."""
    parties = {
        row.id: StoredParty(row.id, row.label, row.kind, row.kind_label, row.position)
        for row in session.execute(
            text(
                "SELECT id, label, kind, kind_label, position FROM version_roles "
                "WHERE version_id = :v"
            ),
            {"v": version_id},
        )
    }
    fields = {
        row.id: StoredField(
            id=row.id,
            label=row.label,
            holds=row.holds,
            holds_label=row.holds_label,
            filled_by=row.filled_by,
            party_id=row.role_id,
            required=row.required,
            sensitive=row.sensitive,
            depends_on=(row.depends_on_field_id, row.depends_on_option)
            if row.depends_on_field_id
            else None,
            needs_review=row.needs_review,
            origin=row.origin,
        )
        for row in session.execute(
            text(
                "SELECT id, label, holds, holds_label, filled_by, role_id, required, sensitive, "
                "depends_on_field_id, depends_on_option, needs_review, origin "
                "FROM version_fields WHERE version_id = :v"
            ),
            {"v": version_id},
        )
    }
    places = {
        row.id: StoredPlace(
            id=row.id,
            field_id=row.field_id,
            page=row.page,
            rect=(row.x0, row.y0, row.x1, row.y1),
            kind=row.kind,
            pdf_field=row.pdf_field,
            option_value=row.option_value,
            option_text=row.option_text,
        )
        for row in session.execute(
            text(
                "SELECT id, field_id, page, x0, y0, x1, y1, kind, pdf_field, option_value, "
                "option_text FROM field_placements WHERE version_id = :v"
            ),
            {"v": version_id},
        )
    }
    return Stored(parties=parties, fields=fields, places=places)


def write_set(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    version_id: uuid.UUID,
    settled: Settled,
    stored: Stored,
) -> None:
    """Write a settled set in place of the stored one, keeping the editor's ids: a constant number
    of statements over O(R + F + P) rows. A place from the PDF keeps its form field name; a field
    keeps its origin, and its flag only while it is unchanged (§2.2)."""
    params = {"v": version_id}
    session.execute(text("DELETE FROM version_fields WHERE version_id = :v"), params)
    session.execute(text("DELETE FROM version_roles WHERE version_id = :v"), params)
    if settled.parties:
        session.execute(
            text(
                "INSERT INTO version_roles (id, workspace_id, version_id, slug, label, kind, "
                "kind_label, position) SELECT r.id, :w, :v, r.slug, r.label, r.kind, r.kind_label, "
                "r.position FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(id uuid, slug text, "
                "label text, kind text, kind_label text, position int)"
            ),
            {
                "w": workspace_id,
                "v": version_id,
                "rows": json.dumps(
                    [
                        {
                            "id": str(party.id),
                            "slug": party_slug,
                            "label": party.label.strip(),
                            "kind": party.kind,
                            "kind_label": party.kind_label,
                            "position": position,
                        }
                        for position, (party, party_slug) in enumerate(settled.parties, start=1)
                    ]
                ),
            },
        )
    if not settled.fields:
        return
    rows = []
    for item, key in settled.fields:
        before = stored.fields.get(item.id)
        rows.append(
            {
                "id": str(item.id),
                "key": key,
                "label": item.label.strip(),
                "holds": item.holds,
                "holds_label": item.holds_label,
                "filled_by": item.filled_by,
                "role_id": str(item.party_id) if item.party_id else None,
                "required": item.required,
                "sensitive": is_sensitive(item),
                "needs_review": before.needs_review
                if before is not None and unchanged(item, before, stored)
                else None,
                "origin": before.origin if before is not None else "added",
            }
        )
    session.execute(
        text(
            "INSERT INTO version_fields (id, workspace_id, version_id, key, label, holds, "
            "holds_label, filled_by, role_id, required, sensitive, needs_review, origin) "
            "SELECT f.id, :w, :v, f.key, f.label, f.holds, f.holds_label, f.filled_by, f.role_id, "
            "f.required, f.sensitive, f.needs_review, f.origin FROM jsonb_to_recordset(CAST(:rows "
            "AS jsonb)) AS f(id uuid, key text, label text, holds text, holds_label text, "
            "filled_by text, role_id uuid, required boolean, sensitive boolean, needs_review text, "
            "origin text)"
        ),
        {"w": workspace_id, "v": version_id, "rows": json.dumps(rows)},
    )
    dependencies = [
        {
            "id": str(item.id),
            "target": str(item.depends_on.field_id),
            "option": item.depends_on.option,
        }
        for item, _ in settled.fields
        if item.depends_on is not None
    ]
    if dependencies:
        session.execute(
            text(
                "UPDATE version_fields AS f SET depends_on_field_id = d.target, "
                "depends_on_option = d.option FROM jsonb_to_recordset(CAST(:deps AS jsonb)) "
                "AS d(id uuid, target uuid, option text) WHERE f.id = d.id"
            ),
            {"deps": json.dumps(dependencies)},
        )
    places = [
        {
            "id": str(place.id),
            "field_id": str(item.id),
            "page": place.page,
            "x0": place.rect[0],
            "y0": place.rect[1],
            "x1": place.rect[2],
            "y1": place.rect[3],
            "kind": place.kind,
            "pdf_field": stored.places[place.id].pdf_field if place.id in stored.places else None,
            "option_value": place.option_value,
            "option_text": place.option_text,
        }
        for item, _ in settled.fields
        for place in item.places
    ]
    session.execute(
        text(
            "INSERT INTO field_placements (id, workspace_id, version_id, field_id, page, x0, y0, "
            "x1, y1, kind, pdf_field, option_value, option_text) SELECT p.id, :w, :v, p.field_id, "
            "p.page, p.x0, p.y0, p.x1, p.y1, p.kind, p.pdf_field, p.option_value, p.option_text "
            "FROM jsonb_to_recordset(CAST(:places AS jsonb)) AS p(id uuid, field_id uuid, "
            "page int, x0 float8, y0 float8, x1 float8, y1 float8, kind text, pdf_field text, "
            "option_value text, option_text text)"
        ),
        {"w": workspace_id, "v": version_id, "places": json.dumps(places)},
    )
