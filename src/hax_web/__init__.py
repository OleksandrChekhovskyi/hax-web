"""Search the web and fetch pages as Markdown from the shell."""

from __future__ import annotations

from typing import Final, TypedDict, Union

JsonPrimitive = Union[None, bool, int, float, str]
JsonValue = Union[JsonPrimitive, list["JsonValue"], dict[str, "JsonValue"]]
JsonObject = dict[str, JsonValue]

VERSION: Final = "0.1.0"


# Each provider module exports search() and fetch() returning these shapes; output formatting and
# --json read only them, never a provider's own response.
class SearchResult(TypedDict):
    title: str
    url: str
    published_at: str
    author: str
    excerpt: str


class SearchData(TypedDict):
    query: str
    results: list[SearchResult]


class FetchData(TypedDict):
    requested_url: str
    url: str
    title: str
    published_at: str
    author: str
    content: str
    truncated: bool


class WebError(Exception):
    pass
