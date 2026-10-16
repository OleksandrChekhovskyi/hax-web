from __future__ import annotations

import os
import unittest
from typing import Any
from unittest import mock

import support  # noqa: F401
from hax_web import WebError, exa


class RequestTests(unittest.TestCase):
    def setUp(self) -> None:
        patch = mock.patch.dict(os.environ, {"EXA_API_KEY": "key"})
        patch.start()
        self.addCleanup(patch.stop)

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
        with mock.patch.object(exa, "post_json", return_value=response) as post:
            result = exa.search("query", 3)

        post.assert_called_once_with(
            "https://api.exa.ai/search",
            {
                "query": "query",
                "type": "auto",
                "numResults": 3,
                "contents": {"highlights": True},
            },
            {"x-api-key": "key"},
            "Exa",
        )
        self.assertEqual(result["results"][0]["excerpt"], "First\n\nSecond")

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
        with mock.patch.object(exa, "post_json", return_value=response) as post:
            result = exa.fetch("https://example.com", 4000, True)

        post.assert_called_once_with(
            "https://api.exa.ai/contents",
            {
                "urls": ["https://example.com"],
                "text": {"maxCharacters": 4000},
                "maxAgeHours": 0,
            },
            {"x-api-key": "key"},
            "Exa",
        )
        self.assertEqual(result["content"], content)

    def test_search_rejects_empty_query(self) -> None:
        with self.assertRaisesRegex(WebError, "empty"):
            exa.search("  ", 5)

    def test_missing_key_is_reported(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(WebError, "EXA_API_KEY is not set"):
                exa.search("query", 5)


class SearchTests(unittest.TestCase):
    def test_search_closes_each_highlight_separately(self) -> None:
        result = exa.normalize_search(
            {"results": [{"highlights": ["```c\nint x;", "", "```\nafter"]}]}, "query"
        )
        self.assertEqual(
            result["results"][0]["excerpt"], "```c\nint x;\n```\n\n```\nafter\n```"
        )

    def test_search_preserves_provider_highlights(self) -> None:
        highlight = "x" * 1500
        result = exa.normalize_search({"results": [{"highlights": [highlight]}]}, "query")
        self.assertEqual(result["results"][0]["excerpt"], highlight)

    def test_search_rejects_missing_results(self) -> None:
        with self.assertRaisesRegex(WebError, "results"):
            exa.normalize_search({}, "query")

    def test_surrogates_are_removed_from_api_text(self) -> None:
        data = exa.normalize_search(
            {"results": [{"title": "Bad\ud800 title", "highlights": ["Text\udfff"]}]}, "query"
        )
        result = data["results"][0]
        self.assertEqual((result["title"], result["excerpt"]), ("Bad title", "Text"))


class FetchTests(unittest.TestCase):
    def test_fetch_marks_content_at_limit_as_truncated(self) -> None:
        for text, truncated in (("```\n" + "x" * 96, True), ("x" * 99, False)):
            response: Any = {"results": [{"title": "Page", "url": "https://a.test", "text": text}]}
            with self.subTest(truncated=truncated):
                page = exa.normalize_fetch(response, "https://a.test", 100)
                self.assertEqual(page["truncated"], truncated)

    def test_fetch_leaves_complete_content_unchanged(self) -> None:
        result = {"title": "Page", "url": "https://a.test", "text": "```\ncode"}
        response: Any = {"results": [result]}
        page = exa.normalize_fetch(response, "https://a.test", 100)
        self.assertEqual(page["content"], "```\ncode")

    def test_fetch_closes_raw_block_cut_by_the_limit(self) -> None:
        result = {"title": "Page", "url": "https://a.test", "text": "```\ncode"}
        response: Any = {"results": [result]}
        page = exa.normalize_fetch(response, "https://a.test", 8)
        self.assertEqual(page["content"], "```\ncode\n```")

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
        with self.assertRaisesRegex(WebError, "CRAWL_NOT_FOUND.*404"):
            exa.normalize_fetch(response, "https://example.com/missing", 100)


if __name__ == "__main__":
    unittest.main()
