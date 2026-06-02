# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
LLM provider abstraction and Minimax M2 implementation.

PROVIDER INTERFACE
==================

Every provider implements `LLMProvider` — a minimal interface with one method:

    chat(messages, tools=None, model=None) → LLMResponse

The interface is deliberately thin so adding OpenAI / Claude / OpenRouter
is a matter of subclassing and implementing one method.

PROVIDER RESOLUTION
==================

`get_provider_for_profile(profile_name)` is the public entry point:

  1. Read the `Agent Profile` row for `profile_name`.
  2. If `model_provider` is set, load that `LLM Provider` row.
  3. Otherwise, fall back to `Agent Settings.default_provider`.
  4. If neither is set, load the first active `LLM Provider` row (last resort).
  5. Return a provider instance configured from that row.

The returned instance is NOT cached — creating it is cheap and you get a
fresh one per call. All per-request state (auth headers, timeouts) is
set at construction time, not at call time.

ERROR HANDLING
==============

Every failure routes through the shared classifier (`error_classifier.py`,
Feature F), which labels it and returns recovery hints:
- **401/403** → `LLMAuthError` (bad key — never retried).
- **429 / 500 / 502 / 503 / timeout** → retryable → up to 3 backoff retries.
- **404 / 400** → not retryable → fail fast (no point retrying a bad request).
- **After retries (or a non-retryable reason)** → `LLMError` with a clean,
  reason-based string (never the raw body or exception text). The gateway
  catches it and writes a system-error outbound row.

WHAT THIS MODULE DOES NOT DO
=============================

- Does not store API keys. Keys live in `LLM Provider.api_key` (Password
  field) — read at construction time from the DocType row.
- Does not own conversation history. That's managed by `prompt_builder`.
- Does not handle streaming. Streaming (progressive token delivery) is
  deferred until a real-time surface (Telegram, web chat) lands.

SEE ALSO
========
- `docs/contributing/proposals/slice-5-llm-integration.md` §2.1
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, TypedDict

import frappe
import requests

from frappe.friday_core.llm.error_classifier import classify_api_error

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class LLMResponse(TypedDict):
    """The result of a successful LLM call."""

    content: str
    finish_reason: str
    usage: dict  # {prompt_tokens, completion_tokens, total_tokens}
    tool_calls: list[dict] | None  # Minimax/OpenAI tool call list, or None


class LLMError(Exception):
    """Base exception for provider errors that bubble up to the gateway."""

    pass


