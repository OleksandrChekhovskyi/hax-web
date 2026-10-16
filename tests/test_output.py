from __future__ import annotations

import io
import os
import unittest
from unittest import mock

import support  # noqa: F401
from hax_web import FetchData, SearchData, output


class TtyBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


class OutputTests(unittest.TestCase):
    def test_auto_display_width_matches_hax(self) -> None:
        self.assertEqual(output.auto_display_width(19), 20)
        self.assertEqual(output.auto_display_width(100), 100)
        self.assertEqual(output.auto_display_width(110), 110)
        self.assertEqual(output.auto_display_width(111), 100)

    def test_direct_output_is_unchanged(self) -> None:
        value = "word " * 120
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(output.limit_agent_lines(value), value)

    def test_hax_output_stays_below_line_cap(self) -> None:
        value = "word " * 300 + "\n" + "é" * 300 + "\n"
        with mock.patch.dict(os.environ, {"AI_AGENT": "hax"}):
            rendered = output.limit_agent_lines(value)
        self.assertTrue(rendered.endswith("\n"))
        self.assertTrue(
            all(len(line.encode()) <= output.AGENT_LINE_BYTES for line in rendered.splitlines())
        )

    def test_tty_output_uses_glow(self) -> None:
        stdout = TtyBuffer()
        completed = mock.Mock(returncode=0)
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch("sys.stdout", stdout):
                with mock.patch.object(output.shutil, "which", return_value="/bin/glow"):
                    with mock.patch.object(
                        output.shutil, "get_terminal_size", return_value=os.terminal_size((105, 24))
                    ):
                        run_patch = mock.patch.object(
                            output.subprocess, "run", return_value=completed
                        )
                        with run_patch as run:
                            output.write_markdown("# Heading\n", False)
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
                with mock.patch.object(output.shutil, "which") as which:
                    output.write_markdown("# Heading\n", True)
        which.assert_not_called()
        self.assertEqual(stdout.getvalue(), "# Heading\n")


class FormatTests(unittest.TestCase):
    def test_markdown_escapes_labels_and_strips_terminal_controls(self) -> None:
        data: SearchData = {
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
        rendered = output.format_search(data)
        self.assertNotIn("\x1b", rendered)
        self.assertIn(r"a \# query", rendered)
        self.assertIn(r"\*title\*", rendered)
        self.assertIn("https://example.com/a%20b", rendered)
        self.assertIn("\nUseful text\n", rendered)

    def test_search_demotes_excerpt_headings_below_result_titles(self) -> None:
        data: SearchData = {
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
        rendered = output.format_search(data)
        self.assertTrue(rendered.startswith("Search results: query\n"))
        self.assertIn("\n# 1. Result\n", rendered)
        self.assertIn("\n### Earlier\n\n## Source heading\n\n#### Detail\n", rendered)
        self.assertIn("```python\n# code comment\n```", rendered)
        self.assertIn("\n###### Deep\n", rendered)

    def test_markdown_metadata_cannot_add_lines(self) -> None:
        data: SearchData = {
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
        rendered = output.format_search(data)
        self.assertIn("Search results: real \\#\\# forged\n", rendered)
        self.assertIn("# 1. Title --- 1. forged\n", rendered)
        self.assertIn(
            "Source: <https://example.com/a%20b%0ASource:%20%3Chttps://evil.test%3E>\n",
            rendered,
        )
        self.assertIn("Published: 2026 \\#\\# forged\n", rendered)
        self.assertIn("Author: Alice Source: forged\n", rendered)

    def test_truncated_page_ends_with_a_note(self) -> None:
        page: FetchData = {
            "requested_url": "https://a.test",
            "url": "https://a.test",
            "title": "Page",
            "published_at": "",
            "author": "",
            "content": "```\ncode\n```",
            "truncated": True,
        }
        self.assertTrue(
            output.format_fetch(page).endswith(
                "```\ncode\n```\n\n*Content truncated at the character limit.*\n"
            )
        )
        page["truncated"] = False
        self.assertNotIn("Content truncated", output.format_fetch(page))


if __name__ == "__main__":
    unittest.main()
