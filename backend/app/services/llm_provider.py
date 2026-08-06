"""
Chat/insights LLM provider abstraction: Gemini or any OpenAI-compatible
endpoint (local llama.cpp/llama-swap, vLLM, LM Studio, etc.), switched via
LLM_PROVIDER in .env — without touching any of the call sites that already
speak the google-genai SDK's shapes (ai_coach.py, analysis_cache.py,
memory.py all call `client.models.generate_content(model=, contents=,
config=)` and read Gemini-shaped responses).

get_llm_client() returns either the real genai.Client or a thin shim
(_OpenAICompatClient) exposing the same `.models.generate_content(...)` call
signature, translating to/from OpenAI's chat.completions API under the
hood. The response objects it returns are plain Python objects that satisfy
the same getattr()-based access patterns every consumer already uses
(candidates[0].content.parts[i].text/.function_call/.thought, response.text,
candidates[0].grounding_metadata) — nothing downstream needs to know which
provider actually served the request. Verified against a real llama-swap
endpoint (gemma-4 26B): tool calling round-trips correctly, including
`reasoning_content`, which is mapped to a thought=True part so it's stripped
the same way Gemini's own thinking output already is.

Known, accepted gaps versus real Gemini when LLM_PROVIDER=openai:
- No Google Search grounding tool (Gemini-proprietary; simply dropped from
  the translated tool list — see _gemini_tools_to_openai — so
  _extract_grounding_sources() naturally returns [] instead of erroring).
- No embeddings — GEMINI_EMBEDDING_MODEL / memory RAG retrieval always uses
  the real Gemini client regardless of LLM_PROVIDER.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

from google import genai
from google.genai import types

from app.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Duck-typed response objects
# ---------------------------------------------------------------------------

class _FakeFunctionCall:
    def __init__(self, name: str, args: dict[str, Any]):
        self.name = name
        self.args = args


class _FakePart:
    def __init__(self, *, text: str | None = None, function_call: _FakeFunctionCall | None = None, thought: bool = False):
        self.text = text
        self.function_call = function_call
        self.function_response = None  # a *response* part never carries one
        self.thought = thought


class _FakeContent:
    def __init__(self, parts: list[_FakePart], role: str = "model"):
        self.parts = parts
        self.role = role


class _FakeCandidate:
    def __init__(self, content: _FakeContent):
        self.content = content
        self.grounding_metadata = None  # no grounding support for OpenAI-compatible backends


class _FakeResponse:
    def __init__(self, candidates: list[_FakeCandidate], text: str):
        self.candidates = candidates
        self.text = text


def _wrap_chat_completion(resp: Any) -> _FakeResponse:
    choice = resp.choices[0]
    msg = choice.message
    parts: list[_FakePart] = []

    reasoning = getattr(msg, "reasoning_content", None)
    if reasoning:
        parts.append(_FakePart(text=reasoning, thought=True))

    for tc in getattr(msg, "tool_calls", None) or []:
        raw_args = getattr(tc.function, "arguments", None) or "{}"
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
        except (json.JSONDecodeError, TypeError):
            # Don't log raw_args — tool-call arguments are model-generated
            # from the athlete's own message/conversation content (workout
            # notes, race goals, etc.) and can carry PII; log only what's
            # needed to diagnose a malformed-arguments issue.
            logger.warning(
                "[llm_provider] failed to parse tool_call arguments as JSON for %r (%d chars)",
                getattr(tc.function, "name", "?"),
                len(raw_args) if isinstance(raw_args, str) else -1,
            )
            args = {}
        parts.append(_FakePart(function_call=_FakeFunctionCall(tc.function.name, args)))

    content_text = getattr(msg, "content", None) or ""
    if content_text:
        parts.append(_FakePart(text=content_text))

    return _FakeResponse([_FakeCandidate(_FakeContent(parts))], text=content_text)


# ---------------------------------------------------------------------------
# Request-side translation: Gemini's contents/config -> OpenAI messages/tools
# ---------------------------------------------------------------------------

def _lowercase_schema_types(node: Any) -> Any:
    """Gemini's Schema.model_dump() emits `"type": "OBJECT"/"STRING"/...`
    (Gemini's own enum casing); standard JSON Schema — what every
    OpenAI-compatible server expects — uses lowercase."""
    if isinstance(node, dict):
        return {
            k: (v.lower() if k == "type" and isinstance(v, str) else _lowercase_schema_types(v))
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [_lowercase_schema_types(v) for v in node]
    return node


def _gemini_tools_to_openai(tools: list[types.Tool] | None) -> list[dict] | None:
    if not tools:
        return None
    out: list[dict] = []
    for tool in tools:
        decls = getattr(tool, "function_declarations", None)
        if not decls:
            continue  # e.g. google_search — no OpenAI-compatible equivalent, dropped
        for decl in decls:
            spec = decl.model_dump(exclude_none=True, mode="json")
            params = _lowercase_schema_types(
                spec.get("parameters") or {"type": "object", "properties": {}}
            )
            out.append({
                "type": "function",
                "function": {
                    "name": spec["name"],
                    "description": spec.get("description", ""),
                    "parameters": params,
                },
            })
    return out or None


def _gemini_contents_to_openai_messages(
    contents: str | list[types.Content],
    system_instruction: str | None,
) -> list[dict]:
    messages: list[dict] = []
    if system_instruction:
        messages.append({"role": "system", "content": str(system_instruction)})

    if isinstance(contents, str):
        messages.append({"role": "user", "content": contents})
        return messages

    # Multi-turn agentic history: a "model" turn with function_call parts is
    # always immediately followed by a "user" turn carrying the matching
    # function_response parts, in the same order — that's exactly what
    # ai_coach.py's agentic loop builds. tool_call_id is generated
    # positionally here since Gemini's FunctionCall doesn't carry one; the
    # very next turn's function_response parts are paired up the same way,
    # tracked via `pending_ids` rather than by mutating either object.
    call_id_seq = 0
    pending_ids: list[str] | None = None

    for content in contents:
        role = getattr(content, "role", "user")
        parts = list(getattr(content, "parts", None) or [])
        fcs = [p.function_call for p in parts if getattr(p, "function_call", None) is not None]
        frs = [p.function_response for p in parts if getattr(p, "function_response", None) is not None]
        text = "\n".join(p.text for p in parts if getattr(p, "text", None))

        if fcs:
            tool_calls = []
            ids: list[str] = []
            for fc in fcs:
                call_id_seq += 1
                cid = f"call_{call_id_seq}"
                ids.append(cid)
                args = fc.args if isinstance(fc.args, dict) else {}
                tool_calls.append({
                    "id": cid,
                    "type": "function",
                    "function": {"name": fc.name, "arguments": json.dumps(args)},
                })
            messages.append({"role": "assistant", "content": text or None, "tool_calls": tool_calls})
            pending_ids = ids
            continue

        if frs and pending_ids and len(frs) == len(pending_ids):
            for cid, fr in zip(pending_ids, frs):
                payload = getattr(fr, "response", None)
                try:
                    payload_text = json.dumps(payload) if payload is not None else "{}"
                except TypeError:
                    payload_text = str(payload)
                messages.append({"role": "tool", "tool_call_id": cid, "content": payload_text})
            pending_ids = None
            continue

        pending_ids = None
        if text:
            messages.append({"role": "assistant" if role == "model" else "user", "content": text})

    return messages


# ---------------------------------------------------------------------------
# Client shim
# ---------------------------------------------------------------------------

class _OpenAICompatModels:
    def __init__(self, raw_client: Any):
        self._client = raw_client

    def generate_content(self, *, model: str, contents, config=None, **_ignored) -> _FakeResponse:
        system_instruction = getattr(config, "system_instruction", None) if config is not None else None
        messages = _gemini_contents_to_openai_messages(contents, system_instruction)
        tools = _gemini_tools_to_openai(getattr(config, "tools", None) if config is not None else None)

        kwargs: dict[str, Any] = {}
        temperature = getattr(config, "temperature", None) if config is not None else None
        if temperature is not None:
            kwargs["temperature"] = temperature
        max_tokens = getattr(config, "max_output_tokens", None) if config is not None else None
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = tools

        resp = self._client.chat.completions.create(model=model, messages=messages, **kwargs)
        return _wrap_chat_completion(resp)


# Local OpenAI-compatible servers (llama-swap in particular) can take a while
# on a cold request — swapping/loading a model that was "stopped" into VRAM
# before it can even start inferring — so this needs to be generous, not the
# SDK's tight default. Bounded rather than unbounded so a genuinely hung
# upstream can't tie up a worker thread indefinitely.
_REQUEST_TIMEOUT_SEC = 120.0


class _OpenAICompatClient:
    def __init__(self, base_url: str, api_key: str | None):
        import openai  # local import: only needed when this provider is actually selected

        self._raw = openai.OpenAI(
            base_url=base_url,
            api_key=api_key or "not-needed",
            timeout=_REQUEST_TIMEOUT_SEC,
            # ai_coach.py's own per-hop retry loop already retries on
            # failure — don't let the SDK silently retry underneath it too.
            max_retries=0,
        )
        self.models = _OpenAICompatModels(self._raw)


@lru_cache(maxsize=1)
def get_llm_client() -> Any:
    """
    Returns the client used for chat/insights/memory generate_content()
    calls — either the real genai.Client (LLM_PROVIDER=gemini, the default)
    or the OpenAI-compatible shim above. Cached: provider/base URL are
    read once at process startup from settings, matching how each call
    site already caches its own `_client = genai.Client(...)` at import time.
    """
    provider = (settings.LLM_PROVIDER or "gemini").strip().lower()
    if provider == "openai":
        if not settings.OPENAI_API_BASE_URL:
            raise RuntimeError(
                "LLM_PROVIDER=openai requires OPENAI_API_BASE_URL to be set "
                "(e.g. http://localhost:8080/v1 or your llama-swap URL)."
            )
        logger.info("[llm_provider] using OpenAI-compatible endpoint %s", settings.OPENAI_API_BASE_URL)
        return _OpenAICompatClient(settings.OPENAI_API_BASE_URL, settings.OPENAI_API_KEY)
    return genai.Client(api_key=settings.GEMINI_API_KEY)
