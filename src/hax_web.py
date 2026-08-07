#!/usr/bin/env python3

from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from typing import Final, Optional, TypedDict, Union, cast

JsonPrimitive = Union[None, bool, int, float, str]
JsonValue = Union[JsonPrimitive, list["JsonValue"], dict[str, "JsonValue"]]
JsonObject = dict[str, JsonValue]

AGENT_LINE_BYTES: Final = 480
API_BASE: Final = "https://api.exa.ai"
MAX_RESPONSE_BYTES: Final = 2 * 1024 * 1024
RETRY_STATUSES: Final = {429, 500, 502, 503, 504}
TRANSPORT_ERRORS: Final = (urllib.error.URLError, http.client.HTTPException, OSError)
VERSION: Final = "0.1.0"


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


class WebError(Exception):
    pass


def sanitize_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(
        char
        for char in value
        if char in "\n\t"
        or (
            ord(char) >= 32
            and not 127 <= ord(char) <= 159
            and not 0xD800 <= ord(char) <= 0xDFFF
        )
    )


def markdown_label(value: object) -> str:
    text = " ".join(sanitize_text(value).split())
    return re.sub(r"([\\`*_\[\]<>#|])", r"\\\1", text)


def display_url(value: object) -> str:
    return urllib.parse.quote(sanitize_text(value), safe=":/?#[]@!$&'()*+,;=%")


def truncate(value: object, max_chars: int) -> str:
    value = sanitize_text(value).strip()
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip() + "\n\n[truncated]"


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


def looks_like_ipv4(host: str) -> bool:
    parts = host.split(".")
    if not 1 <= len(parts) <= 4:
        return False
    number = re.compile(r"(?:0[xX][0-9a-fA-F]+|0[0-7]*|[1-9][0-9]*)")
    return all(number.fullmatch(part) is not None for part in parts)


def validate_public_url(value: str) -> str:
    try:
        url = urllib.parse.urlsplit(value)
        port = url.port
    except ValueError as error:
        raise WebError(f"invalid URL: {error}") from error
    if url.scheme.lower() not in {"http", "https"} or not url.hostname:
        raise WebError("URL must use http:// or https:// and include a host")
    if url.username is not None or url.password is not None:
        raise WebError("URL must not contain embedded credentials")
    if port is not None and not 1 <= port <= 65535:
        raise WebError("URL port is out of range")

    host = url.hostname.lower()
    if "%" in host:
        raise WebError("URL host must not contain percent-encoding")
    try:
        host = host.encode("idna").decode("ascii").rstrip(".")
    except UnicodeError as error:
        raise WebError(f"invalid URL host: {error}") from error

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        if not address.is_global or address.is_multicast:
            raise WebError("refusing to send a local or private URL to Exa")
    elif looks_like_ipv4(host):
        raise WebError("refusing to send an ambiguous IPv4 URL to Exa")
    elif "." not in host or host.endswith((".local", ".internal", ".localhost")):
        raise WebError("refusing to send a local or private URL to Exa")
    return value


def retry_delay(error: urllib.error.HTTPError, attempt: int) -> float:
    fallback = 2**attempt
    value = error.headers.get("Retry-After") if error.headers else None
    if value is None:
        return fallback
    try:
        delay = float(value)
    except ValueError:
        return fallback
    if not math.isfinite(delay):
        return fallback
    return min(max(delay, 0), 10)


def api_error_message(body: bytes, status: int) -> str:
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = None
    if isinstance(data, dict):
        detail = data.get("message") or data.get("error") or data.get("detail")
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("tag")
        if isinstance(detail, str) and detail:
            return sanitize_text(detail)
    return f"Exa returned HTTP {status}"


def post_json(path: str, payload: JsonObject, api_key: str) -> JsonObject:
    body = json.dumps(payload, separators=(",", ":")).encode()
    request = urllib.request.Request(
        API_BASE + path,
        data=body,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Content-Type": "application/json",
            "User-Agent": f"hax-web/{VERSION}",
            "x-api-key": api_key,
        },
        method="POST",
    )

    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise WebError("Exa response exceeded 2 MiB")
                try:
                    data = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError) as error:
                    raise WebError("Exa returned invalid JSON") from error
                if not isinstance(data, dict):
                    raise WebError("Exa returned an unexpected response")
                return cast(JsonObject, data)
        except urllib.error.HTTPError as error:
            if error.code in RETRY_STATUSES and attempt < 2:
                time.sleep(retry_delay(error, attempt))
                continue
            try:
                raw = error.read(64 * 1024)
            except TRANSPORT_ERRORS:
                raw = b""
            raise WebError(api_error_message(raw, error.code)) from error
        except TRANSPORT_ERRORS as error:
            if attempt < 2:
                time.sleep(2**attempt)
                continue
            reason = error.reason if isinstance(error, urllib.error.URLError) else error
            raise WebError(f"could not reach Exa: {sanitize_text(str(reason))}") from error
    raise WebError("could not reach Exa")


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
        excerpt = truncate("\n\n".join(x for x in highlights if isinstance(x, str)), 1200)
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


