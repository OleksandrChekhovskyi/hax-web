from __future__ import annotations

import base64
import json
import os
import pathlib
import re
import time
import uuid
from typing import Final, NamedTuple, Optional

from . import VERSION, FetchData, JsonObject, SearchData, SearchResult, WebError
from .markdown import close_raw_block
from .text import sanitize_text
from .transport import post_json

# The standalone search endpoint behind the Codex CLI's web tool. It is undocumented, so the shapes
# handled here are the ones it has been observed to return.
SEARCH_URL: Final = "https://chatgpt.com/backend-api/codex/alpha/search"

# Required by the endpoint, which does not validate it.
MODEL: Final = "gpt-6-luna"

# chatgpt.com's bot filter rejects clients that do not identify as the Codex CLI.
CLIENT_HEADERS: Final = {
    "originator": "codex_cli_rs",
    "User-Agent": f"codex_cli_rs/0.144.1 hax-web/{VERSION}",
}

# Each open returns a window of about 150-270 page lines, so a 10,000-character fetch rarely needs a
# second; the cap bounds pages whose windows come back nearly empty.
MAX_WINDOWS: Final = 5

# The model-facing output holds one block per search result: a title line, then a line citing the
# result's ref_id with metadata fields ahead of the excerpt:
#   \ue200cite\ue202turn0search3\ue201 [wordlim: 200] Published: 5 months ago; Crawled: today; text
# Blocks are separated by a rule of dashes that need not start a line, so a split also checks that
# a citation follows; a rule inside an excerpt is kept.
RESULT_SEPARATOR: Final = re.compile(r"\s*-{80}\n(?=[^\n]*\n\ue200cite\ue202)")
CITATION: Final = re.compile(r"\ue200cite\ue202([^\ue201]+)\ue201(?: \[wordlim: \d+\])? ?")
METADATA_FIELD: Final = re.compile(r"(Published|Crawled): ([^;\n]*); ")

# PDF lines carry their page number: L12@P3.
PAGE_LINE: Final = re.compile(r"^L(\d+)(?:@P\d+)?: ?(.*)$", re.M)
TOTAL_LINES: Final = re.compile(r"Total lines: (\d+)")
# 【id†text】 or 【id†text†domain】: a numbered link the browser tool would follow by id.
LINK: Final = re.compile(r"【\d+†([^†】]*)[^】]*】")
# Page code blocks come back indented and wrapped in a stray pair of backticks: the first line
# starts with one, and a line holding only the indent and a backtick closes the block.
CODE_OPENER: Final = re.compile(r"( {4,})`(.+)")


class Credentials(NamedTuple):
    access_token: str
    account_id: str
    renew_hint: str


def state_home() -> pathlib.Path:
    value = os.environ.get("XDG_STATE_HOME", "")
    return pathlib.Path(value) if os.path.isabs(value) else pathlib.Path.home() / ".local/state"


def codex_home() -> pathlib.Path:
    value = os.environ.get("CODEX_HOME", "")
    return pathlib.Path(value) if value else pathlib.Path.home() / ".codex"


def read_json(path: pathlib.Path) -> Optional[JsonObject]:
    try:
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        raise WebError(f"could not read {path}: {error}") from error
    return data if isinstance(data, dict) else None


def credentials_from(entry: object, renew_hint: str) -> Optional[Credentials]:
    if not isinstance(entry, dict):
        return None
    access_token = entry.get("access_token")
    account_id = entry.get("account_id")
    if not isinstance(access_token, str) or not isinstance(account_id, str):
        return None
    if not access_token or not account_id:
        return None
    return Credentials(access_token, account_id, renew_hint)


def token_expired(token: str) -> bool:
    """Read the JWT's exp claim unverified; a token without a readable one is left to the server."""
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return float(claims["exp"]) <= time.time() + 60
    except (IndexError, KeyError, TypeError, ValueError):
        return False


def load_credentials() -> Credentials:
    """Borrow the ChatGPT login from hax, else from the Codex CLI, without ever refreshing it.

    Refresh tokens rotate on use, so refreshing here would sign the owning client out. An expired
    token is reported for that client to renew instead.
    """
    hax_store = read_json(state_home() / "hax/auth.json")
    hax_entry = hax_store.get("codex") if hax_store else None
    credentials = credentials_from(hax_entry, "use hax's codex provider")
    if credentials is None:
        codex_auth = read_json(codex_home() / "auth.json")
        tokens = codex_auth.get("tokens") if codex_auth else None
        credentials = credentials_from(tokens, "run codex")
    if credentials is None:
        raise WebError("no ChatGPT login found; sign in with hax's /login or the Codex CLI")
    if token_expired(credentials.access_token):
        raise WebError(f"the ChatGPT login has expired; {credentials.renew_hint} to renew it")
    return credentials


def unavailable() -> Optional[str]:
    try:
        load_credentials()
    except WebError as error:
        return str(error)
    return None


def post(session_id: str, commands: JsonObject) -> JsonObject:
    credentials = load_credentials()
    headers = {
        "Authorization": f"Bearer {credentials.access_token}",
        "chatgpt-account-id": credentials.account_id,
        **CLIENT_HEADERS,
    }
    payload: JsonObject = {"id": session_id, "model": MODEL, "commands": commands}
    return post_json(SEARCH_URL, payload, headers, "Codex")


class Excerpt(NamedTuple):
    published: str
    text: str


