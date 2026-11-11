"""Review's refusals (Phase 6 LLD §10)."""

from __future__ import annotations

from signora.kernel.errors import Conflict


class FieldsChanged(Conflict):
    code = "fields-changed"
    title = "Someone else saved these fields since you opened them. Reload to see their changes"


class WarningsChanged(Conflict):
    code = "warnings-changed"
    title = "The things to check have changed. Look at them again before approving"


class VersionNotInReview(Conflict):
    code = "version-not-in-review"
    title = "Only a version in review can be edited or approved"
