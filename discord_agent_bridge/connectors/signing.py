"""HMAC helpers. Hermes V2 is the documented generic signature; V1 is legacy."""

from __future__ import annotations

import hashlib
import hmac


def signature_v1(secret: str, body: bytes) -> str:
    """Raw HMAC-SHA256 hex of the body. Hermes `X-Webhook-Signature`."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def signature_v2(secret: str, timestamp: str, body: bytes) -> str:
    """HMAC-SHA256 hex of ``{timestamp}.{body}``. Hermes `X-Webhook-Signature-V2`."""
    signed = timestamp.encode("utf-8") + b"." + body
    return hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
