from __future__ import annotations

import http.client
import io
import unittest
import urllib.error
from email.message import Message
from typing import Final, Optional
from unittest import mock

import support  # noqa: F401
from hax_web import WebError, transport

URL: Final = "https://api.exa.ai/test"


class ReadResponse:
    def __init__(self, body: bytes = b"", error: Optional[BaseException] = None) -> None:
        self.body = body
        self.error = error

    def __enter__(self) -> ReadResponse:
        return self

    def __exit__(self, *_: object) -> bool:
        return False

    def read(self, limit: int) -> bytes:
        if self.error is not None:
            raise self.error
        return self.body if limit < 0 else self.body[:limit]


class HttpTests(unittest.TestCase):
    def test_retries_mid_response_failures(self) -> None:
        responses = [
            ReadResponse(error=http.client.IncompleteRead(b"partial")),
            ReadResponse(error=ConnectionResetError("reset")),
            ReadResponse(body=b'{"ok":true}'),
        ]
        urlopen = mock.patch.object(transport.urllib.request, "urlopen", side_effect=responses)
        with urlopen as opened, mock.patch.object(transport.time, "sleep"):
            result = transport.post_json(URL, {}, {}, "Exa")
        self.assertEqual(result, {"ok": True})
        self.assertEqual(opened.call_count, 3)

    def test_exhausted_mid_response_failures_become_web_error(self) -> None:
        responses = [ReadResponse(error=ConnectionResetError("reset")) for _ in range(3)]
        with mock.patch.object(transport.urllib.request, "urlopen", side_effect=responses):
            with mock.patch.object(transport.time, "sleep"):
                with self.assertRaisesRegex(WebError, "could not reach Exa"):
                    transport.post_json(URL, {}, {}, "Exa")

    def test_http_error_body_failure_preserves_status(self) -> None:
        class BrokenHttpError(urllib.error.HTTPError):
            def read(self, n: int = -1, /) -> bytes:
                raise ConnectionResetError("reset")

        error = BrokenHttpError(URL, 400, "bad request", Message(), io.BytesIO())
        self.addCleanup(error.close)
        with mock.patch.object(transport.urllib.request, "urlopen", side_effect=error):
            with self.assertRaisesRegex(WebError, "HTTP 400"):
                transport.post_json(URL, {}, {}, "Exa")

    def test_non_finite_retry_after_uses_backoff(self) -> None:
        for value in ("NaN", "Infinity", "-Infinity"):
            headers = Message()
            headers["Retry-After"] = value
            error = urllib.error.HTTPError(URL, 429, "rate limited", headers, io.BytesIO())
            self.addCleanup(error.close)
            with self.subTest(value=value):
                self.assertEqual(transport.retry_delay(error, 1), 2)


if __name__ == "__main__":
    unittest.main()
