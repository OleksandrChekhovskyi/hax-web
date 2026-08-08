from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import tempfile
import unittest
from typing import Final, Optional
from unittest import mock

ROOT: Final = pathlib.Path(__file__).resolve().parents[1]
SPEC: Final = importlib.util.spec_from_file_location("hax_web", ROOT / "src" / "hax_web.py")
if SPEC is None or not isinstance(SPEC.loader, importlib.machinery.SourceFileLoader):
    raise RuntimeError("could not load hax_web module")
web = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(web)


class TtyBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


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


class OutputTests(unittest.TestCase):
    def test_auto_display_width_matches_hax(self) -> None:
        self.assertEqual(web.auto_display_width(19), 20)
        self.assertEqual(web.auto_display_width(100), 100)
        self.assertEqual(web.auto_display_width(110), 110)
        self.assertEqual(web.auto_display_width(111), 100)

    def test_direct_output_is_unchanged(self) -> None:
        value = "word " * 120
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(web.limit_agent_lines(value), value)

    def test_hax_output_stays_below_line_cap(self) -> None:
        value = "word " * 300 + "\n" + "é" * 300 + "\n"
        with mock.patch.dict(os.environ, {"AI_AGENT": "hax"}):
            output = web.limit_agent_lines(value)
        self.assertTrue(output.endswith("\n"))
        self.assertTrue(
            all(len(line.encode()) <= web.AGENT_LINE_BYTES for line in output.splitlines())
        )

    def test_tty_output_uses_glow(self) -> None:
        stdout = TtyBuffer()
        completed = mock.Mock(returncode=0)
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch("sys.stdout", stdout):
                with mock.patch.object(web.shutil, "which", return_value="/bin/glow"):
                    with mock.patch.object(
                        web.shutil, "get_terminal_size", return_value=os.terminal_size((105, 24))
                    ):
                        run_patch = mock.patch.object(
                            web.subprocess, "run", return_value=completed
                        )
                        with run_patch as run:
                            web.write_markdown("# Heading\n", False)
        run.assert_called_once_with(
            ["/bin/glow", "--width", "105"],
            input="# Heading\n",
            text=True,
            check=False,
        )
        self.assertEqual(stdout.getvalue(), "")

    def test_no_render_writes_markdown_on_tty(self) -> None:
        stdout = TtyBuffer()
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch("sys.stdout", stdout):
                with mock.patch.object(web.shutil, "which") as which:
                    web.write_markdown("# Heading\n", True)
        which.assert_not_called()
        self.assertEqual(stdout.getvalue(), "# Heading\n")


class UrlTests(unittest.TestCase):
    def test_accepts_public_http_urls(self) -> None:
        url = "https://example.com/a?q=1"
        self.assertEqual(web.validate_public_url(url), url)

    def test_rejects_non_http_and_credentials(self) -> None:
        with self.assertRaisesRegex(web.WebError, "http"):
            web.validate_public_url("file:///etc/passwd")
        with self.assertRaisesRegex(web.WebError, "credentials"):
            web.validate_public_url("https://user:secret@example.com/")

    def test_rejects_private_urls(self) -> None:
        for url in (
            "http://localhost/",
            "http://service.internal/",
            "http://127.0.0.1/",
            "http://10.0.0.1/",
            "http://224.0.0.1/",
            "http://[::1]/",
            "http://[ff02::1]/",
        ):
            with self.subTest(url=url):
                with self.assertRaisesRegex(web.WebError, "private"):
                    web.validate_public_url(url)

    def test_rejects_ambiguous_ipv4_urls(self) -> None:
        for url in (
            "http://127.1/",
            "http://127.0.1/",
            "http://0177.0.0.1/",
            "http://0x7f.0.0.1/",
            "http://2130706433/",
        ):
            with self.subTest(url=url):
                with self.assertRaisesRegex(web.WebError, "ambiguous IPv4"):
                    web.validate_public_url(url)

    def test_rejects_encoded_private_hosts(self) -> None:
        with self.assertRaisesRegex(web.WebError, "percent-encoding"):
            web.validate_public_url("http://%31%32%37.0.0.1/")

    def test_normalizes_unicode_hosts_before_validation(self) -> None:
        with self.assertRaisesRegex(web.WebError, "private"):
            web.validate_public_url("http://１２７.０.０.１/")
        url = "https://例え.テスト/"
        self.assertEqual(web.validate_public_url(url), url)


