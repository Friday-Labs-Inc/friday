# Design 63 — You can see a provider's models now (2026-06-13)

## The one-sentence version

`list_models("Minimax")` now returns Minimax's **real live model list**
(MiniMax-M3, M2.7, M2.5, …) instead of you having to know and type the
exact model string by hand.

## What you would have seen, before today

An `LLM Provider` row stored `default_model` as free text. There was no
way to discover what a provider offers — you typed a model string from
memory, and a typo failed the first chat turn with a provider error.
Your words: *"Minimax has many models, I don't have the option."*

## What this PR ships

**`llm/model_discovery.py`** — ports Hermes' `models.py` pattern:

- `fetch_models(provider_type, api_key, base_url)` calls the provider's
  own `/v1/models` endpoint with the right auth (Anthropic `x-api-key` +
  version header; OpenAI / Minimax / OpenRouter Bearer), parses
  `data[].id`, and returns the live list.
- Falls back to a thin curated catalog when the key is missing, the
  endpoint is down, or returns non-200 — so the picker is never empty.
  `source` is `live` or `catalog`, and `error` says why on fallback.
- `list_models(provider_name)` — whitelisted; resolves the LLM Provider
  row's decrypted key and delegates. The Desk model picker calls this.

## Why we know it works

- **9 new** `test_model_discovery.py` — Bearer vs x-api-key header
  selection per provider; live parse of `data[].id`; catalog fallback on
  no-key / network-error / non-200; unknown provider type; the
  whitelisted endpoint resolves the row + key.

**Live proof on `friday.localhost`:** `list_models("Minimax")` returned
8 real models from Minimax's live API (`source: live`):
`MiniMax-M3, MiniMax-M2.7, MiniMax-M2.7-highspeed, MiniMax-M2.5, …`. The
anthropic / openai / openrouter catalog fallbacks returned their curated
lists when no key was set.

## What's NOT in this PR (explicit follow-up 63b)

- **OAuth** (Anthropic Claude OAuth, OpenAI Codex OAuth) — needs a
  credential store, token refresh, and a browser flow; a substantial
  slice on its own. API-key auth already works for all four providers.
- Turning `default_model` into a dynamic Select dropdown in the Desk —
  the data layer (this endpoint) is what unblocks the pain; the UI
  binding is Desk-side polish.
- Per-model context-length / cost metadata (Hermes' `model_metadata.py`).

## Operator note

No migration needed. Call
`/api/method/friday.friday_core.llm.model_discovery.list_models?provider_name=<name>`
or `bench execute friday.friday_core.llm.model_discovery.list_models --args "['Minimax']"`.
