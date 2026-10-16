from __future__ import annotations

import http.client
import json
import math
import time
import urllib.error
import urllib.request
from typing import Final, cast

from . import VERSION, JsonObject, WebError
from .text import sanitize_text

MAX_RESPONSE_BYTES: Final = 2 * 1024 * 1024
RETRY_STATUSES: Final = {429, 500, 502, 503, 504}
TRANSPORT_ERRORS: Final = (urllib.error.URLError, http.client.HTTPException, OSError)


def retry_delay(error: urllib.error.HTTPError, attempt: int) -> float:
    fallback = 2**attempt
    value = error.headers.get("Retry-After") if error.headers else None
    if value is None:
        return fallback
    try:
        delay = float(value)
    except ValueError:
        return fallback
    if not math.isfinite(delay):
        return fallback
    return min(max(delay, 0), 10)


def api_error_message(body: bytes, status: int, provider: str) -> str:
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = None
    if isinstance(data, dict):
        detail = data.get("message") or data.get("error") or data.get("detail")
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("tag")
        if isinstance(detail, str) and detail:
            return sanitize_text(detail)
    return f"{provider} returned HTTP {status}"


def post_json(url: str, payload: JsonObject, headers: dict[str, str], provider: str) -> JsonObject:
    """POST `payload` and return the JSON object reply, retrying transient failures.

    `headers` carry the provider's authentication; `provider` names it in error messages.
    """
    body = json.dumps(payload, separators=(",", ":")).encode()
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Content-Type": "application/json",
            "User-Agent": f"hax-web/{VERSION}",
            **headers,
        },
        method="POST",
    )

    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise WebError(f"{provider} response exceeded 2 MiB")
                try:
                    data = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError) as error:
                    raise WebError(f"{provider} returned invalid JSON") from error
                if not isinstance(data, dict):
                    raise WebError(f"{provider} returned an unexpected response")
                return cast(JsonObject, data)
        except urllib.error.HTTPError as error:
            if error.code in RETRY_STATUSES and attempt < 2:
                time.sleep(retry_delay(error, attempt))
                continue
            try:
                raw = error.read(64 * 1024)
            except TRANSPORT_ERRORS:
                raw = b""
            raise WebError(api_error_message(raw, error.code, provider)) from error
        except TRANSPORT_ERRORS as error:
            if attempt < 2:
                time.sleep(2**attempt)
                continue
            reason = error.reason if isinstance(error, urllib.error.URLError) else error
            raise WebError(f"could not reach {provider}: {sanitize_text(str(reason))}") from error
    raise WebError(f"could not reach {provider}")
