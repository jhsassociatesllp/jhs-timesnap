"""
LLM wrapper — auto-switches between HuggingFace and any OpenAI-compatible API.

How to switch providers (only change .env, no code changes needed):

  Using HuggingFace (current):
    HF_API_KEY=hf_xxxxxxxxxxxx
    HF_MODEL=deepseek-ai/DeepSeek-V4-Flash      (optional, has default)
    HF_BASE_URL=https://router.huggingface.co/v1 (optional, has default)

  Switching to OpenAI / any other API later:
    # Comment out or remove HF_API_KEY, then add:
    LLM_API_KEY=sk-xxxxxxxxxxxx
    LLM_MODEL=gpt-4o-mini                        (optional, has default)
    LLM_BASE_URL=https://api.openai.com/v1        (optional, has default)

The config.py detects which key is set and exposes ACTIVE_API_KEY,
ACTIVE_BASE_URL, ACTIVE_MODEL — used by default when no `provider` override
is passed. A caller that needs a DIFFERENT, independent provider (e.g. the
HR bot deliberately uses its own OpenAI key — see rag.py's HR_PROVIDER —
without switching RCM/the general assistant off the shared one above) can
pass `provider={"base_url":..., "api_key":..., "model":..., "name":...}`
to override just that call.
"""
from typing import Dict, Generator, List, Optional, TypedDict
import json
import requests

from backend.chatbot.config import chatbot_settings

TIMEOUT_SECONDS = 45


class ProviderOverride(TypedDict, total=False):
    base_url: str
    api_key: str
    model: str
    name: str  # label used only in error messages, e.g. "openai (hr)"
    bot: str   # 'hr' | 'rcm' — attributes usage.py's call tracking; omit to skip tracking


def _resolve(provider: Optional[ProviderOverride]):
    if provider:
        return (
            provider["base_url"],
            provider["api_key"],
            provider["model"],
            provider.get("name", "custom"),
        )
    return (
        chatbot_settings.ACTIVE_BASE_URL,
        chatbot_settings.ACTIVE_API_KEY,
        chatbot_settings.ACTIVE_MODEL,
        chatbot_settings.LLM_PROVIDER,
    )


def _track_usage(provider: Optional[ProviderOverride], model: str = None, usage_block: dict = None) -> None:
    bot = (provider or {}).get("bot")
    if not bot:
        return
    from backend.chatbot import usage
    usage_block = usage_block or {}
    usage.record_call(
        bot,
        model=model,
        prompt_tokens=usage_block.get("prompt_tokens", 0),
        completion_tokens=usage_block.get("completion_tokens", 0),
    )


def _raise_for_status(resp: requests.Response, provider_name: str) -> None:
    if resp.status_code == 401:
        raise RuntimeError(
            f"{provider_name} API rejected the token (401). Check its API key in .env. "
            + ("Make sure the HuggingFace token has 'Make calls to Inference Providers' permission."
               if provider_name == "huggingface" else "")
        )
    if resp.status_code == 429:
        raise RuntimeError(
            f"Rate limit / quota hit (429) on {provider_name}. Try again shortly."
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"{provider_name} API error {resp.status_code}: {resp.text[:500]}")


def stream_llm(
    messages: List[Dict[str, str]], temperature: float = 0.2, provider: Optional[ProviderOverride] = None
) -> Generator[str, None, None]:
    """
    Same contract as call_llm, but yields the answer as it's generated instead
    of waiting for the whole thing. This is what makes the chat feel fast: the
    employee sees the first words almost immediately instead of staring at a
    typing indicator for the entire generation time.
    """
    base_url, api_key, model, provider_name = _resolve(provider)
    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        # 1600, not 800: a low cap was cutting off answers mid-list on
        # multi-part questions (role-by-role HR breakdowns, multi-control RCM
        # answers) before they reached their own "Sources:" line.
        "max_tokens": 1600,
        "stream": True,
    }

    try:
        resp = requests.post(
            url, headers=headers, json=payload, timeout=TIMEOUT_SECONDS, stream=True
        )
    except requests.RequestException as e:
        raise RuntimeError(f"Could not reach {provider_name} API: {e}")

    _raise_for_status(resp, provider_name)
    _track_usage(provider)

    for line in resp.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data:"):
            continue
        data = line[len("data:"):].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue
        choices = chunk.get("choices") or []
        if not choices:
            continue
        content = choices[0].get("delta", {}).get("content")
        if content:
            yield content


def call_llm(
    messages: List[Dict[str, str]], temperature: float = 0.2, provider: Optional[ProviderOverride] = None
) -> str:
    """
    messages: standard OpenAI-style [{role: system/user/assistant, content: ...}]
    Returns the assistant reply text.
    Raises RuntimeError with a clear message on any API failure.
    """
    base_url, api_key, model, provider_name = _resolve(provider)
    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        # 1600, not 800: a low cap was cutting off answers mid-list on
        # multi-part questions (role-by-role HR breakdowns, multi-control RCM
        # answers) before they reached their own "Sources:" line.
        "max_tokens": 1600,
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as e:
        raise RuntimeError(f"Could not reach {provider_name} API: {e}")

    _raise_for_status(resp, provider_name)

    try:
        data = resp.json()
    except ValueError as e:
        # Still record that the call happened (no token counts available)
        # before raising — a 2xx response with a malformed body is still a
        # real, billed call, and this used to be tracked unconditionally
        # before usage.py grew token/cost tracking that needs the parsed
        # body; only the (rare) failure-to-parse path should ever miss it.
        _track_usage(provider, model=model, usage_block=None)
        raise RuntimeError(f"Invalid JSON from {provider_name} API: {e}") from e

    _track_usage(provider, model=model, usage_block=data.get("usage"))
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected {provider_name} API response shape: {data}") from e
