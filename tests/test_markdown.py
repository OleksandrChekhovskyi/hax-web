from __future__ import annotations

import unittest

import support  # noqa: F401
from hax_web import markdown


class RawBlockTests(unittest.TestCase):
    def test_closes_unterminated_raw_blocks(self) -> None:
        for value, closer in (
            ("```python\ncode", "```"),
            ("````\ncode\n```", "````"),
            ("~~~\ncode\n```", "~~~"),
            ("<!-- note", "-->"),
            ("<PRE class=x>\ncode", "</PRE>"),
            ("<script>\nlet x;\n</style", "</script>"),
            ("<?php echo 1;", "?>"),
            ("<!DOCTYPE html", ">"),
            ("<![CDATA[ data", "]]>"),
            ("- ```\n  code\n```", "```"),
            ("<div>\n\n```\ncode", "```"),
            ("- Install and\nrun this:\n\n  ```sh\n  pip install foo", "  ```"),
        ):
            with self.subTest(value=value):
                self.assertEqual(markdown.close_raw_block(value), value + "\n" + closer)

    def test_leaves_terminated_and_non_raw_blocks_unchanged(self) -> None:
        for value in (
            "```\ncode\n```",
            "~~~~\ncode\n~~~~~  ",
            "```inline` span",
            "    ```",
            "<!-- one line -->",
            "<pre>code</PRE>",
            "<div>\ntext",
            "<!--\n```\n-->",
            "- ```python\n  print(1)\n  ```",
            "- a\n\n  ```\n  code\n  ```\n- b",
            "> ```\n> code",
            "- ```python\n  print(1)",
            "- a\n  - <!-- note",
            "Paragraph\n2. ```\n   code",
            "<div>\n```\n</div>\n\nText",
            "<details>\n<summary>More</summary>\n```",
        ):
            with self.subTest(value=value):
                self.assertEqual(markdown.close_raw_block(value), value)

    def test_every_truncation_point_is_closed(self) -> None:
        document = (
            "# Title\n\nText with `code`.\n\n```c\nint x;\n```\n\n"
            "<!--\ncomment\n-->\n\n~~~~\n```\n~~~~\n\n<pre>\nx\n</pre>\n\n"
            "1. Step\n\n   ```sh\n   run\n   ```\n- ```\n  code\n  ```\n"
        )
        for cut in range(len(document) + 1):
            closed = markdown.close_raw_block(document[:cut])
            with self.subTest(cut=cut):
                self.assertIsNone(markdown.scan_raw_blocks(closed.splitlines())[1])


class HeadingTests(unittest.TestCase):
    def test_excerpt_headings_are_unchanged_without_h1(self) -> None:
        excerpt = "## Source heading\n\n### Detail"
        self.assertEqual(markdown.demote_excerpt_headings(excerpt), excerpt)

    def test_excerpt_headings_inside_list_code_are_unchanged(self) -> None:
        excerpt = "# Heading\n\n- ```sh\n  # comment\n  ```\n\n# Next"
        self.assertEqual(
            markdown.demote_excerpt_headings(excerpt),
            "## Heading\n\n- ```sh\n  # comment\n  ```\n\n## Next",
        )

    def test_excerpt_headings_inside_html_blocks_are_unchanged(self) -> None:
        excerpt = "# Heading\n\n<pre>\n# shell prompt\n</pre>"
        self.assertEqual(
            markdown.demote_excerpt_headings(excerpt),
            "## Heading\n\n<pre>\n# shell prompt\n</pre>",
        )


if __name__ == "__main__":
    unittest.main()
