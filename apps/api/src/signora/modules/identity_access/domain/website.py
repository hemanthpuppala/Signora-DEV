"""A company's website, kept as its domain: the one definition of what a website field accepts.

People type a website as they know it ("scoutboard.com", "https://www.app.scoutboard.com/about");
what we keep, look a logo up by and key the logo with is the registrable domain ("scoutboard.com"):
the part a company registers, by the Public Suffix List, so "shop.acme.co.uk" is "acme.co.uk".
Hosted names on a platform's own suffix stay whole ("acme.github.io", not GitHub's "github.io").
The list is the copy shipped with ``tldextract``: nothing is fetched.
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

import tldextract

MAX_WEBSITE_INPUT = 2048
MAX_DOMAIN_LENGTH = 253
_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_TOP_LEVEL = re.compile(r"^(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$")
_SCHEMES = frozenset({"http", "https"})
_MESSAGE = "Enter the company's website, like scoutboard.com"


# The bundled Public Suffix List, private suffixes included (github.io, vercel.app): offline.
_SUFFIXES = tldextract.TLDExtract(
    suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True
)
# The same list without the private suffixes: a platform's own domain (github.io) is registrable.
_ICANN = tldextract.TLDExtract(
    suffix_list_urls=(), cache_dir=None, include_psl_private_domains=False
)


class InvalidWebsiteError(ValueError):
    pass


def company_domain(raw: str) -> str:
    """The registrable domain of a typed website, lower case; IDNs in their ASCII form.

    Raises ``InvalidWebsiteError`` for anything that is not a public host name: no IP addresses,
    no single-label names (``localhost``), no credentials, other schemes or ports out of range,
    and nothing that is only a public suffix (``co.uk``).
    """
    candidate = raw.strip()
    if not candidate or len(candidate) > MAX_WEBSITE_INPUT or any(c.isspace() for c in candidate):
        raise InvalidWebsiteError(_MESSAGE)
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    try:
        parts = urlsplit(candidate)
        parts.port  # noqa: B018 - raises ValueError for a port out of range
    except ValueError:
        raise InvalidWebsiteError(_MESSAGE) from None
    if parts.scheme.lower() not in _SCHEMES or parts.username or parts.password:
        raise InvalidWebsiteError(_MESSAGE)
    host = (parts.hostname or "").rstrip(".")
    try:
        host = host.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise InvalidWebsiteError(_MESSAGE) from None
    host = host.removeprefix("www.")
    if not host or len(host) > MAX_DOMAIN_LENGTH or _is_ip(host):
        raise InvalidWebsiteError(_MESSAGE)
    labels = host.split(".")
    if len(labels) < 2 or not all(_LABEL.match(label) for label in labels):
        raise InvalidWebsiteError(_MESSAGE)
    if not _TOP_LEVEL.match(labels[-1]):
        raise InvalidWebsiteError(_MESSAGE)
    return _registrable(host)


def _registrable(host: str) -> str:
    """The part of ``host`` a company registers. A platform's own domain (``github.io``,
    ``myshopify.com``) is itself; a host on an ending the bundled list does not know yet (a new
    top-level domain) is its last two labels; a public suffix on its own (``co.uk``) is refused."""
    found = _SUFFIXES(host)
    if found.top_domain_under_public_suffix:
        return str(found.top_domain_under_public_suffix)
    if not found.suffix:
        return ".".join(host.split(".")[-2:])  # an ending the list does not know
    icann = _ICANN(host)
    if found.is_private and icann.top_domain_under_public_suffix:
        return str(icann.top_domain_under_public_suffix)
    raise InvalidWebsiteError(_MESSAGE)  # only a public suffix: nobody's company


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True
