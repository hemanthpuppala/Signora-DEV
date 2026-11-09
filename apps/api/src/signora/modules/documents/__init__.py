"""Documents module: agreements, their versions, uploads and processing (Phase 4 LLD).

Public interface — other modules import only from here. Detection (Phase 5) drives a version after
processing through the lifecycle functions.
"""

from signora.modules.documents.domain import detection_failure_message
from signora.modules.documents.errors import FieldsApproved
from signora.modules.documents.lifecycle import (
    StartMode,
    VersionForDetection,
    VersionForReview,
    apply_name_and_description,
    approve_version,
    audit_document,
    fail_detection,
    finish_detection,
    record_field_count,
    require_document,
    start_detection,
    version_for_detection,
    version_for_review,
    version_status,
)
from signora.modules.documents.processing import DocumentVersionProcessed
from signora.modules.documents.routes import router

__all__ = [
    "DocumentVersionProcessed",
    "FieldsApproved",
    "StartMode",
    "VersionForDetection",
    "VersionForReview",
    "apply_name_and_description",
    "approve_version",
    "audit_document",
    "detection_failure_message",
    "fail_detection",
    "finish_detection",
    "record_field_count",
    "require_document",
    "router",
    "start_detection",
    "version_for_detection",
    "version_for_review",
    "version_status",
]
