# hax-web

A small, dependency-free Python CLI for web search and content extraction. The first provider is
[Exa](https://exa.ai).

## Requirements

- Python 3.9 or newer
- `EXA_API_KEY` in the environment
- Optional: [`glow`](https://github.com/charmbracelet/glow) for interactive rendering

## Usage

```sh
./hax-web search "C23 constexpr changes"
./hax-web search -n 10 "recent Linux io_uring changes"
./hax-web fetch "https://example.com/article"
./hax-web fetch --fresh --max-chars 5000 "https://example.com/article"
```

On a terminal, Markdown is rendered with `glow` when available; `--no-render` disables it. Piped or
redirected output stays raw Markdown, and errors go to stderr. Both commands accept `--json` for
normalized JSON output. Search returns up to five results by default; fetch output is capped at
10,000 characters by Exa and ends with a truncation note when it reaches the cap. Code blocks and
raw HTML blocks that a cut leaves open are closed, so they cannot swallow the rest of the output.

Queries and fetched URLs are sent to Exa. Do not use fetch for private, authenticated, intranet,
credential-bearing, or signed URLs.

## Source installation

Clone the repository somewhere it will not be moved, then run:

```sh
./install.sh
```

The installer links `hax-web` into `~/.local/bin` and the skill into hax's XDG configuration
directory. It is safe to rerun and refuses to replace existing paths. Restart hax after installing
the skill.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

## Adding a provider

Providers live in `src/hax_web/`, one module each, with `exa.py` as the reference. A provider
exports `search(query, limit)` and `fetch(url, max_chars, fresh)`, which return the `SearchData`
and `FetchData` shapes defined in `__init__.py`; reads its own API key from the environment; and
sends requests through `transport.post_json`. Keep it standard-library only, and test it in
`tests/test_<provider>.py`. Exa is the only provider so far, so `cli.py` calls it directly; the
second provider adds the choice between them there.

## License

[MIT](LICENSE)
