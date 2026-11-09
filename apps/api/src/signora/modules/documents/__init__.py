"""Documents module: agreements, their versions, uploads and processing (Phase 4 LLD).

Public interface — other modules import only from here. Detection (Phase 5) drives a version after
processing through the lifecycle functions.
"""

from signora.modules.documents.domain import detection_failure_message
from signora.modules.documents.lifecycle import (
    StartMode,
    VersionForDetection,
    apply_name_and_description,
    fail_detection,
    finish_detection,
    require_document,
    start_detection,
    version_for_detection,
    version_status,
)
from signora.modules.documents.processing import DocumentVersionProcessed
from signora.modules.documents.routes import router

__all__ = [
    "DocumentVersionProcessed",
    "StartMode",
    "VersionForDetection",
    "apply_name_and_description",
    "detection_failure_message",
    "fail_detection",
    "finish_detection",
    "require_document",
    "router",
    "start_detection",
    "version_for_detection",
    "version_status",
]
