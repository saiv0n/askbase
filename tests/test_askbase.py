import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from askbase import cli
from askbase.answer import NOT_FOUND, Settings, answer, search_text
from askbase.index import Index, to_query
from askbase.ingest import Doc, _html_to_text, chunk, load_path, load_urls
from askbase.llm import Claude, LLMError, OpenAICompatible, from_env
from askbase.server import RateLimiter, create_app

DOCS = Path(__file__).parents[1] / "examples" / "kestrel-docs"


@pytest.fixture
def index(tmp_path):
    ix = Index(tmp_path / "t.db")
    ix.add([c for d in load_path(DOCS) for c in chunk(d)])
    return ix


class FakeLLM:
    name = "fake"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def stream(self, system, messages):
        self.calls.append((system, messages))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        # stream in awkward pieces, like real providers do
        for i in range(0, len(reply), 3):
            yield reply[i:i + 3]


def run(messages, index, llm, s=None):
    events = list(answer(messages, index, llm, s or Settings(company="Kestrel")))
    text = "".join(e.data for e in events if e.type == "delta")
    return events, text


# ingest and chunking

def test_load_docs_uses_first_heading_as_title():
    docs = {Path(d.source).name: d for d in load_path(DOCS)}
    assert len(docs) == 8
    assert docs["shipping.md"].title == "Shipping and delivery"


def test_chunks_follow_headings_and_respect_size():
    doc = Doc("x.md", "Guide", "# Guide\n\n## One\n\n" + ("word " * 400) + "\n\n## Two\n\nshort")
    chunks = chunk(doc, size=600, overlap=50)
    assert {c.heading for c in chunks} == {"One", "Two"}
    assert all(len(c.text) <= 600 for c in chunks)
    assert chunks[-1].text == "short"


def test_html_is_cleaned_and_keeps_headings():
    title, text = _html_to_text(
        "<html><head><title>FAQ</title><script>x()</script></head><body><nav>menu</nav>"
        "<main><h2>Returns</h2><p>Within 30 days.</p><ul><li>one</li><li>two</li></ul></main></body></html>")
    assert title == "FAQ"
    assert "## Returns" in text and "Within 30 days." in text and "- one" in text
    assert "menu" not in text and "x()" not in text


@respx.mock
def test_crawl_stays_on_site():
    respx.get("https://docs.test/").respond(200, html=(
        '<title>Home</title><main><p>Welcome</p><a href="/faq">faq</a>'
        '<a href="https://elsewhere.test/x">out</a><a href="/logo.png">img</a></main>'))
    respx.get("https://docs.test/faq").respond(200, html="<title>FAQ</title><main><p>Answers</p></main>")
    docs = load_urls(["https://docs.test/"])
    assert [d.title for d in docs] == ["Home", "FAQ"]


# retrieval

def test_query_building():
    assert to_query("How do refunds work?") == '"refun"* OR "work"*'
    assert to_query("the and of") == ""
    assert '"kargo"*' in to_query("Kargom ne zaman gelir?") or '"karg"*' in to_query("Kargom ne zaman gelir?")


@pytest.mark.parametrize("question,expected", [
    ("When will my order ship?", "shipping.md"),
    ("how do I pause my subscription", "subscriptions.md"),
    ("can I return an opened bag of coffee", "returns.md"),
    ("what grind for french press", "grind-and-brewing.md"),
    ("is the decaf caffeine free", "coffees.md"),
    ("I forgot my password", "account-and-payment.md"),
    ("do you sell to cafes", "wholesale.md"),
])
def test_search_finds_the_right_page(index, question, expected):
    hits = index.search(question, k=3)
    assert hits and Path(hits[0].source).name == expected


def test_search_text_includes_previous_question():
    msgs = [{"role": "user", "content": "shipping to the EU"},
            {"role": "assistant", "content": "..."},
            {"role": "user", "content": "and how long does it take?"}]
    assert search_text(msgs) == "shipping to the EU and how long does it take?"


# answering

def test_answer_streams_with_sources_and_logs(index):
    llm = FakeLLM("We roast on Monday and Thursday [1].")
    events, text = run([{"role": "user", "content": "When do you roast?"}], index, llm)
    assert [e.type for e in events][0] == "sources"
    assert text == "We roast on Monday and Thursday [1]."
    assert events[-1].data == {"answered": True}
    system, msgs = llm.calls[0]
    assert "Kestrel" in system and "[1]" in system and NOT_FOUND in system
    assert msgs == [{"role": "user", "content": "When do you roast?"}]
    assert index.questions() and index.questions()[0][2] == 1


@pytest.mark.parametrize("reply,shown", [
    (NOT_FOUND, "Please contact support."),
    (f"  {NOT_FOUND}.", "Please contact support."),
    (f"{NOT_FOUND}\n\nLütfen destekle iletişime geçin.", "Lütfen destekle iletişime geçin."),
])
def test_not_found_marker_never_reaches_the_user(index, reply, shown):
    s = Settings(company="Kestrel", fallback="Please contact support.")
    events, text = run([{"role": "user", "content": "Do you sell tea from Japan?"}], index, FakeLLM(reply), s)
    assert text == shown
    assert NOT_FOUND not in text
    assert events[-1].data == {"answered": False}
    assert index.questions(unanswered_only=True)[0][1] == "Do you sell tea from Japan?"


