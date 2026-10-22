from __future__ import annotations

import os
import re
from typing import Final, Optional

from . import FetchData, JsonObject, SearchData, SearchResult, WebError
from .markdown import close_raw_block
from .text import sanitize_text
from .transport import post_json

API_BASE: Final = "https://api.deepseek.com/v1/tools"

# Search appends chunk numbers to most result URLs, even after an existing fragment.
CHUNK_SUFFIX: Final = re.compile(r"(?:#\d+)+$")
# Fetch backslash-escapes every ASCII punctuation character, including Markdown syntax and code.
# Content is escaped this way when it escapes something Markdown never needs escaped: one of these
# characters, or a period other than one after a digit, where it keeps "1." from starting a list.
ESCAPE_ALL_MARKER: Final = re.compile(r"""\\[,;:/"'=@%?]|(?<![0-9])\\\.""")
ESCAPED_PUNCTUATION: Final = re.compile(r"\\([!-/:-@\[-`{-~])")
# Unescaping keeps the escapes on characters that would turn literal text into markup that drops
# characters: DeepSeek leaves most code outside code blocks, where __init__, #include <vector>, or a
# >>> prompt would render as emphasis, hidden HTML, or a blockquote.
KEPT_ESCAPES: Final = "\\`*_[]<>&~"
# A line-start bullet is the one such escape that hides block structure.
ESCAPED_BULLET: Final = re.compile(r"^( *)\\\*(?= )", re.M)


def unavailable() -> Optional[str]:
    return None if os.environ.get("DEEPSEEK_API_KEY") else "DEEPSEEK_API_KEY is not set"


def post(path: str, payload: JsonObject) -> JsonObject:
    reason = unavailable()
    if reason is not None:
        raise WebError(reason)
    headers = {"Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}"}
    return post_json(API_BASE + path, payload, headers, "DeepSeek")


def normalize_search(response: JsonObject, query: str) -> SearchData:
    raw_results = response.get("results")
    if not isinstance(raw_results, list):
        raise WebError("DeepSeek search response did not contain results")
    results: list[SearchResult] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        excerpt = sanitize_text(item.get("summary")).strip()
        results.append(
            {
                "title": sanitize_text(item.get("title")) or "Untitled",
                "url": CHUNK_SUFFIX.sub("", sanitize_text(item.get("url"))),
                "published_at": sanitize_text(item.get("date")),
                "author": "",
                "excerpt": close_raw_block(excerpt or sanitize_text(item.get("snippet")).strip()),
            }
        )
    return {"query": query, "results": results}


def unescape(content: str) -> str:
    if not ESCAPE_ALL_MARKER.search(content):
        return content
    content = ESCAPED_PUNCTUATION.sub(
        lambda escape: escape[0] if escape[1] in KEPT_ESCAPES else escape[1], content
    )
    return ESCAPED_BULLET.sub(r"\1*", content)


def normalize_fetch(response: JsonObject, url: str, max_chars: int) -> FetchData:
    text = unescape(sanitize_text(response.get("content"))).strip()
    if not text:
        raise WebError(f"DeepSeek returned no content for {url}")
    truncated = len(text) > max_chars
    content = text[:max_chars].rstrip()
    return {
        "requested_url": url,
        "url": url,
        "title": sanitize_text(response.get("title")) or "Untitled",
        "published_at": "",
        "author": "",
        "content": close_raw_block(content) if truncated else content,
        "truncated": truncated,
    }


def search(query: str, limit: int) -> SearchData:
    query = query.strip()
    if not query:
        raise WebError("query must not be empty")
    response = post("/search", {"query": query, "count": limit})
    return normalize_search(response, query)


def fetch(url: str, max_chars: int, fresh: bool) -> FetchData:
    """Fetch the whole page and truncate it locally: the endpoint has no length limit and no
    cache control, so `fresh` has no effect."""
    return normalize_fetch(post("/fetch", {"url": url}), url, max_chars)
