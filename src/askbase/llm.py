from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Protocol

import httpx


class LLMError(Exception):
    """Something the end user can be told about without leaking internals."""


class LLM(Protocol):
    name: str

    def stream(self, system: str, messages: list[dict]) -> Iterator[str]: ...


class OpenAICompatible:
    """Any /chat/completions endpoint: OpenAI, Gemini, Groq, OpenRouter, Ollama, LM Studio."""

    def __init__(self, base_url: str, model: str, api_key: str | None = None,
                 max_tokens: int = 1024, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.name = f"{self.base_url} / {model}"
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.client = client or httpx.Client(timeout=httpx.Timeout(60, connect=10), headers=headers)

    def stream(self, system: str, messages: list[dict]) -> Iterator[str]:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "max_tokens": self.max_tokens,
            "stream": True,
        }
        try:
            with self.client.stream("POST", f"{self.base_url}/chat/completions", json=body) as r:
                if r.status_code >= 400:
                    r.read()
                    raise LLMError(_explain(r.status_code, r.text))
                for line in r.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    choices = json.loads(data).get("choices") or []
                    if choices and (text := (choices[0].get("delta") or {}).get("content")):
                        yield text
        except httpx.TransportError as e:
            raise LLMError(f"could not reach the model provider: {e}") from e

    def models(self) -> list[str]:
        r = self.client.get(f"{self.base_url}/models")
        if r.status_code >= 400:
            raise LLMError(_explain(r.status_code, r.text))
        return sorted(m["id"] for m in r.json().get("data", []))


class Claude:
    def __init__(self, model: str = "claude-opus-5-5", effort: str = "low",
                 max_tokens: int = 4096, client=None):
        try:
            import anthropic
        except ImportError as e:
            raise SystemExit("Claude needs: pip install 'askbase[claude]'") from e
        self._anthropic = anthropic
        self.client = client or anthropic.Anthropic()
        self.model = model
        # short support answers don't benefit from deep thinking
        self.effort = effort
        self.max_tokens = max_tokens
        self.name = f"anthropic / {model}"

    def stream(self, system: str, messages: list[dict]) -> Iterator[str]:
        a = self._anthropic
        try:
            with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=messages,
                output_config={"effort": self.effort},
                # if the model declines, the API retries on a fallback model in the same call
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            ) as s:
                yield from s.text_stream
                final = s.get_final_message()
            if final.stop_reason == "refusal":
                raise LLMError("the model declined to answer this question")
        except a.AuthenticationError as e:
            raise LLMError("the Anthropic API key is missing or invalid") from e
        except a.RateLimitError as e:
            raise LLMError("the model provider is rate limiting requests, try again shortly") from e
        except a.APIStatusError as e:
            raise LLMError(f"model provider error ({e.status_code})") from e
        except a.APIConnectionError as e:
            raise LLMError("could not reach the model provider") from e


def _explain(status: int, body: str) -> str:
    if status in (401, 403):
        return "the API key is missing or invalid"
    if status == 404:
        return "model not found, check ASKBASE_MODEL (askbase models lists what is available)"
    if status == 429:
        return "the model provider is rate limiting requests, try again shortly"
    return f"model provider error ({status}): {body[:200]}"


PRESETS = {
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "ollama": ("http://localhost:11434/v1", None),
}


def from_env(env: dict | None = None) -> LLM:
    """Pick a provider from ASKBASE_PROVIDER, ASKBASE_MODEL and the provider's usual key variable."""
    env = os.environ if env is None else env
    provider = env.get("ASKBASE_PROVIDER", "claude").lower()
    model = env.get("ASKBASE_MODEL")
    if provider == "claude":
        return Claude(model=model or "claude-opus-5-5", effort=env.get("ASKBASE_EFFORT", "low"))
    if provider in PRESETS:
        base, key_var = PRESETS[provider]
    elif provider == "custom":
        base, key_var = env.get("ASKBASE_BASE_URL", ""), None
        if not base:
            raise SystemExit("ASKBASE_PROVIDER=custom needs ASKBASE_BASE_URL")
    else:
        raise SystemExit(f"unknown ASKBASE_PROVIDER {provider!r}; use claude, custom or one of {', '.join(PRESETS)}")
    if not model:
        raise SystemExit(f"set ASKBASE_MODEL for {provider} (askbase models lists the options)")
    key = env.get("ASKBASE_API_KEY") or (env.get(key_var) if key_var else None)
    return OpenAICompatible(base, model, key)
