# Design 63 — Provider Model Discovery

**Status:** LOCKED 2026-06-13 (all Qs as recommended; user said "go").
Lands as **one PR** (63). OAuth is an explicit follow-up (63b), not this
slice.

## Why this exists — the plain English

The user's words from the first hands-on test:

> *"currently I am not able to list/see the providers' models — for
> example Minimax has many models, I don't have the option."*

Today an `LLM Provider` row stores `default_model` as a **free-text Data
field**. There is **zero** model discovery anywhere in the codebase — no
call to a provider's `/v1/models`, no cached list, no dropdown. You have
to *know* the exact model string and type it by hand. Get it wrong and
the first chat turn fails with a provider error.

## Compare with Hermes

Hermes has exactly this: `hermes_cli/models.py` →
`provider_model_ids(provider)` calls each provider's live `/models`
endpoint (Anthropic `GET /v1/models` with `x-api-key`; OpenAI-compat
`GET <base>/models` with Bearer; OpenRouter with tool-support filter) and
falls back to a static `_PROVIDER_MODELS` catalog when the live call
fails. This design ports that pattern to Friday — **faithful to Hermes**
([[feedback_true-1to1-ports]]), adapted to Friday's `LLM Provider`
DocType.

## Q1 — Discovery mechanism

*Recommendation:* a `llm/model_discovery.py` module with one function:

```python
fetch_models(provider_type, api_key, base_url) -> dict
# → {"models": ["...", ...], "source": "live" | "catalog", "error": str|None}
```

Per `provider_type`:
- **anthropic** → `GET {base}/v1/models`, headers `x-api-key` +
  `anthropic-version: 2023-06-01`, parse `data[].id`.
- **openai / minimax / openrouter / any openai-compat** →
  `GET {base}/v1/models`, `Authorization: Bearer {key}`, parse
  `data[].id`.
- network error / non-200 / no key → fall back to a curated
  `_CATALOG[provider_type]` and set `source="catalog"`, `error=<reason>`.

The catalog is a **thin fallback** (a handful of stable, known model IDs
per provider) so the picker is never empty even when the key is missing
or the endpoint is down. Live is always authoritative when reachable.

## Q2 — How the operator sees it

*Recommendation:* a whitelisted method
`llm.model_discovery.list_models(provider_name)` that loads the `LLM
Provider` row, resolves its `api_key` (the existing `get_password`
path), and returns `fetch_models(...)`. The Desk uses it to populate a
model picker; an agent could later use it too.

v0.1 keeps `default_model` a Data field (no schema churn) but the picker
calls this endpoint so the operator chooses from the **real** list
instead of typing. (Turning the field into a dynamic Select is a Desk-UI
follow-up; the data layer is what unblocks the pain now.)

## Q3 — Provider parity

The Anthropic and OpenAI provider classes already exist and work
(`provider.py`); this design does not rebuild them. "Parity" here =
**discovery parity** — every provider type can list its models. The
`openrouter` type (today raises `LLMError` on build) gets discovery
support so its models are visible even before a chat adapter lands.

## Scope

In: `model_discovery.py` (live fetch + catalog fallback for anthropic /
openai / minimax / openrouter), the whitelisted `list_models`, tests,
live-bench proof.

Out (explicit follow-up 63b): **OAuth** (Anthropic Claude OAuth, OpenAI
Codex OAuth) — it needs a credential store, token refresh, and a browser
flow; a substantial slice on its own. API-key auth already works. Also
out: turning `default_model` into a dynamic Select (Desk-UI polish);
per-model context-length/cost metadata (Hermes' `model_metadata.py`).

## What lands on disk — one PR (63)

- `llm/model_discovery.py`: `fetch_models` + `_CATALOG` + the whitelisted
  `list_models`.
- Tests: live-shape parsing per provider, Bearer vs x-api-key header
  selection, catalog fallback on error/no-key, unknown provider type.
- Live proof: call `list_models("Minimax")` on the bench and get a real
  model list (live or catalog); call for anthropic/openai and get the
  catalog when no key is set.
