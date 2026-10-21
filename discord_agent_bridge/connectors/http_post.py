"""Shared HTTPS POST for connectors. Tests pass a fake transport."""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import NamedTuple, Protocol


class HttpResult(NamedTuple):
    status: int
    body: str


class HttpTransport(Protocol):
    def post(self, url: str, headers: Mapping[str, str], body: bytes) -> HttpResult: ...


class HttpDeliveryError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


def urllib_post(url: str, headers: Mapping[str, str], body: bytes) -> HttpResult:
    request = urllib.request.Request(
        url,
        data=body,
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return HttpResult(response.status, response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return HttpResult(exc.code, exc.read().decode("utf-8", errors="replace"))
    except urllib.error.URLError as exc:
        raise HttpDeliveryError(0) from exc


def post_json(
    transport: HttpTransport,
    url: str,
    headers: Mapping[str, str],
    body: bytes,
) -> None:
    try:
        result = transport.post(url, headers, body)
    except HttpDeliveryError:
        raise
    except Exception as exc:
        raise HttpDeliveryError(0) from exc
    if result.status < 200 or result.status >= 300:
        raise HttpDeliveryError(result.status)
