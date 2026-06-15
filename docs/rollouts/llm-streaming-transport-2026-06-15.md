# LLM Provider — Streaming Transport (Hermes Port)

**Date:** 2026-06-15
**Driver:** FLI-001 `Brand guidelines draft` task — the same Minimax key that runs hours-long Roo Code and Hermes coding/research sessions was timing out at 30s on every Friday goal-mode call. The user (correctly) called out that the issue wasn't the key or the timeout knob — it was an architectural gap.

## The diagnosis

Friday's `_OpenAICompatibleProvider.chat()` was a single blocking `requests.post(url, json=payload, timeout=N)`. Hermes uses the OpenAI SDK with `stream=True`, with the timeout split between an overall budget and a per-chunk stale watchdog. Two-row table for the difference:

| | Friday (before) | Hermes / Roo / now Friday |
|---|---|---|
| Transport | `requests.post()` blocking | `openai.OpenAI(...).chat.completions.create(stream=True, ...)` |
| Connection model | New HTTP/1.1 per call, no keep-alive | httpx pool, HTTP/2 where supported |
| Watchdog | Total wall-clock (30s, then 1800s) | `httpx.Timeout(read=stale, write=total)` — read is the stale-byte detector |
| Failure mode | Single blob succeeds or fails | Each delta proves the connection is alive; stall fails in `stale_seconds` |
| Goal-mode | Hits 30s before first token completes | Streams ~4k tokens in 47s with no stall |

## What changed

### `LLM Provider` DocType — two new fields

- **`request_timeout_seconds`** (Int, nullable, default 1800 when blank) — total session budget, maps to `httpx.Timeout.write`. The Hermes-parity default of 30 min covers any goal-mode generation.
- **`request_stale_seconds`** (Int, nullable, default 120 when blank) — streaming watchdog, maps to `httpx.Timeout.read`. Matches Hermes's `HERMES_STREAM_READ_TIMEOUT` default. This is the knob that actually fires on a hung provider; the budget above is the cap behind it.

Both fields are nullable — leave blank to get the defaults. Lower `stale` for fast-fail; raise it for slow-prefill local providers (Ollama, llama.cpp).

### `LLMProvider` base class

- New `DEFAULT_REQUEST_TIMEOUT_SECONDS = 1800.0` and `DEFAULT_REQUEST_STALE_SECONDS = 120.0` constants (Hermes parity).
- New instance attrs `request_timeout_seconds` and `request_stale_seconds`, attached by `_build_provider._with_pricing` from the row.
- New resolvers `_effective_request_timeout()` and `_effective_stale_seconds()` — defensive against zero / negative / non-numeric configured values, which would otherwise produce 0-second timeouts.

### `_OpenAICompatibleProvider.chat()` — the actual port

Replaced the `_post_with_recovery(url, headers, payload, model)` call with `_stream_with_recovery(stream_kwargs, model)`. The `chat()` signature is unchanged so the rest of Friday (runner, agent_runner, etc.) sees the same `LLMResponse` shape.

The new helpers ported from Hermes (`agent/chat_completion_helpers.py::interruptible_streaming_api_call`):

- **`_build_openai_client()`** — constructs a per-request `openai.OpenAI(api_key, base_url, timeout=httpx.Timeout(connect=..., read=stale, write=total, pool=...), max_retries=0)`. The Hermes idiom: total budget on `write`, stale watchdog on `read`. Misplacing them would mean a fast-streaming 30-min generation falls inside the budget while a 35s silence (legitimate slow first token) kills it.
- **`_stream_with_recovery()`** — wraps `client.chat.completions.create(stream=True, stream_options={"include_usage": True}, ...)` in the existing retry loop. Catches the SDK exception hierarchy (`APIStatusError`, `APITimeoutError`, `APIConnectionError`, `APIError`) and routes each through the same `error_classifier` Feature F that the old path used, so the runner sees the same `LLMError(reason="timeout"|"rate_limit"|...)` semantics for blocked-reason / reconciler retry behavior.
- **`_consume_stream()`** — iterates SDK chunks, accumulates content (concatenated), tool-call deltas (id assigned once, args concatenated, per-index), finish_reason, and usage from the terminal chunk. Returns the same dict shape `_parse_response` already consumed — zero downstream changes.

### `MinimaxProvider` URL derivation

Minimax's legacy `CHAT_PATH = "/v1/text/chatcompletion_v2"` is not OpenAI-shaped. The SDK constructs `{base_url}/chat/completions`. So the SDK's `base_url` must be derived such that the final URL is correct:

