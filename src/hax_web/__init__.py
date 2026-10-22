"""Search the web and fetch pages as Markdown from the shell."""

from __future__ import annotations

from typing import Final, Optional, Protocol, TypedDict, Union

JsonPrimitive = Union[None, bool, int, float, str]
JsonValue = Union[JsonPrimitive, list["JsonValue"], dict[str, "JsonValue"]]
JsonObject = dict[str, JsonValue]

VERSION: Final = "0.1.0"


# Providers return these shapes; output formatting and --json read only them, never a provider's
# own response.
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


class Provider(Protocol):
    """A provider module: one per service, registered in `providers.PROVIDERS`, with `exa` as the
    reference. Providers read their own credentials, send requests through `transport.post_json`,
    and use only the standard library."""

    def search(self, query: str, limit: int) -> SearchData: ...

    def fetch(self, url: str, max_chars: int, fresh: bool) -> FetchData: ...

    def unavailable(self) -> Optional[str]:
        """Why the provider cannot run, such as missing credentials, or None when it can."""
        ...
