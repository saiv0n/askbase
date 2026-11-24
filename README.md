# askbase

[![tests](https://github.com/saiv0n/askbase/actions/workflows/ci.yml/badge.svg)](https://github.com/saiv0n/askbase/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

A support chatbot that answers from your own documents and shows where every answer came from. Point it at a folder of help pages, PDFs or your website, then add one script tag to your site.

```html
<script src="https://help.example.com/widget.js" defer
        data-title="Help" data-color="#1f5f4a"
        data-suggestions="Where is my order?|How do returns work?"></script>
```

## Why it's different from a generic chatbot

It only answers from your documents. Each claim carries a numbered citation, and hovering a number highlights the page it came from. When the docs don't cover a question, it says so and sends the customer to a person instead of inventing a policy.

Every question is logged, and `askbase questions --unanswered` exports the ones your docs couldn't answer. That list is a to-do list for your help center.

## Features

- Reads Markdown, text, HTML and PDF files, or crawls a website and stays on that domain
- Keyword search with SQLite FTS5, no vector database to run or pay for
- Answers in the customer's language, even when the docs are in another one
- Works with Claude, OpenAI, Gemini, Groq, OpenRouter or a local model through Ollama
- Streams answers token by token
- Widget in a shadow DOM, so your site's CSS can't break it and it can't break your site. It picks up your site's font, follows light and dark mode, and goes full screen on phones
- Per visitor rate limits so nobody can run up your API bill
- One Python process, no Node build step, no database server

## Quick start

```bash
git clone https://github.com/saiv0n/askbase
cd askbase
pip install '.[claude]'          # or plain `pip install .` for the other providers

askbase ingest examples/kestrel-docs
askbase search "can I return opened coffee"   # check retrieval, no model call
```

Pick a model provider in `.env`:

```bash
# Claude
ASKBASE_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-...

# or Gemini, OpenAI, Groq, OpenRouter (any OpenAI-compatible API)
ASKBASE_PROVIDER=gemini
GEMINI_API_KEY=...
ASKBASE_MODEL=...                # `askbase models` lists what your key can use

# or a local model
ASKBASE_PROVIDER=ollama
ASKBASE_MODEL=llama3.2
```

Then:

```bash
askbase ask "When will my order ship?"
askbase serve                     # demo page at http://127.0.0.1:8000
```

The demo page is the help centre of a made up coffee roaster. Its articles live in [examples/kestrel-docs](examples/kestrel-docs), and clicking any article title asks the assistant that question.

## Your own documents

```bash
askbase ingest ./help-center ./policies.pdf
askbase ingest https://help.example.com --max-pages 300
askbase ingest ./new-faq.md --append
```

Ingesting replaces the index unless you pass `--append`. Documents are split on headings first and paragraphs second, so a passage rarely cuts a thought in half.

## Configuration

| Variable | Default | |
|---|---|---|
| `ASKBASE_PROVIDER` | `claude` | `claude`, `openai`, `gemini`, `groq`, `openrouter`, `ollama` or `custom` |
| `ASKBASE_MODEL` | `claude-opus-5-5` for Claude | required for the other providers |
| `ASKBASE_BASE_URL` | | API base for `custom`, e.g. an LM Studio server |
| `ASKBASE_API_KEY` | | overrides the provider's usual key variable |
| `ASKBASE_EFFORT` | `low` | Claude effort level; support answers rarely need more |
| `ASKBASE_COMPANY` | `our company` | how the assistant refers to you |
| `ASKBASE_FALLBACK` | | what to say when the docs don't have the answer |
| `ASKBASE_DOCS_LANGUAGE` | `English` | language of your documents, used to translate questions in other languages |
| `ASKBASE_ORIGINS` | `*` | comma separated sites allowed to embed the widget |
| `ASKBASE_RATE_MINUTE` / `ASKBASE_RATE_DAY` | `10` / `200` | questions per visitor |
| `ASKBASE_TRUST_PROXY` | | set to `1` behind nginx or Cloudflare so limits use the real visitor IP |
| `ASKBASE_DB` | `askbase.db` | index and question log |

With Claude, a declined answer is retried on a fallback model in the same request, so customers don't see a dead end.

## Widget options

All set as `data-` attributes on the script tag:

| Attribute | |
|---|---|
| `data-title` | panel title |
| `data-color`, `data-on-color` | accent color and the text color on it |
| `data-greeting` | first message |
| `data-suggestions` | up to four starter questions, separated by `\|` |
| `data-position` | `right` (default) or `left` |
| `data-theme` | `light` to ignore dark mode |
| `data-lang` | interface language, `en` or `tr`; defaults to the page language |
| `data-api` | API origin if it differs from where `widget.js` is served |
| `data-open` | `true` to start open |

The conversation survives page navigation within a tab and is cleared when the tab closes.

The page can also drive the widget, which is handy for linking FAQ entries straight to an answer:

```js
askbase.open();
askbase.ask("How do returns work?");
askbase.close();
```

## API

`POST /api/chat` with `{"messages": [{"role": "user", "content": "..."}]}` returns a server-sent event stream:

```
event: sources
data: [{"n": 1, "title": "Shipping and delivery", "heading": "Roast days and dispatch", "source": "..."}]

event: delta
data: "We roast on Monday and Thursday"

event: done
data: {"answered": true}
```

`GET /api/health` reports the number of indexed passages and the model in use.

## Deploying

Any host that runs Python works. Behind a reverse proxy, turn off response buffering for `/api/chat` so answers stream, and set `ASKBASE_TRUST_PROXY=1`.

```bash
ASKBASE_ORIGINS=https://www.example.com askbase serve --host 0.0.0.0 --port 8000
```

## Tests

```bash
uv run pytest
```

The tests run offline: ingestion and chunking, retrieval against the demo docs, the not-in-docs path, cross-language questions, both provider clients with mocked APIs, the streaming endpoint, input validation and rate limits.

## License

MIT
