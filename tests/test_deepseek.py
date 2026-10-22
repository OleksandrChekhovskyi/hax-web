from __future__ import annotations

import os
import unittest
from typing import Any
from unittest import mock

import support  # noqa: F401
from hax_web import WebError, deepseek


class RequestTests(unittest.TestCase):
    def setUp(self) -> None:
        patch = mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "key"})
        patch.start()
        self.addCleanup(patch.stop)

    def test_search_requests_count_and_normalizes_results(self) -> None:
        response = {
            "results": [
                {
                    "title": "Example",
                    "url": "https://example.com/page#1",
                    "date": "2026-01-02T16:00:00+00:00",
                    "snippet": "Short",
                    "summary": "Long summary",
                }
            ]
        }
        with mock.patch.object(deepseek, "post_json", return_value=response) as post:
            data = deepseek.search(" query ", 3)

        post.assert_called_once_with(
            "https://api.deepseek.com/v1/tools/search",
            {"query": "query", "count": 3},
            {"Authorization": "Bearer key"},
            "DeepSeek",
        )
        self.assertEqual(
            data,
            {
                "query": "query",
                "results": [
                    {
                        "title": "Example",
                        "url": "https://example.com/page",
                        "published_at": "2026-01-02T16:00:00+00:00",
                        "author": "",
                        "excerpt": "Long summary",
                    }
                ],
            },
        )

    def test_fetch_sends_only_the_url(self) -> None:
        response = {"title": "Page", "content": "Text"}
        with mock.patch.object(deepseek, "post_json", return_value=response) as post:
            page = deepseek.fetch("https://example.com", 100, True)

        post.assert_called_once_with(
            "https://api.deepseek.com/v1/tools/fetch",
            {"url": "https://example.com"},
            {"Authorization": "Bearer key"},
            "DeepSeek",
        )
        self.assertEqual((page["title"], page["content"]), ("Page", "Text"))

    def test_search_rejects_empty_query(self) -> None:
        with self.assertRaisesRegex(WebError, "empty"):
            deepseek.search("  ", 5)

    def test_missing_key_is_reported(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(deepseek.unavailable(), "DEEPSEEK_API_KEY is not set")
            with self.assertRaisesRegex(WebError, "DEEPSEEK_API_KEY is not set"):
                deepseek.search("query", 5)


class SearchTests(unittest.TestCase):
    def test_search_strips_chunk_numbers_from_urls(self) -> None:
        urls = (
            ("https://a.test/issues/1#issuecomment-2#1", "https://a.test/issues/1#issuecomment-2"),
            ("https://a.test/doc.pdf#3#8", "https://a.test/doc.pdf"),
            ("https://a.test/page", "https://a.test/page"),
            ("https://a.test/page#section", "https://a.test/page#section"),
        )
        response: Any = {"results": [{"url": url} for url, _ in urls]}
        results = deepseek.normalize_search(response, "query")["results"]
        self.assertEqual([result["url"] for result in results], [url for _, url in urls])

    def test_search_falls_back_to_snippet_and_closes_open_blocks(self) -> None:
        response: Any = {
            "results": [
                {"summary": "", "snippet": "Snippet"},
                {"summary": "```c\nint x;"},
            ]
        }
        results = deepseek.normalize_search(response, "query")["results"]
        self.assertEqual(
            [result["excerpt"] for result in results], ["Snippet", "```c\nint x;\n```"]
        )

    def test_search_rejects_missing_results(self) -> None:
        with self.assertRaisesRegex(WebError, "results"):
            deepseek.normalize_search({}, "query")


class FetchTests(unittest.TestCase):
    def test_fetch_unescapes_punctuation_without_inline_meaning(self) -> None:
        content = "\n\n".join([r"\#\# Build", r"    \$ \.\/configure", r"1\. C\:\\path\, \(see\)"])
        page = deepseek.normalize_fetch({"content": content}, "https://a.test", 1000)
        expected = "\n\n".join(["## Build", "    $ ./configure", r"1. C:\\path, (see)"])
        self.assertEqual(page["content"], expected)

    def test_unescaping_keeps_escapes_that_prevent_markup(self) -> None:
        cases = (
            (r"\_\_init\_\_\(\)", r"\_\_init\_\_()"),
            (r"\*p", r"\*p"),
            (r"x\[0\]", r"x\[0\]"),
            (r"\#include \<vector\>", r"#include \<vector\>"),
            ("\n" + r"\>\>\> f\(\)", "\n" + r"\>\>\> f()"),
            (r"\`x\`", r"\`x\`"),
            (r"\&amp\;", r"\&amp;"),
            (r"\~\~x\~\~", r"\~\~x\~\~"),
        )
        content = r"\, ".join(escaped for escaped, _ in cases)
        self.assertEqual(deepseek.unescape(content), ", ".join(kept for _, kept in cases))

    def test_unescaping_restores_list_bullets(self) -> None:
        content = "  \\* item\\, more\n\\*p \\= 1\\;"
        self.assertEqual(deepseek.unescape(content), "  * item, more\n\\*p = 1;")

    def test_escaped_content_without_commas_is_unescaped(self) -> None:
        self.assertEqual(deepseek.unescape(r"\# http\.badssl\.com"), "# http.badssl.com")

    def test_content_with_only_needed_escapes_is_left_as_is(self) -> None:
        content = r"1\. Not a list: a \*literal\* star, \<vector\>, and \# text."
        self.assertEqual(deepseek.unescape(content), content)

    def test_fetch_truncates_locally_and_closes_open_blocks(self) -> None:
        response: Any = {"title": "", "content": "```\n" + "x" * 20}
        page = deepseek.normalize_fetch(response, "https://a.test", 10)
        self.assertEqual(
            (page["title"], page["content"], page["truncated"]),
            ("Untitled", "```\nxxxxxx\n```", True),
        )

    def test_fetch_leaves_content_within_the_limit_unchanged(self) -> None:
        page = deepseek.normalize_fetch({"content": "```\ncode"}, "https://a.test", 100)
        self.assertEqual((page["content"], page["truncated"]), ("```\ncode", False))

    def test_fetch_reports_empty_content(self) -> None:
        with self.assertRaisesRegex(WebError, "no content"):
            deepseek.normalize_fetch({"title": "Page", "content": "  "}, "https://a.test", 100)


if __name__ == "__main__":
    unittest.main()