def normalize_fetch(
    response: JsonObject, requested_url: str, max_chars: int
) -> FetchData:
    results = response.get("results")
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        raise content_error(response, requested_url)
    item = results[0]
    content = truncate(item.get("text"), max_chars)
    if not content:
        raise content_error(response, requested_url)
    return {
        "requested_url": requested_url,
        "url": sanitize_text(item.get("url")) or requested_url,
        "title": sanitize_text(item.get("title")) or "Untitled",
        "published_at": sanitize_text(item.get("publishedDate")),
        "author": sanitize_text(item.get("author")),
        "content": content,
    }


def search(api_key: str, query: str, limit: int) -> SearchData:
    query = query.strip()
    if not query:
        raise WebError("query must not be empty")
    response = post_json(
        "/search",
        {
            "query": query,
            "type": "auto",
            "numResults": limit,
            "contents": {"highlights": True},
        },
        api_key,
    )
    return normalize_search(response, query)


def fetch(api_key: str, url: str, max_chars: int, fresh: bool) -> FetchData:
    options: JsonObject = {"urls": [url], "text": {"maxCharacters": max_chars}}
    if fresh:
        options["maxAgeHours"] = 0
    response = post_json("/contents", options, api_key)
    return normalize_fetch(response, url, max_chars)


def format_search(data: SearchData) -> str:
    lines = [f"# Search results: {markdown_label(data['query'])}"]
    if not data["results"]:
        lines.extend(["", "No results."])
    for index, result in enumerate(data["results"], 1):
        lines.extend(["", f"## {index}. {markdown_label(result['title'])}"])
        if result["url"]:
            lines.append(f"Source: <{display_url(result['url'])}>")
        if result["published_at"]:
            lines.append(f"Published: {markdown_label(result['published_at'])}")
        if result["author"]:
            lines.append(f"Author: {markdown_label(result['author'])}")
        if result["excerpt"]:
            lines.extend(["", result["excerpt"]])
    return "\n".join(lines) + "\n"


def format_fetch(page: FetchData) -> str:
    lines = [f"# {markdown_label(page['title'])}", "", f"Source: <{display_url(page['url'])}>"]
    if page["published_at"]:
        lines.append(f"Published: {markdown_label(page['published_at'])}")
    if page["author"]:
        lines.append(f"Author: {markdown_label(page['author'])}")
    lines.extend(["", "---", "", page["content"]])
    return "\n".join(lines) + "\n"


def positive_int(value: str, maximum: int) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if not 1 <= number <= maximum:
        raise argparse.ArgumentTypeError(f"must be between 1 and {maximum}")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hax-web", description="Search and fetch the web via Exa."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    commands = parser.add_subparsers(dest="command", required=True)

    search_parser = commands.add_parser("search", help="search the web")
    search_parser.add_argument("query")
    search_parser.add_argument(
        "-n", "--limit", type=lambda value: positive_int(value, 20), default=5
    )
    search_parser.add_argument("--json", action="store_true", help="write normalized JSON")
    search_parser.add_argument("--no-render", action="store_true", help="do not invoke glow")

    fetch_parser = commands.add_parser("fetch", help="fetch a URL as Markdown")
    fetch_parser.add_argument("url")
    fetch_parser.add_argument(
        "--max-chars", type=lambda value: positive_int(value, 10000), default=10000
    )
    fetch_parser.add_argument("--fresh", action="store_true", help="request a live crawl")
    fetch_parser.add_argument("--json", action="store_true", help="write normalized JSON")
    fetch_parser.add_argument("--no-render", action="store_true", help="do not invoke glow")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    api_key = os.environ.get("EXA_API_KEY")
    if not api_key:
        raise WebError("EXA_API_KEY is not set")

    if args.command == "search":
        data = search(api_key, args.query, args.limit)
        rendered = (
            json.dumps(data, ensure_ascii=False, indent=2) if args.json else format_search(data)
        )
    else:
        url = validate_public_url(args.url)
        data = fetch(api_key, url, args.max_chars, args.fresh)
        rendered = (
            json.dumps(data, ensure_ascii=False, indent=2) if args.json else format_fetch(data)
        )
    output = rendered if rendered.endswith("\n") else rendered + "\n"
    if args.json:
        sys.stdout.write(output)
    else:
        write_markdown(output, args.no_render)


if __name__ == "__main__":
    try:
        main()
    except WebError as error:
        print(f"hax-web: {error}", file=sys.stderr)
        raise SystemExit(1)
    except BrokenPipeError:
        raise SystemExit(0)
