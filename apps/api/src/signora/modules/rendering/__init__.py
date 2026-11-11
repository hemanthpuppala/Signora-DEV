"""Rendering module: values and signatures written into a PDF's pages, and the certificate of
completion (Phase 8 LLD §10, §11). It only draws: what to draw and who may see it are decided by
its callers.

Public interface — other modules import only from here.
"""

from signora.modules.rendering.draw import (
    DrawnSignature,
    Item,
    Mark,
    Text,
    TypedSignature,
    render,
)

__all__ = ["DrawnSignature", "Item", "Mark", "Text", "TypedSignature", "render"]