class HttpTests(unittest.TestCase):
    def test_retries_mid_response_failures(self) -> None:
        responses = [
            ReadResponse(error=web.http.client.IncompleteRead(b"partial")),
            ReadResponse(error=ConnectionResetError("reset")),
            ReadResponse(body=b'{"ok":true}'),
        ]
        with mock.patch.object(web.urllib.request, "urlopen", side_effect=responses) as urlopen:
            with mock.patch.object(web.time, "sleep"):
                result = web.post_json("/test", {}, "key")
        self.assertEqual(result, {"ok": True})
        self.assertEqual(urlopen.call_count, 3)

    def test_exhausted_mid_response_failures_become_web_error(self) -> None:
        responses = [ReadResponse(error=ConnectionResetError("reset")) for _ in range(3)]
        with mock.patch.object(web.urllib.request, "urlopen", side_effect=responses):
            with mock.patch.object(web.time, "sleep"):
                with self.assertRaisesRegex(web.WebError, "could not reach Exa"):
                    web.post_json("/test", {}, "key")

    def test_http_error_body_failure_preserves_status(self) -> None:
        class BrokenHttpError(web.urllib.error.HTTPError):
            def read(self, _: int) -> bytes:
                raise ConnectionResetError("reset")

        error = BrokenHttpError("https://api.exa.ai/test", 400, "bad request", {}, None)
        self.addCleanup(error.close)
        with mock.patch.object(web.urllib.request, "urlopen", side_effect=error):
            with self.assertRaisesRegex(web.WebError, "HTTP 400"):
                web.post_json("/test", {}, "key")

    def test_non_finite_retry_after_uses_backoff(self) -> None:
        for value in ("NaN", "Infinity", "-Infinity"):
            error = web.urllib.error.HTTPError(
                "https://api.exa.ai/test", 429, "rate limited", {"Retry-After": value}, None
            )
            self.addCleanup(error.close)
            with self.subTest(value=value):
                self.assertEqual(web.retry_delay(error, 1), 2)


