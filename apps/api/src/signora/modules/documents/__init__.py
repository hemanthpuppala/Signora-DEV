"""Documents module: agreements, their versions, uploads and processing (Phase 4 LLD).

Public interface — other modules import only from here. Detection (Phase 5) drives a version after
processing through the lifecycle functions.
"""

from signora.modules.documents.domain import detection_failure_message
from signora.modules.documents.errors import FieldsApproved, VersionNotApproved
from signora.modules.documents.lifecycle import (
    StartMode,
    VersionForDetection,
    VersionForReview,
    VersionForSigning,
    apply_name_and_description,
    approve_version,
    audit_document,
    derive_version,
    fail_detection,
    finish_detection,
    hold_document,
    record_field_count,
    require_document,
    start_detection,
    version_for_detection,
    version_for_review,
    version_for_signing,
    version_status,
)
from signora.modules.documents.processing import DocumentVersionProcessed
from signora.modules.documents.routes import router
from signora.modules.documents.service import count_to_approve

__all__ = [
    "DocumentVersionProcessed",
    "FieldsApproved",
    "StartMode",
    "VersionForDetection",
    "VersionForReview",
    "VersionForSigning",
    "VersionNotApproved",
    "apply_name_and_description",
    "approve_version",
    "audit_document",
    "count_to_approve",
    "derive_version",
    "detection_failure_message",
    "fail_detection",
    "finish_detection",
    "hold_document",
    "record_field_count",
    "require_document",
    "router",
    "start_detection",
    "version_for_detection",
    "version_for_review",
    "version_for_signing",
    "version_status",
]
