# hax-web

A small, dependency-free Python CLI for web search and content extraction, with a choice of
[providers](#providers).

## Requirements

- Python 3.9 or newer
- Credentials for at least one provider
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
10,000 characters and ends with a truncation note when it reaches the cap.

Queries and fetched URLs are sent to the selected provider. Do not use fetch for private,
authenticated, intranet, credential-bearing, or signed URLs.

## Providers

| Name | Credentials |
| --- | --- |
| `exa` | [Exa](https://exa.ai) API key in `EXA_API_KEY` |
| `deepseek` | [DeepSeek](https://platform.deepseek.com) API key in `DEEPSEEK_API_KEY` |
| `codex` | ChatGPT login from hax (`/login`) or the [Codex CLI](https://github.com/openai/codex) |

hax-web uses the first provider in the table whose credentials are present. Set `HAX_WEB_PROVIDER`
to choose one, or pass `--provider` to `search` or `fetch` for a single run. `./hax-web providers`
shows which providers are ready and which one is selected.

`deepseek` cannot fetch PDFs, and fetched pages lose links and code formatting; code examples on
some sites are dropped. `--fresh` has no effect.

`codex` uses the web search behind the Codex CLI, through an endpoint OpenAI does not document; it
may change or stop working without notice. hax-web never renews the login itself: when it expires,
use the codex provider in hax or run `codex` to renew it. Search results show publication dates as
ages such as "5 months ago" and omit authors. Fetched pages include the site's navigation and lose
link targets, and `--fresh` has no effect.

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
