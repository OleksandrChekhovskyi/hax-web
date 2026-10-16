from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, NamedTuple, Optional


class RawBlock(NamedTuple):
    """A fenced code or HTML block, whose lines are not Markdown until one matches `end`."""

    end: re.Pattern[str]
    closer: str


@dataclass
class Container:
    """The document or a list item, whose lines continue at `indent` columns or deeper."""

    indent: int
    block: Optional[RawBlock] = None


FENCE_START: Final = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")
LIST_MARKER: Final = re.compile(r" {0,3}(?:[-+*]|[0-9]{1,9}[.)])(?= |$)")


HTML_BLOCK_TAGS: Final = (
    "address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|"
    "details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|"
    "h[1-6]|head|header|hr|html|iframe|legend|li|link|main|menu|menuitem|nav|noframes|ol|"
    "optgroup|option|p|param|search|section|summary|table|tbody|td|tfoot|th|thead|title|tr|"
    "track|ul"
)


HTML_BLOCKS: Final = (
    (
        re.compile(r" {0,3}<(pre|script|style|textarea)(?=[ \t>]|$)", re.I),
        re.compile(r"</(?:pre|script|style|textarea)>", re.I),
        r"</\1>",
    ),
    (re.compile(r" {0,3}<!--"), re.compile("-->"), "-->"),
    (re.compile(r" {0,3}<\?"), re.compile(r"\?>"), "?>"),
    (re.compile(r" {0,3}<![A-Za-z]"), re.compile(">"), ">"),
    (re.compile(r" {0,3}<!\[CDATA\["), re.compile(r"\]\]>"), "]]>"),
    (
        re.compile(rf" {{0,3}}</?(?:{HTML_BLOCK_TAGS})(?=[ \t>]|/>|$)", re.I),
        re.compile(r"^[ \t]*$"),
        "",
    ),
)


def open_raw_block(line: str) -> Optional[RawBlock]:
    # A closer at the opener's indentation also closes the block when it is really inside a list
    # item that lazy continuation kept open.
    indent = line[: len(line) - len(line.lstrip(" "))]
    fence = FENCE_START.match(line)
    if fence is not None:
        marker, info = fence.groups()
        if marker[0] == "`" and "`" in info:
            return None
        end = re.compile(rf"^ {{0,3}}{marker[0]}{{{len(marker)},}}[ \t]*$")
        return RawBlock(end, indent + marker)
    for start, end, closer in HTML_BLOCKS:
        html = start.match(line)
        if html is None:
            continue
        if end.search(line):
            return None
        closer = html.expand(closer)
        return RawBlock(end, indent + closer if closer else "")
    return None


def list_item_indent(line: str) -> int:
    marker = LIST_MARKER.match(line)
    if marker is None:
        return 0
    text = line[marker.end() :]
    spaces = len(text) - len(text.lstrip(" "))
    return marker.end() + (spaces if 1 <= spaces <= 4 and text.strip() else 1)


def scan_raw_blocks(lines: Sequence[str]) -> tuple[list[bool], Optional[str]]:
    """Flag lines inside raw blocks and return the line that closes a block left open, if any.

    A list item, with any raw block in it, ends at a nonblank line indented less than its content,
    so only top-level blocks need a closer. Keep it that way: list detection ignores paragraph
    interruption and lazy continuation, and a closer for a misdetected block would open one.
    """
    in_raw = []
    containers = [Container(0)]
    for line in lines:
        line = line.expandtabs(4)
        if line.strip():
            indent = len(line) - len(line.lstrip(" "))
            while indent < containers[-1].indent:
                containers.pop()
        container = containers[-1]
        content = line[container.indent :]
        if container.block is not None:
            in_raw.append(True)
            if container.block.end.search(content):
                container.block = None
            continue
        item_indent = list_item_indent(content)
        while item_indent:
            container = Container(container.indent + item_indent)
            containers.append(container)
            content = content[item_indent:]
            item_indent = list_item_indent(content)
        container.block = open_raw_block(content)
        in_raw.append(container.block is not None)

    block = containers[0].block if len(containers) == 1 else None
    return in_raw, block.closer if block is not None and block.closer else None


def close_raw_block(value: str) -> str:
    closer = scan_raw_blocks(value.splitlines())[1]
    return value if closer is None else value + "\n" + closer


def demote_excerpt_headings(value: str) -> str:
    lines = value.splitlines(keepends=True)
    in_raw = scan_raw_blocks(lines)[0]
    headings = []
    for index, (line, raw) in enumerate(zip(lines, in_raw)):
        heading = re.match(r"^ {0,3}(#{1,6})(?=[ \t]|$)", line)
        if heading is not None and not raw:
            headings.append((index, heading.start(1), heading.end(1)))

    if not any(end - start == 1 for _, start, end in headings):
        return value
    for index, start, end in headings:
        if end - start < 6:
            lines[index] = lines[index][:start] + "#" + lines[index][start:]
    return "".join(lines)