def test_answer_that_starts_like_the_marker_is_kept(index):
    _, text = run([{"role": "user", "content": "What about shipping?"}], index, FakeLLM("NOTE: shipping is free [1]."))
    assert text == "NOTE: shipping is free [1]."


def test_no_hits_even_after_rewrite_gives_fallback(index):
    llm = FakeLLM("xyzzy plugh")
    events, text = run([{"role": "user", "content": "zzzz qqqq"}], index, llm, Settings(fallback="Ask a human."))
    assert text == "Ask a human."
    assert len(llm.calls) == 1  # only the keyword rewrite, no answer call


def test_other_language_question_is_rewritten_then_answered(index):
    llm = FakeLLM("return refund opened coffee", "Evet, açılmış kahveyi 30 gün içinde iade edebilirsiniz [1].")
    events, text = run([{"role": "user", "content": "Açılmış kahveyi iade edebilir miyim?"}], index, llm)
    assert text.startswith("Evet")
    rewrite_system, _ = llm.calls[0]
    assert "English search keywords" in rewrite_system
    sources = next(e.data for e in events if e.type == "sources")
    assert Path(sources[0]["source"]).name == "returns.md"


def test_history_is_trimmed(index):
    msgs = []
    for i in range(10):
        msgs += [{"role": "user", "content": f"shipping question {i}"}, {"role": "assistant", "content": "ok"}]
    msgs.append({"role": "user", "content": "shipping to Canada?"})
    llm = FakeLLM("5 to 9 working days [1].")
    run(msgs, index, llm, Settings(history=4))
    assert len(llm.calls[0][1]) == 4


# providers

@respx.mock
def test_openai_compatible_stream():
    sse = "".join(f"data: {json.dumps({'choices': [{'delta': {'content': p}}]})}\n\n" for p in ["Hel", "lo"])
    sse += 'data: {"choices": []}\n\ndata: [DONE]\n\n'
    route = respx.post("https://llm.test/v1/chat/completions").respond(200, text=sse)
    llm = OpenAICompatible("https://llm.test/v1/", "m1", api_key="k")
    assert "".join(llm.stream("sys", [{"role": "user", "content": "hi"}])) == "Hello"
    body = json.loads(route.calls[0].request.content)
    assert body["model"] == "m1" and body["stream"] is True
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    assert route.calls[0].request.headers["authorization"] == "Bearer k"


@respx.mock
@pytest.mark.parametrize("status,needle", [(401, "API key"), (404, "model not found"), (429, "rate limiting")])
def test_openai_compatible_errors(status, needle):
    respx.post("https://llm.test/v1/chat/completions").respond(status, text="nope")
    with pytest.raises(LLMError, match=needle):
        list(OpenAICompatible("https://llm.test/v1", "m", retries=1).stream("s", []))


@respx.mock
def test_cut_off_stream_is_an_error():
    cut = 'data: {"choices": [{"delta": {"content": "You can ret"}}]}\n\n'
    respx.post("https://llm.test/v1/chat/completions").respond(200, text=cut)
    with pytest.raises(LLMError, match="cut off"):
        list(OpenAICompatible("https://llm.test/v1", "m").stream("s", []))


@respx.mock
def test_error_inside_stream_is_raised():
    respx.post("https://llm.test/v1/chat/completions").respond(200, text='data: {"error": {"code": 503}}\n\n')
    with pytest.raises(LLMError, match="provider error"):
        list(OpenAICompatible("https://llm.test/v1", "m").stream("s", []))


@respx.mock
def test_finish_reason_without_done_is_complete():
    ok = 'data: {"choices": [{"delta": {"content": "Done."}, "finish_reason": "stop"}]}\n\n'
    respx.post("https://llm.test/v1/chat/completions").respond(200, text=ok)
    assert "".join(OpenAICompatible("https://llm.test/v1", "m").stream("s", [])) == "Done."


@respx.mock
def test_openai_compatible_retries_busy_provider(monkeypatch):
    monkeypatch.setattr("askbase.llm.time.sleep", lambda s: None)
    ok = 'data: {"choices": [{"delta": {"content": "hi"}}]}\n\ndata: [DONE]\n\n'
    route = respx.post("https://llm.test/v1/chat/completions").mock(side_effect=[
        httpx.Response(503, text="busy"), httpx.Response(429, headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}),
        httpx.Response(200, text=ok)])
    assert "".join(OpenAICompatible("https://llm.test/v1", "m").stream("s", [])) == "hi"
    assert route.call_count == 3
    body = json.loads(route.calls[0].request.content)
    assert body["temperature"] == 0.2


