from __future__ import annotations

import base64
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def _load_public_key(value: str) -> Ed25519PublicKey:
    value = value.strip()
    if value.startswith("-----BEGIN"):
        key = serialization.load_pem_public_key(value.encode("utf-8"))
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("TELNYX_PUBLIC_KEY is not an Ed25519 key")
        return key

    try:
        raw = bytes.fromhex(value)
    except ValueError:
        try:
            raw = base64.b64decode(value, validate=True)
        except Exception as exc:
            raise ValueError("TELNYX_PUBLIC_KEY must be PEM, hex, or base64") from exc

    if len(raw) != 32:
        raise ValueError("TELNYX_PUBLIC_KEY raw value must be 32 bytes")
    return Ed25519PublicKey.from_public_bytes(raw)


def verify_telnyx_signature(
    raw_body: bytes,
    signature_b64: str,
    timestamp: str,
    public_key: str,
    *,
    now: int | None = None,
    tolerance_seconds: int = 300,
) -> bool:
    if not raw_body or not signature_b64 or not timestamp or not public_key:
        return False
    try:
        timestamp_int = int(timestamp)
        current = int(time.time()) if now is None else now
        if abs(current - timestamp_int) > tolerance_seconds:
            return False
        signature = base64.b64decode(signature_b64, validate=True)
        signed_payload = timestamp.encode("ascii") + b"|" + raw_body
        _load_public_key(public_key).verify(signature, signed_payload)
        return True
    except (ValueError, InvalidSignature, TypeError):
        return False


def stream_token_matches(header_value: str | None, expected: str) -> bool:
    """Validate a Telnyx media-stream token from a WebSocket header value.

    Telnyx currently sends ``stream_auth_token`` as the
    ``x-telnyx-streaming-auth-token`` WebSocket header. Older examples and
    some proxies may use a Bearer-style Authorization header, so this accepts
    either raw-token or ``Bearer <token>`` values.
    """
    if not expected or not header_value:
        return False
    supplied = header_value.strip()
    if supplied.lower().startswith("bearer "):
        supplied = supplied[7:].strip()
    import hmac

    return hmac.compare_digest(supplied, expected)
