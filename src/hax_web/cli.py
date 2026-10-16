from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Optional

from . import VERSION, WebError, exa
from .output import format_fetch, format_search, write_markdown
from .urls import validate_public_url


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
    if args.command == "search":
        data = exa.search(args.query, args.limit)
        rendered = (
            json.dumps(data, ensure_ascii=False, indent=2) if args.json else format_search(data)
        )
    else:
        url = validate_public_url(args.url)
        data = exa.fetch(url, args.max_chars, args.fresh)
        rendered = (
            json.dumps(data, ensure_ascii=False, indent=2) if args.json else format_fetch(data)
        )
    output = rendered if rendered.endswith("\n") else rendered + "\n"
    if args.json:
        sys.stdout.write(output)
    else:
        write_markdown(output, args.no_render)


def run() -> None:
    try:
        main()
    except WebError as error:
        print(f"hax-web: {error}", file=sys.stderr)
        raise SystemExit(1)
    except BrokenPipeError:
        raise SystemExit(0)
