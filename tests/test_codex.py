from __future__ import annotations

import base64
import json
import os
import pathlib
import tempfile
import time
import unittest
from typing import Any
from unittest import mock

import support  # noqa: F401
from hax_web import WebError, codex

PAGE_URL = "https://a.test/page"


def jwt(exp: float) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


def citation(ref_id: str) -> str:
    return f"\ue200cite\ue202{ref_id}\ue201 [wordlim: 200]"


def window(first: int, lines: list[str], total: int, url: str = PAGE_URL) -> Any:
    body = "\n".join(f"L{first + index}: {text}" for index, text in enumerate(lines))
    return {
        "encrypted_output": "gAAAAA",
        "output": f"Page ({url})\n{citation('turn0view0')} Total lines: {total}\n{body}\n",
        "results": [{"type": "text_result", "title": "Page", "url": url}],
    }


class CredentialTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.state = pathlib.Path(directory.name, "state")
        self.codex_home = pathlib.Path(directory.name, "codex")
        environ = {"XDG_STATE_HOME": str(self.state), "CODEX_HOME": str(self.codex_home)}
        patch = mock.patch.dict(os.environ, environ)
        patch.start()
        self.addCleanup(patch.stop)

    def write(self, path: pathlib.Path, data: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def write_hax(self, token: str) -> None:
        entry = {"access_token": token, "account_id": "hax-account", "refresh_token": "r"}
        self.write(self.state / "hax/auth.json", {"codex": entry})

    def write_codex(self, token: str) -> None:
        tokens = {"access_token": token, "account_id": "cli-account"}
        self.write(self.codex_home / "auth.json", {"tokens": tokens})

    def test_hax_login_is_preferred(self) -> None:
        self.write_hax(jwt(time.time() + 3600))
        self.write_codex(jwt(time.time() + 3600))
        self.assertEqual(codex.load_credentials().account_id, "hax-account")

    def test_codex_cli_file_is_read_only_as_the_fallback(self) -> None:
        self.write_hax(jwt(time.time() + 3600))
        self.codex_home.mkdir()
        (self.codex_home / "auth.json").write_text("{not json")
        self.assertEqual(codex.load_credentials().account_id, "hax-account")
        (self.state / "hax/auth.json").unlink()
        with self.assertRaisesRegex(WebError, "could not read .*auth.json"):
            codex.load_credentials()

    def test_codex_cli_login_is_the_fallback(self) -> None:
        self.write(self.state / "hax/auth.json", {"exa": {}})
        self.write_codex(jwt(time.time() + 3600))
        self.assertEqual(codex.load_credentials().account_id, "cli-account")

    def test_missing_login_is_reported(self) -> None:
        with self.assertRaisesRegex(WebError, "no ChatGPT login found"):
            codex.load_credentials()
        self.assertIn("no ChatGPT login found", codex.unavailable() or "")

    def test_expired_login_names_its_owner(self) -> None:
        self.write_codex(jwt(time.time() - 1))
        with self.assertRaisesRegex(WebError, "expired; run codex to renew it"):
            codex.load_credentials()

    def test_unreadable_expiry_is_left_to_the_server(self) -> None:
        self.write_hax("opaque-token")
        self.assertIsNone(codex.unavailable())


class RequestTests(unittest.TestCase):
    def setUp(self) -> None:
        credentials = codex.Credentials("token", "account", "renew")
        patch = mock.patch.object(codex, "load_credentials", return_value=credentials)
        patch.start()
        self.addCleanup(patch.stop)

    def test_search_sends_codex_identity_and_normalizes_results(self) -> None:
        response = {
            "output": "text for the model",
            "results": [
                {"type": "image_result", "url": "https://a.test/image"},
                {"type": "text_result", "title": "No URL"},
                {"type": "text_result", "title": "One", "url": "https://a.test/1", "snippet": "S"},
                {"type": "text_result", "url": "https://a.test/2", "snippet": "```c\nint x;"},
                {"type": "text_result", "title": "Three", "url": "https://a.test/3"},
            ],
        }
        with mock.patch.object(codex, "post_json", return_value=response) as post:
            data = codex.search(" query ", 2)

        post.assert_called_once_with(
            codex.SEARCH_URL,
            {
                "id": mock.ANY,
                "model": codex.MODEL,
                "commands": {"search_query": [{"q": "query"}], "response_length": "short"},
            },
            {
                "Authorization": "Bearer token",
                "chatgpt-account-id": "account",
                **codex.CLIENT_HEADERS,
            },
            "Codex",
        )
        self.assertEqual(
            data,
            {
                "query": "query",
                "results": [
                    {
                        "title": "One",
                        "url": "https://a.test/1",
                        "published_at": "",
                        "author": "",
                        "excerpt": "S",
                    },
                    {
                        "title": "Untitled",
                        "url": "https://a.test/2",
                        "published_at": "",
                        "author": "",
                        "excerpt": "```c\nint x;\n```",
                    },
                ],
            },
        )

    def test_search_prefers_output_excerpts_and_their_dates_to_snippets(self) -> None:
        rule = "-" * 80
        output = (
            "One (https://a.test/1)\n"
            f"{citation('turn0search0')} Published: 5 months ago; Crawled: today; "
            f"Long excerpt\nwith a second line {rule}\n"
            "Two (https://a.test/2)\n"
            f"{citation('turn0search1')} Crawled: today;    Indented\n{rule}\ntext\n"
        )
        response: Any = {
            "output": output,
            "results": [
                {"type": "text_result", "ref_id": "turn0search0", "url": "https://a.test/1"},
                {"type": "text_result", "ref_id": "turn0search1", "url": "https://a.test/2"},
                {"type": "text_result", "ref_id": "turn0search2", "url": "https://a.test/3"},
            ],
        }
        response["results"][0]["snippet"] = "Long"
        response["results"][2]["snippet"] = "Snippet only"
        results = codex.normalize_search(response, "query", 5)["results"]
        self.assertEqual(
            [(result["published_at"], result["excerpt"]) for result in results],
            [
                ("5 months ago", "Long excerpt\nwith a second line"),
                ("", f"Indented\n{rule}\ntext"),
                ("", "Snippet only"),
            ],
        )

    def test_fetch_continues_past_overlapping_windows_to_the_end(self) -> None:
        responses = [window(0, ["a", "b", "c"], 6), window(1, ["b", "c", "d", "e", "f"], 6)]
        with mock.patch.object(codex, "post_json", side_effect=responses) as post:
            page = codex.fetch(PAGE_URL, 100, False)

        commands = [call.args[1]["commands"] for call in post.call_args_list]
        self.assertEqual(
            commands,
            [
                {"open": [{"ref_id": PAGE_URL}]},
                {"open": [{"ref_id": PAGE_URL, "lineno": 3}]},
            ],
        )
        ids = {call.args[1]["id"] for call in post.call_args_list}
        self.assertEqual(len(ids), 1)
        self.assertEqual((page["content"], page["truncated"]), ("a\nb\nc\nd\ne\nf", False))

    def test_fetch_stops_at_the_character_limit(self) -> None:
        response = window(0, ["```", "x" * 20, "more"], 10)
        with mock.patch.object(codex, "post_json", return_value=response) as post:
            page = codex.fetch(PAGE_URL, 10, False)
        post.assert_called_once()
        self.assertEqual((page["content"], page["truncated"]), ("```\nxxxxxx\n```", True))

    def test_fetch_marks_a_page_cut_short_by_the_window_cap(self) -> None:
        responses = [window(index, [str(index)], 100) for index in range(codex.MAX_WINDOWS)]
        with mock.patch.object(codex, "post_json", side_effect=responses):
            page = codex.fetch(PAGE_URL, 10000, False)
        self.assertEqual((page["content"], page["truncated"]), ("0\n1\n2\n3\n4", True))

    def test_fetch_strips_link_markers_and_pdf_page_numbers(self) -> None:
        response = window(0, ["See 【3†the docs】 and 【7†a mirror†b.test】."], 1)
        response["output"] += "L1@P2: page two\n"
        with mock.patch.object(codex, "post_json", return_value=response):
            page = codex.fetch(PAGE_URL, 10000, False)
        self.assertEqual(page["content"], "See the docs and a mirror.\npage two")

    def test_fetch_fences_backtick_wrapped_code_blocks(self) -> None:
        lines = ["Example:", "    `int main(void)", "    {", "", "    }", "    `", "After."]
        with mock.patch.object(codex, "post_json", return_value=window(0, lines, len(lines))):
            page = codex.fetch(PAGE_URL, 10000, False)
        self.assertEqual(page["content"], "Example:\n```\nint main(void)\n{\n\n}\n```\nAfter.")

    def test_code_fence_outgrows_backtick_runs_in_the_code(self) -> None:
        lines = ["    `echo ```", "    `"]
        self.assertEqual(codex.fence_code_blocks(lines), ["````", "echo ```", "````"])

    def test_code_block_without_closing_line_stays_indented(self) -> None:
        cases = (
            ["    `int x;", "    int y;"],
            ["    `int x;", "Unindented text", "    `"],
            ["  * item", "    `inline` code in a list item"],
        )
        for lines in cases:
            with self.subTest(lines=lines):
                self.assertEqual(codex.fence_code_blocks(lines), lines)

    def test_fetch_reports_an_inaccessible_page(self) -> None:
        response = {
            "output": "Internal Error ()\nL0: URL is not accessible via this tool.",
            "results": [{"type": "text_result", "title": "Internal Error"}],
        }
        with mock.patch.object(codex, "post_json", return_value=response):
            with self.assertRaisesRegex(WebError, "Codex cannot access the page"):
                codex.fetch(PAGE_URL, 10000, False)

    def test_fetch_reports_a_page_without_text(self) -> None:
        with mock.patch.object(codex, "post_json", return_value=window(0, ["", "  "], 2)):
            with self.assertRaisesRegex(WebError, "returned no content"):
                codex.fetch(PAGE_URL, 10000, False)

    def test_fetch_reports_content_returned_only_encrypted(self) -> None:
        response = window(0, ["text"], 1)
        response["output"] = ""
        with mock.patch.object(codex, "post_json", return_value=response):
            with self.assertRaisesRegex(WebError, "no readable content"):
                codex.fetch(PAGE_URL, 10000, False)


if __name__ == "__main__":
    unittest.main()