- If `{self.base_url}{self.CHAT_PATH}` ends in `/chat/completions` (OpenAI, OpenRouter) — strip that suffix.
- Otherwise — fall back to `{base_url}/v1` (matches Hermes's `MINIMAX_BASE_URL = https://api.minimax.io/v1`). The SDK then constructs `https://api.minimax.io/v1/chat/completions` — Minimax's modern OpenAI-compatible endpoint.

## Disclosed deviations from Hermes

Per [[true-1to1-ports]]:

| Deviation | Type | Rationale |
|---|---|---|
| Config lives on the LLM Provider DocType row, not Hermes's TOML files + env vars | **frappe-adaptation** | Frappe-native config UI. Same logic; the row IS the per-provider config. |
| No per-model override (Hermes has `providers.<id>.models.<model>.timeout_seconds`) | **simplification** | Friday's profile-level model selection already separates a model from a provider row; can be added later if needed. |
| No env-var escape hatch (`HERMES_API_TIMEOUT`) | **simplification** | The row is the only knob — fewer surprises. |
| Single retry loop catches `APIStatusError + APITimeoutError + APIConnectionError + APIError + httpx.HTTPError`, no Anthropic/Bedrock/Codex branches | **not yet ported** | OpenAI-compatible streaming covers Minimax, OpenAI, OpenRouter, Together, Groq, Anyscale. Anthropic streaming uses `messages.stream()` and needs its own port (separate slice). |
| No agent-interrupt check (Hermes mid-stream `agent._interrupt_requested`) | **simplification** | Friday's runner doesn't surface user-cancellation mid-LLM-call yet. Easy to add. |
| No Ollama parallel-tool-call index workaround | **not yet ported** | Friday's first-party skills don't currently exercise providers that need it. |
| No tool-call JSON repair on truncated args | **not yet ported** | Belongs with the broader compaction story; defer. |
| No rate-limit header capture / diagnostic counters | **simplification** | Design 72's `llm.call_summary` event already captures the operational details (model, tokens, cost). |

## Bonus: the `request_timeout_seconds` knob

The intermediate timeout-only fix (added earlier in the same diff) is preserved. With `request_timeout_seconds=1800` and the OLD blocking POST, the guidelines task did eventually complete by absorbing the full 30-min budget on a single shot — but that's the wrong shape. With streaming + 120s stale, it completes in ~47s and a real hang fails in 120s, not 30 min.

## What we proved live

Same FLI-001 `Brand guidelines draft` task that timed out at 30s on every retry:

```
10:13:04 — dispatcher.claim_attempt (won)
10:13:05 — runner.start
10:13:09 — llm.call_summary  minimax/MiniMax-M3  1910+79=1989 tok      ← 4s to first response
10:13:52 — llm.call_summary  minimax/MiniMax-M3  2081+2048=4129 tok    ← 43s of streaming
10:13:52 — runner.complete   47833ms
```

**4,129 tokens streamed cleanly in 47s. retry_count=0. blocked_reason=None.** Same key, same model, same task. The transport was the bug.

## Tests

- `test_llm_provider_streaming.py` — 21 tests across:
  - `TestStreamAssembly` — content/tool-call/usage accumulation across chunks, including the assign-not-concat name fix.
  - `TestClientTimeoutWiring` — `httpx.Timeout` granularity wiring, defaults, zero-fallback.
  - `TestChatGoesThroughStreaming` — `chat()` routes through `_stream_with_recovery`.
  - `TestBuildProviderAttachesStaleSeconds` — `_build_provider` propagates the row field.
  - `TestStreamingRetryBehavior` — retry on 429/500, fail-fast on 400, auth-error on 401, transport timeout retried then raised with retryable=True.
  - `TestStreamingPayloadShape` — tools included/omitted, model override.
  - URL derivation tests for Minimax (legacy path) and OpenAI (standard).
- `test_llm_provider_timeout.py` — 6 tests for `request_timeout_seconds` config (added earlier in the same change).
- `test_llm_provider.py` — kept the `TestLLMProviderInterface`, `TestMinimaxProviderConstruction`, and `TestGetProviderForProfile` blocks. The old `TestMinimaxProviderChat` block (25 tests that mocked `requests.post`) was removed — its behavior is now covered by the SDK-level tests above.

Total: 36 LLM-provider tests, all green.

## Migration

- One DocType change (two new nullable fields) — clean `bench migrate`.
- No data migration required — existing rows get `None` → both defaults apply (1800s / 120s).
- Backward-compatible: every existing call site still calls `provider.chat(messages, tools, model)` and receives an `LLMResponse`. The transport is internal.
