from __future__ import annotations

import os
from typing import Final

from . import FetchData, JsonObject, SearchData, SearchResult, WebError
from .markdown import close_raw_block
from .text import sanitize_text
from .transport import post_json

API_BASE: Final = "https://api.exa.ai"


def post(path: str, payload: JsonObject) -> JsonObject:
    api_key = os.environ.get("EXA_API_KEY")
    if not api_key:
        raise WebError("EXA_API_KEY is not set")
    return post_json(API_BASE + path, payload, {"x-api-key": api_key}, "Exa")


def normalize_search(response: JsonObject, query: str) -> SearchData:
    raw_results = response.get("results")
    if not isinstance(raw_results, list):
        raise WebError("Exa search response did not contain results")
    results: list[SearchResult] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        highlights = item.get("highlights")
        if not isinstance(highlights, list):
            highlights = []
        fragments = (sanitize_text(x).strip() for x in highlights if isinstance(x, str))
        excerpt = "\n\n".join(close_raw_block(x) for x in fragments if x)
        results.append(
            {
                "title": sanitize_text(item.get("title")) or "Untitled",
                "url": sanitize_text(item.get("url")),
                "published_at": sanitize_text(item.get("publishedDate")),
                "author": sanitize_text(item.get("author")),
                "excerpt": excerpt,
            }
        )
    return {"query": query, "results": results}


def content_error(response: JsonObject, url: str) -> WebError:
    statuses = response.get("statuses")
    if not isinstance(statuses, list):
        statuses = []
    for status in statuses:
        if not isinstance(status, dict) or status.get("status") != "error":
            continue
        detail = status.get("error")
        if not isinstance(detail, dict):
            detail = {}
        tag = sanitize_text(detail.get("tag")) or "content unavailable"
        http_status = detail.get("httpStatusCode")
        suffix = f" (HTTP {http_status})" if isinstance(http_status, int) else ""
        return WebError(f"could not fetch {url}: {tag}{suffix}")
    return WebError(f"Exa returned no content for {url}")


def normalize_fetch(response: JsonObject, requested_url: str, max_chars: int) -> FetchData:
    results = response.get("results")
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        raise content_error(response, requested_url)
    item = results[0]
    text = item.get("text")
    content = sanitize_text(text).strip()
    if not content:
        raise content_error(response, requested_url)
    truncated = isinstance(text, str) and len(text) >= max_chars
    return {
        "requested_url": requested_url,
        "url": sanitize_text(item.get("url")) or requested_url,
        "title": sanitize_text(item.get("title")) or "Untitled",
        "published_at": sanitize_text(item.get("publishedDate")),
        "author": sanitize_text(item.get("author")),
        "content": close_raw_block(content) if truncated else content,
        "truncated": truncated,
    }


def search(query: str, limit: int) -> SearchData:
    query = query.strip()
    if not query:
        raise WebError("query must not be empty")
    response = post(
        "/search",
        {
            "query": query,
            "type": "auto",
            "numResults": limit,
            "contents": {"highlights": True},
        },
    )
    return normalize_search(response, query)


def fetch(url: str, max_chars: int, fresh: bool) -> FetchData:
    options: JsonObject = {"urls": [url], "text": {"maxCharacters": max_chars}}
    if fresh:
        options["maxAgeHours"] = 0
    response = post("/contents", options)
    return normalize_fetch(response, url, max_chars)
