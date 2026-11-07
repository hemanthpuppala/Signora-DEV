"""The words of every account email (Phase 2 LLD topics 1, 2, 6). Delivery is the notifications
module's job; links carry their token after ``#`` so it never reaches a server log."""

from __future__ import annotations

from dataclasses import dataclass

from signora.modules.notifications import EmailAction, RenderedEmail, render_layout

FOOTER = "Signora sends this email when someone uses this address on Signora."


@dataclass(frozen=True)
class AccountEmail:
    category: str
    subject: str
    body: RenderedEmail


def link(base_url: str, path: str, token: str) -> str:
    return f"{base_url.rstrip('/')}{path}#{token}"


def verify_signup(base_url: str, token: str, hours: int) -> AccountEmail:
    return AccountEmail(
        "auth.signup_verify",
        "Confirm your email to create your Signora workspace",
        render_layout(
            heading="Confirm your email.",
            paragraphs=[
                "Use the link below to name your workspace and choose a password.",
                f"The link works once and expires in {hours} hours. If you did not ask to join "
                "Signora, ignore this email.",
            ],
            action=EmailAction("Create workspace", link(base_url, "/signup/verify", token)),
            footer=FOOTER,
        ),
    )


def already_registered(base_url: str) -> AccountEmail:
    root = base_url.rstrip("/")
    return AccountEmail(
        "auth.signup_existing",
        "You already have a Signora account",
        render_layout(
            heading="You already have an account.",
            paragraphs=[
                "Someone tried to create a Signora workspace with this email, which already has "
                "an account. Log in instead, or reset your password if you have forgotten it.",
                f"Forgot your password? {root}/forgot-password",
                "If this was not you, you can ignore this email; nothing has changed.",
            ],
            action=EmailAction("Log in", f"{root}/login"),
            footer=FOOTER,
        ),
    )


def reset_password(base_url: str, token: str, minutes: int) -> AccountEmail:
    return AccountEmail(
        "auth.password_reset",
        "Reset your Signora password",
        render_layout(
            heading="Reset your password.",
            paragraphs=[
                "Use the link below to choose a new password. Choosing one signs you out "
                "everywhere else.",
                f"The link works once and expires in {minutes} minutes. If you did not ask for "
                "this, ignore this email; your password stays the same.",
            ],
            action=EmailAction("Reset password", link(base_url, "/reset-password", token)),
            footer=FOOTER,
        ),
    )


def password_changed(base_url: str) -> AccountEmail:
    root = base_url.rstrip("/")
    return AccountEmail(
        "auth.password_changed",
        "Your Signora password was changed",
        render_layout(
            heading="Your password was changed.",
            paragraphs=[
                "The password for your Signora account was just changed, and your other "
                "sessions were signed out.",
                f"If this was not you, reset your password now: {root}/forgot-password",
            ],
            footer=FOOTER,
        ),
    )


def invitation(
    base_url: str, token: str, *, workspace: str, inviter: str, role: str, days: int
) -> AccountEmail:
    return AccountEmail(
        "auth.invite",
        f"{inviter} invited you to {workspace} on Signora",
        render_layout(
            heading=f"Join {workspace}.",
            paragraphs=[
                f"{inviter} invited you to {workspace} on Signora with {role} access.",
                f"The invitation expires in {days} days.",
            ],
            action=EmailAction("Accept invitation", link(base_url, "/invite", token)),
            footer=FOOTER,
        ),
    )


def invitation_blocked(*, workspace: str, inviter: str) -> AccountEmail:
    return AccountEmail(
        "auth.invite_blocked",
        f"{inviter} invited you to {workspace} on Signora",
        render_layout(
            heading=f"An invitation to {workspace}.",
            paragraphs=[
                f"{inviter} invited you to {workspace} on Signora, but this email already belongs "
                "to another workspace. On Signora each email belongs to one workspace, so you "
                "cannot join with it.",
                f"If you need access, ask {inviter} to invite a different email address.",
            ],
            footer=FOOTER,
        ),
    )
