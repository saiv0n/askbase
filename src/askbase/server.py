from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import defaultdict, deque
from importlib.resources import files

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from .answer import Event, Settings, answer
from .index import Index
from .llm import LLM, LLMError

log = logging.getLogger(__name__)
STATIC = files("askbase") / "static"


class Message(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1, max_length=40)


class RateLimiter:
    """Per-client sliding window, so one visitor can't run up the API bill."""

    def __init__(self, per_minute: int, per_day: int):
        self.limits = [(60, per_minute), (86400, per_day)]
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > 86400:
                q.popleft()
            for window, limit in self.limits:
                if limit and sum(1 for t in q if now - t <= window) >= limit:
                    return False
            q.append(now)
            return True


def _sse(event: Event) -> str:
    return f"event: {event.type}\ndata: {json.dumps(event.data, ensure_ascii=False)}\n\n"


def create_app(index: Index, llm: LLM, settings: Settings | None = None,
               origins: list[str] | None = None, per_minute: int = 10, per_day: int = 200,
               trust_proxy: bool = False) -> FastAPI:
    settings = settings or Settings()
    limiter = RateLimiter(per_minute, per_day)
    app = FastAPI(title="askbase", docs_url=None, redoc_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=origins or ["*"],
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    @app.get("/api/health")
    def health():
        return {"ok": True, "chunks": index.count(), "model": llm.name}

    @app.post("/api/chat")
    def chat(req: ChatRequest, request: Request):
        if req.messages[-1].role != "user":
            raise HTTPException(400, "the last message must be from the user")
        client = request.client.host if request.client else "?"
        # the header is trivially forged, so only believe it behind our own proxy
        if trust_proxy and (fwd := request.headers.get("x-forwarded-for")):
            client = fwd.split(",")[0].strip()
        if not limiter.allow(client):
            raise HTTPException(429, "too many questions, please wait a minute")
        msgs = [m.model_dump() for m in req.messages]

        def events():
            try:
                for ev in answer(msgs, index, llm, settings):
                    yield _sse(ev)
            except LLMError as e:
                log.warning("llm error: %s", e)
                yield _sse(Event("error", "Sorry, the assistant is unavailable right now. Please try again."))
            except Exception:
                log.exception("chat failed")
                yield _sse(Event("error", "Sorry, something went wrong. Please try again."))

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/widget.js")
    def widget():
        return FileResponse(str(STATIC / "widget.js"), media_type="application/javascript",
                            headers={"Cache-Control": "public, max-age=300"})

    @app.get("/", response_class=HTMLResponse)
    def demo():
        return (STATIC / "demo.html").read_text(encoding="utf-8")

    return app


def app_from_env():
    """Entry point for uvicorn --factory, configured from environment variables."""
    from .llm import from_env

    index = Index(os.environ.get("ASKBASE_DB", "askbase.db"))
    s = Settings.from_env()
    origins = [o.strip() for o in os.environ.get("ASKBASE_ORIGINS", "*").split(",") if o.strip()]
    return create_app(index, from_env(), s, origins,
                      per_minute=int(os.environ.get("ASKBASE_RATE_MINUTE", 10)),
                      per_day=int(os.environ.get("ASKBASE_RATE_DAY", 200)),
                      trust_proxy=os.environ.get("ASKBASE_TRUST_PROXY") == "1")