class LLMAuthError(LLMError):
    """Raised on 401 — invalid or missing API key."""

    pass


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """Abstract base for all LLM provider adapters."""

    @abstractmethod
    def chat(
        self,
        messages: list[dict],  # [{"role": "system"|"user"|"assistant", "content": str}]
        tools: list[dict] | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        """
        Send a chat completion request and return the response.

        Arguments:
          - `messages` — the full prompt (system + history + current message).
          - `tools` — OpenAI-format tool definitions, or None for chat-only.
          - `model` — override the provider's default model, or None to use it.

        Returns `LLMResponse`.
        Raises `LLMAuthError` on 401, `LLMError` on other failures.
        """
        ...

    @abstractmethod
    def get_default_model(self) -> str:
        """Return the provider's default model identifier."""
        ...


# ---------------------------------------------------------------------------
# Minimax M2 implementation
# ---------------------------------------------------------------------------


class MinimaxProvider(LLMProvider):
    """Minimax M2 chat completions adapter.

    API reference:
    https://www.minimaxi.com/document/Guides/Chat Completion/V2/text/chat

    The API is OpenAI-compatible with minor differences:
      - Auth: Bearer token in Authorization header.
      - Endpoint: https://api.minimax.io/v1/text/chatcompletion_v2
        (international OpenAI-compat endpoint; matches Hermes' choice.
        Override via `LLM Provider.base_url` for region-specific endpoints
        e.g. https://api.minimaxi.com for China.)
      - Tool calling: supported via the `tools` parameter.
      - Response: similar shape to OpenAI but model_name in response differs.

    RETRY BUDGET CAVEAT (per design doc §11):
      With MAX_RETRIES=3 and exponential sleeps (1+2+4s = 7s) plus 30s per
      request, total wall-clock can reach ~97s before giving up. **This is
      safe for sync dispatch (CLI) but exceeds the 10s webhook deadline of
      Telegram/Slack.** When async surfaces land, either the retry policy
      needs to be dispatch-mode-aware OR the gateway needs to fire the
      webhook 200 OK before this retry loop begins (the current async-via-RQ
      design does the latter — the gateway already returns to the webhook
      before queueing the job — so this is documented but not blocking).
    """

    TIMEOUT_SECONDS = 30
    MAX_RETRIES = 3
    # International OpenAI-compatible endpoint. Hermes uses the same.
    # Override per row via `LLM Provider.base_url` for region-specific endpoints.
    DEFAULT_BASE_URL = "https://api.minimax.io"

    def __init__(
        self,
        api_key: str,
        default_model: str,
        base_url: str | None = None,
        default_max_tokens: int | None = None,
        default_temperature: float | None = None,
    ):
        self.api_key = api_key
        self.default_model = default_model
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        # Sampling defaults. None means "let the provider decide" — we
        # omit the field from the payload rather than send 0 or null.
        self.default_max_tokens = default_max_tokens
        self.default_temperature = default_temperature

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        model = model or self.default_model
        url = f"{self.base_url}/v1/text/chatcompletion_v2"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
        # Sampling params: only include when set on the provider row, so we
        # don't accidentally send 0 (which means deterministic) or 0 max_tokens
        # (which would reject the response). None = use the API default.
        if self.default_max_tokens is not None:
            payload["max_tokens"] = self.default_max_tokens
        if self.default_temperature is not None:
            payload["temperature"] = self.default_temperature

        last_exc: Exception | None = None
        for attempt in range(self.MAX_RETRIES):
            try:
                response = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.TIMEOUT_SECONDS,
                )
            except requests.exceptions.RequestException as exc:
                # Transport failure (timeout, connection reset, …). Classify to
                # decide whether to retry, but NEVER surface str(exc): a Timeout
                # or Connection error can carry a URL with a query string, and we
                # don't want secrets sneaking into the audit log.
                last_exc = exc
                classified = classify_api_error(exc, provider="minimax", model=model)
                if classified.retryable and attempt < self.MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
                    continue
                break

            # 2xx — success.
            if response.status_code < 300:
                return self._parse_response(response.json())

            # Non-2xx — the shared classifier decides the recovery action. The
            # body is passed for disambiguation only (e.g. a 429 that is really
            # credit exhaustion); it is never put into the raised error.
            body = response.text[:500] if isinstance(getattr(response, "text", None), str) else ""
            classified = classify_api_error(
                status_code=response.status_code,
                provider="minimax",
                model=model,
                message=body,
            )
            if classified.is_auth:
                raise LLMAuthError(
                    f"Minimax auth failed (HTTP {response.status_code}). Check the "
                    f"API key in the LLM Provider DocType."
                )
            if classified.retryable and attempt < self.MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
                continue
            # Not retryable, or retries exhausted — raise a clean, reason-based
            # error (no raw body — it can carry PII / partial content).
            raise LLMError(
                f"Minimax call failed: {classified.reason.value} "
                f"(HTTP {response.status_code}) after {attempt + 1} attempt(s)."
            )

        # Transport retries exhausted. Type name only (redaction policy).
        last_exc_type = type(last_exc).__name__ if last_exc else "Unknown"
        raise LLMError(
            f"Minimax call failed after {self.MAX_RETRIES} retries. "
            f"Last error type: {last_exc_type}"
        )

    def get_default_model(self) -> str:
        return self.default_model

    # -------------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------------

    def _parse_response(self, data: dict) -> LLMResponse:
        """Extract the assistant's text from a Minimax V2 response dict."""
        choices = data.get("choices", [])
        if not choices:
            # Redact: include structural keys only, not values. The response
            # body can carry partial content / tokens / user PII which we
            # never want in the Frappe Error Log.
            raise LLMError(
                f"Minimax response has no choices. response_keys={sorted(data.keys())}"
            )

        choice = choices[0]
        finish_reason = choice.get("finish_reason", "stop")

        # Minimax returns message.content directly.
        message = choice.get("message", {})
        content = message.get("content", "")

        # Tool calls (Minimax uses the same OpenAI-style tool_calls field).
        tool_calls = message.get("tool_calls") or None

        # Usage block.
        usage = data.get("usage", {})
        return LLMResponse(
            content=content or "",
            finish_reason=finish_reason,
            usage={
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
            tool_calls=tool_calls,
        )


# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------


def get_provider_for_profile(profile_name: str) -> LLMProvider:
    """Return the configured LLM provider for the given Agent Profile.

    Resolution order:
      1. `Agent Profile.model_provider` link → `LLM Provider` row.
      2. `Agent Settings.default_provider` link → `LLM Provider` row.
      3. First active `LLM Provider` row (last resort).
      4. Raises `LLMError` if no provider is configured.

    The returned provider instance is NOT cached. Construction is cheap
    and all secrets are already in memory from the DocType read.
    """
    provider_row = _resolve_provider_row(profile_name)
    if not provider_row:
        raise LLMError(
            f"No LLM Provider configured for Agent Profile {profile_name!r} "
            f"and no default in Agent Settings. Add at least one active "
            f"LLM Provider row in Desk."
        )

    api_key = _get_api_key(provider_row)
    provider_type = provider_row.get("provider_type") or "minimax"
    default_model = provider_row.get("default_model") or "MiniMax-Standard"
    base_url = provider_row.get("base_url") or None
    default_max_tokens = provider_row.get("default_max_tokens")
    default_temperature = provider_row.get("default_temperature")

    if provider_type == "minimax":
        return MinimaxProvider(
            api_key=api_key,
            default_model=default_model,
            base_url=base_url,
            default_max_tokens=default_max_tokens,
            default_temperature=default_temperature,
        )

    # Future: openai → OpenAIProvider(...), anthropic → AnthropicProvider(...),
    # openrouter → OpenRouterProvider(...). Each adds one branch here and one
    # subclass file. The DocType's `provider_type` Select field must be
    # extended in lockstep (frappe/friday_core/doctype/llm_provider/llm_provider.json).
    raise LLMError(f"Unsupported provider_type {provider_type!r}")


def _resolve_provider_row(profile_name: str) -> dict | None:
    """Find the LLM Provider DocType row to use for a profile.

    Resolution rules — IMPORTANT:

      - Step 1 (explicit profile link) is **strict**. If the Agent Profile
        names a model_provider AND that provider exists but is inactive,
        we RAISE rather than fall through. Rationale: an operator who
        deactivated the provider almost certainly meant "stop this profile
        from working until I fix this," not "silently route to a different
        provider." Silent fallback would be a governance bug.
      - We only fall through to step 2/3 if the link is empty OR the
        named provider row doesn't exist (genuine misconfiguration).
    """
    # Step 1: Agent Profile.model_provider link — strict.
    profile_model = frappe.db.get_value(
        "Agent Profile", profile_name, "model_provider", as_dict=True
    )
    if profile_model and profile_model.get("model_provider"):
        target = profile_model["model_provider"]
        if frappe.db.exists("LLM Provider", target):
            row = frappe.get_doc("LLM Provider", target)
            if not row.is_active:
                raise LLMError(
                    f"Agent Profile {profile_name!r} is linked to LLM Provider "
                    f"{target!r} which is currently inactive. Either reactivate "
                    f"it or change the profile's model_provider field."
                )
            return row.as_dict()
        # If the row doesn't exist, that's a stale link — fall through
        # to the defaults rather than raising.

    # Step 2: Agent Settings singleton.
    if frappe.db.exists("Agent Settings", {"name": "Agent Settings"}):
        default = frappe.db.get_value(
            "Agent Settings",
            "Agent Settings",
            "default_provider",
            as_dict=True,
        )
        if default and default.get("default_provider"):
            target = default["default_provider"]
            if frappe.db.exists("LLM Provider", target):
                row = frappe.get_doc("LLM Provider", target)
                if row.is_active:
                    return row.as_dict()

    # Step 3: First active LLM Provider row (last resort).
    rows = frappe.get_all(
        "LLM Provider",
        filters={"is_active": 1},
        order_by="creation asc",
        limit=1,
    )
    if rows:
        return frappe.get_doc("LLM Provider", rows[0]["name"]).as_dict()

    return None


def _get_api_key(provider_row: dict) -> str:
    """Read the API key from an LLM Provider dict.

    The key is stored in a Frappe Password field, which is encrypted at rest.
    Frappe provides `get_password()` to decrypt it at runtime.

    Errors from `get_password` (e.g. missing key, corrupted ciphertext,
    encryption-key rotation in progress) are deliberately NOT swallowed —
    they bubble up as the original exception so operators see the real
    cause in the Error Log instead of a misleading "Minimax 401" downstream.
    """
    doc = frappe.get_doc("LLM Provider", provider_row["name"])
    return doc.get_password("api_key") or ""
