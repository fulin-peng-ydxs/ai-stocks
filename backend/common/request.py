"""Shared request metadata helpers for trusted server-side audit snapshots."""

from __future__ import annotations

from typing import Any

from backend.config import get_effective_settings


def trusted_client_ip(request: Any, *, default: str | None = None) -> str | None:
    """Resolve client IP with the same trusted-proxy boundary used by API rate limiting."""
    if get_effective_settings().server.trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
    client = getattr(request, "client", None)
    return getattr(client, "host", None) or default
