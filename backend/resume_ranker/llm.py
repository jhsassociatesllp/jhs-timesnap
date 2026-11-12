# backend/resume_ranker/llm.py
"""
Thin OpenAI wrapper: one JSON-mode chat call, with errors sorted into
"retry later" (rate limit / timeout / 5xx) vs "give up" (bad key, bad request)
so the task queue knows which failures are worth another attempt.
"""
from __future__ import annotations

import json
import re
import threading

from backend.resume_ranker import config


class LLMError(Exception):
    """Permanent failure — retrying will not help (missing/invalid key, etc.)."""


class LLMTransientError(Exception):
    """Temporary failure — rate limit, timeout, upstream 5xx. Worth retrying."""


_client = None
_lock = threading.Lock()


def set_client(client) -> None:
    """Tests inject a fake here."""
    global _client
    _client = client


def is_configured() -> bool:
    return _client is not None or bool(config.api_key())


def get_client():
    """The shared OpenAI client (chat + embeddings both go through this
    module's key/base_url) — built lazily so importing this module never
    requires a key to already be configured."""
    global _client
    with _lock:
        if _client is None:
            key = config.api_key()
            if not key:
                raise LLMError("OpenAI API key is not configured on the server "
                               "(set RESUME_OPENAI_API_KEY in .env)")
            from openai import OpenAI
            _client = OpenAI(api_key=key, base_url=config.base_url(), timeout=90.0, max_retries=2)
        return _client


def chat_json(model: str, system: str, user: str, max_tokens: int = 2500) -> dict:
    client = get_client()
    try:
        resp = client.chat.completions.create(
            model=model,
            temperature=0,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
    except Exception as exc:
        raise classify_error(exc) from exc

    choice = resp.choices[0]
    content = choice.message.content or ""
    if choice.finish_reason == "length":
        raise LLMTransientError("Model output was cut off (too long)")
    return _loads(content)


def _loads(content: str) -> dict:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise LLMTransientError("Model returned invalid JSON")


def classify_error(exc: Exception) -> Exception:
    name = type(exc).__name__
    status = getattr(exc, "status_code", None)
    if name in ("RateLimitError", "APITimeoutError", "APIConnectionError", "InternalServerError") \
            or (isinstance(status, int) and (status == 429 or status >= 500)):
        # "insufficient_quota" arrives as a 429 but will not recover by waiting
        if "insufficient_quota" in str(exc):
            return LLMError("OpenAI quota exhausted — check billing on the API account")
        return LLMTransientError(f"{name}: {exc}")
    if name == "AuthenticationError" or status in (401, 403):
        return LLMError("OpenAI rejected the API key")
    return LLMError(f"{name}: {exc}")
