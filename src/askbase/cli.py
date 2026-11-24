from __future__ import annotations

import argparse
import csv
import logging
import os
import re
import sys
from pathlib import Path

from . import __version__
from .answer import Settings, answer
from .index import Index
from .llm import LLMError
from .ingest import chunk, load_path, load_urls


def _load_dotenv(path: str = ".env"):
    # tiny .env reader so keys never have to be typed on the command line
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def cmd_ingest(args) -> int:
    index = Index(args.db)
    if not args.append:
        index.clear()
    docs = []
    for src in args.sources:
        if src.startswith(("http://", "https://")):
            docs += load_urls([src], max_pages=args.max_pages)
        else:
            docs += load_path(src)
    chunks = [c for d in docs for c in chunk(d)]
    index.add(chunks)
    print(f"indexed {len(docs)} documents as {len(chunks)} chunks into {args.db}")
    return 0 if chunks else 1


def cmd_search(args) -> int:
    for h in Index(args.db).search(args.question, k=args.k):
        print(f"{h.score:6.2f}  {h.title} > {h.heading}  ({h.source})")
        print("        " + h.text[:160].replace("\n", " ") + "...")
    return 0


def cmd_ask(args) -> int:
    from .llm import from_env

    s = Settings.from_env()
    sources, text = [], ""
    try:
        for ev in answer([{"role": "user", "content": args.question}], Index(args.db), from_env(), s):
            if ev.type == "sources":
                sources = ev.data
            elif ev.type == "delta":
                text += ev.data
                print(ev.data, end="", flush=True)
    except LLMError as e:
        print(f"\nerror: {e}", file=sys.stderr)
        return 1
    print()
    cited = {int(n) for n in re.findall(r"\[(\d{1,2})\]", text)}
    for src in (s for s in sources if s["n"] in cited):
        print(f"  [{src['n']}] {src['title']} > {src['heading']}  {src['source']}")
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    os.environ["ASKBASE_DB"] = args.db
    uvicorn.run("askbase.server:app_from_env", factory=True, host=args.host, port=args.port)
    return 0


def cmd_questions(args) -> int:
    rows = Index(args.db).questions(unanswered_only=args.unanswered)
    w = csv.writer(sys.stdout)
    w.writerow(["asked_at", "question", "answered", "top_source"])
    w.writerows(rows)
    return 0


def cmd_models(args) -> int:
    from .llm import OpenAICompatible, from_env

    os.environ.setdefault("ASKBASE_MODEL", "x")
    llm = from_env()
    if not isinstance(llm, OpenAICompatible):
        print("model listing works for OpenAI-compatible providers; for Claude see the Anthropic docs")
        return 1
    print("\n".join(llm.models()))
    return 0


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    p = argparse.ArgumentParser(prog="askbase")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--db", default=os.environ.get("ASKBASE_DB", "askbase.db"))
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("ingest", help="index files, folders (md, txt, html, pdf) or a website")
    i.add_argument("sources", nargs="+")
    i.add_argument("--append", action="store_true", help="keep what is already indexed")
    i.add_argument("--max-pages", type=int, default=200)
    i.set_defaults(func=cmd_ingest)

    s = sub.add_parser("search", help="show which passages a question retrieves, no model call")
    s.add_argument("question")
    s.add_argument("-k", type=int, default=5)
    s.set_defaults(func=cmd_search)

    a = sub.add_parser("ask", help="answer one question in the terminal")
    a.add_argument("question")
    a.set_defaults(func=cmd_ask)

    v = sub.add_parser("serve", help="run the chat API and widget")
    v.add_argument("--host", default="127.0.0.1")
    v.add_argument("--port", type=int, default=8000)
    v.set_defaults(func=cmd_serve)

    q = sub.add_parser("questions", help="export asked questions as CSV")
    q.add_argument("--unanswered", action="store_true", help="only the ones the docs couldn't answer")
    q.set_defaults(func=cmd_questions)

    m = sub.add_parser("models", help="list models of the configured provider")
    m.set_defaults(func=cmd_models)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
