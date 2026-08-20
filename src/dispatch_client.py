"""Bounded, secret-safe client for the private Make dispatch webhook."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .dispatch_contract import normalize_action_result


MAX_RESPONSE_BYTES = 64 * 1024


def _valid_webhook_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def _post_json(
    webhook_url: str,
    auth_token: str,
    envelope: Mapping[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    if not _valid_webhook_url(webhook_url):
        return {
            "status": "temporarily_unavailable",
            "reason_code": "invalid_endpoint",
        }

    body = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
    request = Request(
        webhook_url,
        data=body,
        method="POST",
        headers={
            "x-make-apikey": auth_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "hpg-voice-gateway/1",
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError):
        return {
            "status": "temporarily_unavailable",
            "reason_code": "dispatch_unreachable",
        }

    if len(raw) > MAX_RESPONSE_BYTES:
        return {
            "status": "temporarily_unavailable",
            "reason_code": "response_too_large",
        }
    try:
        result = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {
            "status": "temporarily_unavailable",
            "reason_code": "invalid_response",
        }
    if not isinstance(result, dict):
        return {
            "status": "temporarily_unavailable",
            "reason_code": "invalid_response",
        }
    return normalize_action_result(result)


async def submit_appointment_request(
    webhook_url: str,
    auth_token: str,
    envelope: Mapping[str, Any],
    timeout_seconds: float = 8,
) -> dict[str, Any]:
    """Submit without logging caller data, endpoint values, or credentials."""

    if not auth_token:
        return {
            "status": "temporarily_unavailable",
            "reason_code": "dispatch_not_configured",
            "accepted": False,
        }
    return await asyncio.to_thread(
        _post_json,
        webhook_url,
        auth_token,
        envelope,
        timeout_seconds,
    )