def parse_excerpts(output: str) -> dict[str, Excerpt]:
    """Map ref_ids to the excerpts the model-facing output gives them, which run far longer than
    the structured results' snippets."""
    excerpts = {}
    for block in RESULT_SEPARATOR.split(output):
        citation = CITATION.search(block)
        if citation is None:
            continue
        text = block[citation.end() :]
        fields = {}
        while (field := METADATA_FIELD.match(text)) is not None:
            fields[field[1]] = field[2]
            text = text[field.end() :]
        excerpts[citation[1]] = Excerpt(fields.get("Published", ""), text.strip())
    return excerpts


def normalize_search(response: JsonObject, query: str, limit: int) -> SearchData:
    excerpts = parse_excerpts(sanitize_text(response.get("output")))
    raw_results = response.get("results")
    if not isinstance(raw_results, list):
        raise WebError("Codex search response did not contain results")
    results: list[SearchResult] = []
    for item in raw_results:
        if len(results) == limit:
            break
        if not isinstance(item, dict) or item.get("type") != "text_result":
            continue
        url = sanitize_text(item.get("url"))
        if not url:
            continue
        excerpt = excerpts.get(sanitize_text(item.get("ref_id")))
        text = excerpt.text if excerpt else ""
        results.append(
            {
                "title": sanitize_text(item.get("title")) or "Untitled",
                "url": url,
                "published_at": excerpt.published if excerpt else "",
                "author": "",
                "excerpt": close_raw_block(text or sanitize_text(item.get("snippet")).strip()),
            }
        )
    return {"query": query, "results": results}


class Window(NamedTuple):
    """One open: the page's metadata and a numbered slice of its text lines."""

    title: str
    url: str
    lines: list[tuple[int, str]]
    total_lines: int


def parse_window(response: JsonObject, requested_url: str) -> Window:
    results = response.get("results")
    page = results[0] if isinstance(results, list) and results else None
    if not isinstance(page, dict):
        page = {}
    url = sanitize_text(page.get("url"))
    # A page the backend cannot open comes back as a URL-less "Internal Error" result.
    if not url:
        raise WebError(f"could not fetch {requested_url}: Codex cannot access the page")
    output = sanitize_text(response.get("output"))
    if not output.strip():
        raise WebError(f"Codex returned no readable content for {requested_url}")
    lines = [(int(match[1]), LINK.sub(r"\1", match[2])) for match in PAGE_LINE.finditer(output)]
    total = TOTAL_LINES.search(output)
    return Window(
        title=sanitize_text(page.get("title")) or "Untitled",
        url=url,
        lines=lines,
        total_lines=int(total[1]) if total else (lines[-1][0] + 1 if lines else 0),
    )


def search(query: str, limit: int) -> SearchData:
    query = query.strip()
    if not query:
        raise WebError("query must not be empty")
    # Longer response lengths only lengthen the top results' excerpts, which already run to
    # thousands of characters at "short".
    commands: JsonObject = {"search_query": [{"q": query}], "response_length": "short"}
    response = post(str(uuid.uuid4()), commands)
    return normalize_search(response, query, limit)


def code_block_end(lines: list[str], start: int, indent: str) -> Optional[int]:
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.rstrip() == indent + "`":
            return index
        if line.strip() and not line.startswith(indent):
            return None
    return None


def fence_code_blocks(lines: list[str]) -> list[str]:
    """Rewrite the backend's backtick-wrapped indented code blocks as fenced ones, which otherwise
    render with literal backticks. A block whose closing line was cut off stays indented, which
    still ends at the next unindented line."""
    fenced: list[str] = []
    index = 0
    while index < len(lines):
        opener = CODE_OPENER.fullmatch(lines[index])
        end = code_block_end(lines, index, opener[1]) if opener else None
        if opener is None or end is None:
            fenced.append(lines[index])
            index += 1
            continue
        indent = len(opener[1])
        code = [opener[2]] + [line[indent:] for line in lines[index + 1 : end]]
        longest_run = max((len(run) for line in code for run in re.findall("`+", line)), default=0)
        fence = "`" * max(3, longest_run + 1)
        fenced.extend([fence, *code, fence])
        index = end + 1
    return fenced


def open_window(session_id: str, url: str, lineno: int) -> Window:
    operation: JsonObject = {"ref_id": url}
    if lineno:
        operation["lineno"] = lineno
    return parse_window(post(session_id, {"open": [operation]}), url)


def fetch(url: str, max_chars: int, fresh: bool) -> FetchData:
    """Open `url` window by window until `max_chars` or the page's end.

    `fresh` is accepted for interface parity: the endpoint's cache settings showed no effect on what
    open returns.
    """
    session_id = str(uuid.uuid4())
    window = open_window(session_id, url, 0)
    page_lines: list[str] = []
    chars = 0
    next_line = 0
    for opened in range(1, MAX_WINDOWS + 1):
        # Windows overlap: one opened at a line starts some lines before it.
        new_lines = [text for number, text in window.lines if number >= next_line]
        if not new_lines:
            break
        page_lines.extend(new_lines)
        chars += sum(len(text) + 1 for text in new_lines)
        next_line = window.lines[-1][0] + 1
        if chars >= max_chars or next_line >= window.total_lines or opened == MAX_WINDOWS:
            break
        window = open_window(session_id, url, next_line)

    content = "\n".join(fence_code_blocks(page_lines)).strip()
    if not content:
        raise WebError(f"Codex returned no content for {url}")
    truncated = len(content) > max_chars or next_line < window.total_lines
    content = content[:max_chars].rstrip()
    return {
        "requested_url": url,
        "url": window.url,
        "title": window.title,
        "published_at": "",
        "author": "",
        "content": close_raw_block(content) if truncated else content,
        "truncated": truncated,
    }
