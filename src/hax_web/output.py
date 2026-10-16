from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import urllib.parse
from typing import Final

from . import FetchData, SearchData, WebError
from .markdown import demote_excerpt_headings
from .text import sanitize_text

AGENT_LINE_BYTES: Final = 480


def markdown_label(value: object) -> str:
    text = " ".join(sanitize_text(value).split())
    return re.sub(r"([\\`*_\[\]<>#|])", r"\\\1", text)


def display_url(value: object) -> str:
    return urllib.parse.quote(sanitize_text(value), safe=":/?#[]@!$&'()*+,;=%")


def split_long_line(line: str, max_bytes: int) -> list[str]:
    chunks = []
    while len(line.encode()) > max_bytes:
        bytes_used = 0
        cut = 0
        for index, char in enumerate(line):
            char_bytes = len(char.encode())
            if bytes_used + char_bytes > max_bytes:
                break
            bytes_used += char_bytes
            cut = index + 1

        whitespace = max(line.rfind(" ", 0, cut), line.rfind("\t", 0, cut))
        if whitespace > 0 and len(line[:whitespace].encode()) >= max_bytes // 2:
            chunks.append(line[:whitespace])
            line = line[whitespace + 1 :]
        else:
            chunks.append(line[:cut])
            line = line[cut:]
    chunks.append(line)
    return chunks


def limit_agent_lines(value: str) -> str:
    if os.environ.get("AI_AGENT") != "hax":
        return value
    lines = []
    for line in value.splitlines():
        lines.extend(split_long_line(line, AGENT_LINE_BYTES))
    suffix = "\n" if value.endswith("\n") else ""
    return "\n".join(lines) + suffix


def auto_display_width(terminal_width: int) -> int:
    width = terminal_width if terminal_width <= 110 else 100
    return max(width, 20)


def write_markdown(value: str, no_render: bool) -> None:
    if no_render or os.environ.get("AI_AGENT") == "hax" or not sys.stdout.isatty():
        sys.stdout.write(limit_agent_lines(value))
        return

    glow = shutil.which("glow")
    if glow is None:
        sys.stdout.write(value)
        return

    terminal_width = shutil.get_terminal_size(fallback=(120, 24)).columns
    result = subprocess.run(
        [glow, "--width", str(auto_display_width(terminal_width))],
        input=value,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise WebError(f"glow exited with status {result.returncode}")


def format_search(data: SearchData) -> str:
    lines = [f"Search results: {markdown_label(data['query'])}"]
    if not data["results"]:
        lines.extend(["", "No results."])
    for index, result in enumerate(data["results"], 1):
        lines.extend(["", f"# {index}. {markdown_label(result['title'])}"])
        if result["url"]:
            lines.append(f"Source: <{display_url(result['url'])}>")
        if result["published_at"]:
            lines.append(f"Published: {markdown_label(result['published_at'])}")
        if result["author"]:
            lines.append(f"Author: {markdown_label(result['author'])}")
        if result["excerpt"]:
            lines.extend(["", demote_excerpt_headings(result["excerpt"])])
    return "\n".join(lines) + "\n"


def format_fetch(page: FetchData) -> str:
    lines = [f"# {markdown_label(page['title'])}", "", f"Source: <{display_url(page['url'])}>"]
    if page["published_at"]:
        lines.append(f"Published: {markdown_label(page['published_at'])}")
    if page["author"]:
        lines.append(f"Author: {markdown_label(page['author'])}")
    lines.extend(["", "---", "", page["content"]])
    if page["truncated"]:
        lines.extend(["", "*Content truncated at the character limit.*"])
    return "\n".join(lines) + "\n"
