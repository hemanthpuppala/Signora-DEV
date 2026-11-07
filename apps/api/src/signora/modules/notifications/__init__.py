"""Notifications module: email delivery only (Phase 2 LLD topic 1a).

Callers own the content; this module queues, delivers, retries and records. Public interface —
other modules import only from here.
"""

from signora.modules.notifications.layout import EmailAction, RenderedEmail, render_layout
from signora.modules.notifications.service import send_email

__all__ = ["EmailAction", "RenderedEmail", "render_layout", "send_email"]
