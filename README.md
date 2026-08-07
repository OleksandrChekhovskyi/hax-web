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
10,000 characters by Exa.

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

## License

[MIT](LICENSE)