class SearchTests(unittest.TestCase):
    def test_search_requests_highlights_and_normalizes_results(self) -> None:
        response = {
            "results": [
                {
                    "title": "Example",
                    "url": "https://example.com",
                    "publishedDate": "2026-01-02",
                    "author": "A",
                    "highlights": ["First", "Second"],
                }
            ]
        }
        with mock.patch.object(web, "post_json", return_value=response) as post:
            result = web.search("key", "query", 3)

        post.assert_called_once_with(
            "/search",
            {
                "query": "query",
                "type": "auto",
                "numResults": 3,
                "contents": {"highlights": True},
            },
            "key",
        )
        self.assertEqual(result["results"][0]["excerpt"], "First\n\nSecond")

    def test_search_preserves_provider_highlights(self) -> None:
        highlight = "x" * 1500
        result = web.normalize_search(
            {"results": [{"highlights": [highlight]}]}, "query"
        )
        self.assertEqual(result["results"][0]["excerpt"], highlight)

    def test_search_rejects_empty_query(self) -> None:
        with self.assertRaisesRegex(web.WebError, "empty"):
            web.search("key", "  ", 5)

    def test_search_rejects_missing_results(self) -> None:
        with self.assertRaisesRegex(web.WebError, "results"):
            web.normalize_search({}, "query")

    def test_markdown_escapes_labels_and_strips_terminal_controls(self) -> None:
        data = {
            "query": "a # query",
            "results": [
                {
                    "title": "Bad\x1b[2J *title*",
                    "url": "https://example.com/a b",
                    "published_at": "",
                    "author": "",
                    "excerpt": "Useful text",
                }
            ],
        }
        output = web.format_search(data)
        self.assertNotIn("\x1b", output)
        self.assertIn(r"a \# query", output)
        self.assertIn(r"\*title\*", output)
        self.assertIn("https://example.com/a%20b", output)
        self.assertIn("\nUseful text\n", output)

    def test_excerpt_headings_are_unchanged_without_h1(self) -> None:
        excerpt = "## Source heading\n\n### Detail"
        self.assertEqual(web.demote_excerpt_headings(excerpt), excerpt)

    def test_search_demotes_excerpt_headings_below_result_titles(self) -> None:
        data = {
            "query": "query",
            "results": [
                {
                    "title": "Result",
                    "url": "",
                    "published_at": "",
                    "author": "",
                    "excerpt": (
                        "## Earlier\n\n# Source heading\n\n### Detail\n\n"
                        "```python\n# code comment\n```\n\n###### Deep"
                    ),
                }
            ],
        }
        output = web.format_search(data)
        self.assertTrue(output.startswith("Search results: query\n"))
        self.assertIn("\n# 1. Result\n", output)
        self.assertIn("\n### Earlier\n\n## Source heading\n\n#### Detail\n", output)
        self.assertIn("```python\n# code comment\n```", output)
        self.assertIn("\n###### Deep\n", output)

    def test_markdown_metadata_cannot_add_lines(self) -> None:
        data = {
            "query": "real\n## forged",
            "results": [
                {
                    "title": "Title\n---\n1. forged",
                    "url": "https://example.com/a b\nSource: <https://evil.test>",
                    "published_at": "2026\n## forged",
                    "author": "Alice\nSource: forged",
                    "excerpt": "",
                }
            ],
        }
        output = web.format_search(data)
        self.assertIn("Search results: real \\#\\# forged\n", output)
        self.assertIn("# 1. Title --- 1. forged\n", output)
        self.assertIn(
            "Source: <https://example.com/a%20b%0ASource:%20%3Chttps://evil.test%3E>\n",
            output,
        )
        self.assertIn("Published: 2026 \\#\\# forged\n", output)
        self.assertIn("Author: Alice Source: forged\n", output)

    def test_surrogates_are_removed_from_api_text(self) -> None:
        data = web.normalize_search(
            {"results": [{"title": "Bad\ud800 title", "highlights": ["Text\udfff"]}]}, "query"
        )
        output = web.format_search(data)
        self.assertNotIn("\ud800", output)
        self.assertNotIn("\udfff", output)
        self.assertEqual(output.encode().decode(), output)


class FetchTests(unittest.TestCase):
    def test_fetch_sets_provider_limit_without_local_truncation(self) -> None:
        content = "x" * 5000
        response = {
            "results": [
                {
                    "title": "Page",
                    "url": "https://example.com/final",
                    "text": content,
                }
            ],
            "statuses": [{"id": "https://example.com", "status": "success"}],
        }
        with mock.patch.object(web, "post_json", return_value=response) as post:
            result = web.fetch("key", "https://example.com", 4000, True)

        post.assert_called_once_with(
            "/contents",
            {
                "urls": ["https://example.com"],
                "text": {"maxCharacters": 4000},
                "maxAgeHours": 0,
            },
            "key",
        )
        self.assertEqual(result["content"], content)

    def test_fetch_surfaces_per_url_failure(self) -> None:
        response = {
            "results": [],
            "statuses": [
                {
                    "id": "https://example.com/missing",
                    "status": "error",
                    "error": {"tag": "CRAWL_NOT_FOUND", "httpStatusCode": 404},
                }
            ],
        }
        with self.assertRaisesRegex(web.WebError, "CRAWL_NOT_FOUND.*404"):
            web.normalize_fetch(response, "https://example.com/missing")


class CliTests(unittest.TestCase):
    def test_json_output_is_normalized(self) -> None:
        result = {"query": "q", "results": []}
        stdout = io.StringIO()
        with mock.patch.dict(os.environ, {"EXA_API_KEY": "key", "AI_AGENT": "hax"}):
            with mock.patch.object(web, "search", return_value=result):
                with mock.patch("sys.stdout", stdout):
                    web.main(["search", "q", "--json"])
        self.assertEqual(json.loads(stdout.getvalue()), result)

    def test_launcher_works_through_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            link = pathlib.Path(directory) / "hax-web"
            link.symlink_to(ROOT / "hax-web")
            result = subprocess.run(
                [str(link), "--version"],
                check=False,
                text=True,
                capture_output=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), f"hax-web {web.VERSION}")


if __name__ == "__main__":
    unittest.main()