@respx.mock
def test_openai_compatible_gives_up_after_retries(monkeypatch):
    monkeypatch.setattr("askbase.llm.time.sleep", lambda s: None)
    respx.post("https://llm.test/v1/chat/completions").respond(503, text="busy")
    with pytest.raises(LLMError, match="busy or down"):
        list(OpenAICompatible("https://llm.test/v1", "m", retries=2).stream("s", []))


def test_claude_provider_uses_sdk_stream():
    seen = {}

    class Stream:
        text_stream = iter(["Roast ", "days [1]."])

        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get_final_message(self): return SimpleNamespace(stop_reason="end_turn")

    def stream(**kw):
        seen.update(kw)
        return Stream()

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)))
    llm = Claude(client=client)
    assert "".join(llm.stream("sys", [{"role": "user", "content": "q"}])) == "Roast days [1]."
    assert seen["model"] == "claude-opus-5-5"
    assert seen["system"] == "sys"
    assert seen["output_config"] == {"effort": "low"}
    assert seen["fallbacks"] == "default"


def test_claude_refusal_becomes_llm_error():
    class Stream:
        text_stream = iter([])
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get_final_message(self): return SimpleNamespace(stop_reason="refusal")

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: Stream())))
    with pytest.raises(LLMError, match="declined"):
        list(Claude(client=client).stream("s", [{"role": "user", "content": "q"}]))


def test_from_env():
    llm = from_env({"ASKBASE_PROVIDER": "gemini", "ASKBASE_MODEL": "g1", "GEMINI_API_KEY": "abc"})
    assert isinstance(llm, OpenAICompatible)
    assert llm.base_url.startswith("https://generativelanguage.googleapis.com")
    assert llm.client.headers["authorization"] == "Bearer abc"
    with pytest.raises(SystemExit, match="ASKBASE_MODEL"):
        from_env({"ASKBASE_PROVIDER": "groq"})
    with pytest.raises(SystemExit, match="unknown"):
        from_env({"ASKBASE_PROVIDER": "nope"})


# server

def _events(body: str):
    out = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_chat_endpoint_streams_sse(index):
    app = create_app(index, FakeLLM("Monday and Thursday [1]."), Settings(company="Kestrel"))
    c = TestClient(app)
    r = c.post("/api/chat", json={"messages": [{"role": "user", "content": "When do you roast?"}]})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    ev = _events(r.text)
    assert ev[0][0] == "sources" and ev[-1] == ("done", {"answered": True})
    assert "".join(d for t, d in ev if t == "delta") == "Monday and Thursday [1]."


def test_chat_endpoint_hides_provider_errors(index):
    app = create_app(index, FakeLLM(LLMError("secret internal detail")))
    r = TestClient(app).post("/api/chat", json={"messages": [{"role": "user", "content": "shipping?"}]})
    ev = _events(r.text)
    assert ev[-1][0] == "error" and "secret" not in r.text


def test_chat_endpoint_validates(index):
    c = TestClient(create_app(index, FakeLLM()))
    assert c.post("/api/chat", json={"messages": []}).status_code == 422
    assert c.post("/api/chat", json={"messages": [{"role": "system", "content": "x"}]}).status_code == 422
    assert c.post("/api/chat", json={"messages": [{"role": "assistant", "content": "x"}]}).status_code == 400


def test_rate_limit(index):
    c = TestClient(create_app(index, FakeLLM(*["ok [1]"] * 5), per_minute=2))
    q = {"messages": [{"role": "user", "content": "shipping?"}]}
    assert [c.post("/api/chat", json=q).status_code for _ in range(3)] == [200, 200, 429]


def test_rate_limit_ignores_forged_forwarded_header(index):
    c = TestClient(create_app(index, FakeLLM(*["ok [1]"] * 5), per_minute=1))
    q = {"messages": [{"role": "user", "content": "shipping?"}]}
    codes = [c.post("/api/chat", json=q, headers={"x-forwarded-for": f"10.0.0.{i}"}).status_code for i in range(2)]
    assert codes == [200, 429]


def test_rate_limiter_daily_window():
    rl = RateLimiter(per_minute=0, per_day=2)
    assert [rl.allow("a"), rl.allow("a"), rl.allow("a"), rl.allow("b")] == [True, True, False, True]


def test_widget_and_demo_are_served(index):
    c = TestClient(create_app(index, FakeLLM()))
    w = c.get("/widget.js")
    assert w.status_code == 200 and "attachShadow" in w.text
    assert "widget.js" in c.get("/").text
    assert c.get("/api/health").json()["chunks"] == index.count()


# cli

def test_cli_ingest_search_and_questions(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "c.db")
    assert cli.main(["--db", db, "ingest", str(DOCS)]) == 0
    assert "indexed 8 documents" in capsys.readouterr().out
    assert cli.main(["--db", db, "search", "refund opened coffee"]) == 0
    assert "Returns and refunds" in capsys.readouterr().out
    Index(db).log_question("tea?", False, None)
    assert cli.main(["--db", db, "questions", "--unanswered"]) == 0
    assert "tea?" in capsys.readouterr().out
