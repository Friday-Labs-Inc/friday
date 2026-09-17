# Design 63b-OAuth — Provider OAuth Login (Claude Max + Codex)

**Status:** LOCKED 2026-06-13. Scope fork answered by the user: **both Anthropic
Claude OAuth AND OpenAI Codex OAuth now**, robust, no corners. Ships as **two
PRs under this one design**: **63b-1** = shared OAuth infra + Anthropic Claude
OAuth (manual-paste PKCE, Messages API); **63b-2** = OpenAI Codex device-code +
a new OpenAI **Responses-API** transport. Tests-first per
[[feedback_workflow-design-lock-before-roo-code]].

## Why this exists — the plain English

> *"I need Anthropic and OpenAI provider support same like Hermes agents — all
> possible methods: api key, OAuth login."*

Friday today only authenticates LLM providers with an **API key**. The operator
has a **Claude Max** subscription and a **Codex** subscription; they want Friday's
agents to run on those subscriptions via OAuth login — exactly what Hermes does
with `hermes auth`. Design 63 gave model discovery + the picker; 64 gave the
setup wizard (with an "OAuth — coming soon" placeholder). 63b-OAuth fills that
placeholder with the real flows.

## The principle that drives every Q below

> **An OAuth provider is the same `LLM Provider` row, switched to `auth_mode =
> oauth`. The access token rides in the same slot the API key did — the provider
> layer swaps the auth header and (for Codex) the wire format. Tokens are
> encrypted, never logged, and refreshed before they expire.**

## Compare with Hermes — faithful where it's a protocol, ours where it's a host

The OAuth *protocols* are external (Claude's PKCE flow, OpenAI's device-code) —
Hermes implements them from scratch and so do we; per [[feedback_true-1to1-ports]]
we port the **protocol constants and behaviour faithfully** (exact client_ids,
endpoints, headers, refresh skew) but the **host integration is Frappe-native**
(encrypted Password fields, whitelisted endpoints, the scheduler) rather than
Hermes' `auth.json` + CLI prompts. Every divergence is host-adaptation, disclosed
in the ports ledger.

### The exact protocol constants (from Hermes source, verified)

**Anthropic Claude (manual-paste PKCE — no callback route needed):**
- client_id `9d1c250a-e61b-44d9-88ed-5944d1962f5e` (public, no secret)
- authorize `https://claude.ai/oauth/authorize` (params include `code=true`,
  `response_type=code`, `scope=org:create_api_key user:profile user:inference`,
  `code_challenge` S256, `state`)
- redirect_uri `https://console.anthropic.com/oauth/code/callback` — **Anthropic's
  own page that DISPLAYS the code**; the operator copies `code#state` and pastes
  it back. No Frappe redirect/callback registration.
- token `https://console.anthropic.com/v1/oauth/token` (JSON body for the
  auth-code exchange; form-encoded for refresh; fallback host
  `https://platform.claude.com/v1/oauth/token`)
- refresh: `grant_type=refresh_token` + client_id; trigger when
  `expires_at <= now + 120s`.
- **inference**: base `https://api.anthropic.com`, **Messages API** (Friday
  already speaks this), header `Authorization: Bearer <token>` (NOT `x-api-key`),
  plus required `anthropic-beta: interleaved-thinking-2025-05-14,fine-grained-tool-streaming-2025-05-14,claude-code-20250219,oauth-2025-04-20`,
  `user-agent: claude-cli/<ver> (external, cli)`, `x-app: cli`.

**OpenAI Codex (proprietary device-code):**
- client_id `app_EMoamEEZ73f0CkXaXp7hrann` (public, no secret)
- device-auth `POST https://auth.openai.com/api/accounts/deviceauth/usercode`
  `{client_id}` → `{user_code, device_auth_id, interval}`
- user visits `https://auth.openai.com/codex/device`, enters `user_code`
- poll `POST https://auth.openai.com/api/accounts/deviceauth/token`
  `{device_auth_id, user_code}` → 200 `{authorization_code, code_verifier}` (the
  verifier is **server-supplied**), 403/404 = keep polling
- token `POST https://auth.openai.com/oauth/token` (form-encoded)
  `grant_type=authorization_code, code, redirect_uri=https://auth.openai.com/deviceauth/callback, client_id, code_verifier`
  → `{access_token, refresh_token}`
- refresh: `grant_type=refresh_token` + client_id; trigger on JWT `exp <= now+120s`;
  **refresh tokens are single-use (rotate)** — handle `refresh_token_reused`.
- **inference**: base `https://chatgpt.com/backend-api/codex`, **OpenAI Responses
  API** (`/responses`, `store: false` — NOT chat completions), header
  `Authorization: Bearer <token>`, plus `originator: codex_cli_rs` (Cloudflare —
  non-negotiable from a server), `User-Agent: codex_cli_rs/...`,
  `ChatGPT-Account-ID: <from JWT claim https://api.openai.com/auth.chatgpt_account_id>`.

## Q1 — Scope *(LOCKED: both providers now, two PRs)*

63b-1 ships infra + Anthropic; 63b-2 ships Codex + the Responses transport. See Q9.

## Q2 — Data model *(recommended: fields on LLM Provider)*

Add to `llm_provider.json` (all OAuth fields only meaningful when
`auth_mode == "oauth"`):

| field | type | purpose |
|---|---|---|
| `auth_mode` | Select (`api_key`/`oauth`), default `api_key` | which credential path |
| `oauth_flavor` | Select (`anthropic-claude`/`openai-codex`) | drives flow + transport |
| `oauth_access_token` | Password | the bearer token (encrypted) |
| `oauth_refresh_token` | Password | for refresh (encrypted) |
| `oauth_expires_at` | Datetime | access-token expiry (Anthropic: from `expires_in`; Codex: from JWT `exp`) |
| `oauth_account_id` | Data | Codex `ChatGPT-Account-ID` (from JWT) |
| `oauth_pkce_verifier` | Password | transient, between start and complete (Anthropic); cleared after exchange |
| `oauth_state` | Data | transient CSRF state (Anthropic); cleared after exchange |
| `oauth_device_id` | Data | transient `device_auth_id` (Codex); cleared after poll success |

`api_key` becomes non-mandatory (an OAuth provider has no key). Existing api-key
rows are unaffected (`auth_mode` defaults to `api_key`).

## Q3 — Anthropic flow *(manual-paste PKCE)*

`llm/oauth/anthropic.py`:
- `build_authorize_url(provider)` — generate PKCE (verifier=32 rand bytes
  urlsafe-b64 no pad; challenge=S256) + `state`=token_urlsafe(32); persist
  verifier+state (transient, encrypted verifier); return the `claude.ai/oauth/authorize`
  URL.
- `exchange_code(provider, pasted)` — split `code#state`, **validate state**
  (CSRF; reject mismatch), POST the JSON auth-code body with the stored verifier,
  store `access/refresh/expires_at`, **clear** verifier+state.
- `refresh(provider)` — form-encoded refresh grant; update tokens+expiry.

No callback route. The operator pastes the code into a Desk dialog.

## Q4 — Codex flow *(device-code poll)*

`llm/oauth/codex.py`:
- `start_device(provider)` — POST usercode; persist `device_auth_id`; return
  `{user_code, verification_url, interval}`.
- `poll_device(provider)` — POST poll once; on 200 exchange the code (form body,
  server `code_verifier`), decode JWT for `exp` + `chatgpt_account_id`, store
  tokens+expiry+account_id, clear device_id; on not-ready return `{pending: true}`.
  (The Desk UI polls this endpoint on an interval; the server does one poll per
  call so we never block a worker.)
- `refresh(provider)` — rotation-aware refresh; on `refresh_token_reused` mark
  the provider needing re-login (loud, not silent).

## Q5 — Inference integration *(provider.py branch)*

`_build_provider()` gains an `auth_mode` branch:
- **api_key** (today) — unchanged.
- **oauth** — call `oauth/tokens.get_fresh_access_token(provider)` (refreshes
  in-line if within the 120s skew — the on-use guarantee), then:
  - `anthropic-claude` → `AnthropicProvider` with an OAuth header set (Bearer +
    the beta/user-agent/x-app headers), base `https://api.anthropic.com`,
    Messages API (existing transport).
  - `openai-codex` → a **new `CodexProvider`** speaking the **Responses API**
    (`/responses`, `store:false`, the Cloudflare headers + account id). 63b-2.

`AnthropicProvider.chat()` switches `x-api-key` → the OAuth header set when the
provider is OAuth. `model_discovery` gets the same branch (OAuth Bearer).

## Q6 — Token refresh *(on-use primary, cron backstop)*

- **On-use (primary):** `get_fresh_access_token` refreshes if expiring within
  120s before every build — so a token is never used stale. Mirrors Hermes.
- **Cron backstop:** `llm/oauth_token_refresh.tick` on `*/30 * * * *` refreshes
  any oauth provider expiring soon, so long-idle providers stay warm and a
  broken refresh surfaces (Issue + log) before an agent needs it.

## Q7 — UI *(LLM Provider form + setup wizard)*

- `llm_provider.js`: when `auth_mode == oauth`, show **Login with Claude**
  (→ dialog: open authorize URL + paste-code field) or **Login with Codex**
  (→ dialog: show user_code + link, poll until done), and a token status line
  (valid until / expired / needs re-login).
- Design 64 wizard Step 1: the "OAuth — coming soon" affordance becomes a real
  "Login with Claude / Codex" path.

## Q8 — Security *(per [[feedback_v01-skills-first-party-trust]] — CRITICAL bar)*

- All tokens + the PKCE verifier in encrypted **Password** fields; never logged,
  echoed, or returned by a whitelisted read. `state` CSRF-validated; verifier/state
  cleared immediately after exchange.
- Every OAuth endpoint is **System-Manager-gated** (`frappe.only_for`).
- Refresh failures (incl. Codex `refresh_token_reused`) fail **loud** — log +
  Issue + a "needs re-login" status — never a silent fallback to a stale token.
- The token-exchange/refresh POSTs go over TLS to the literal provider hosts; no
  redirect-following to arbitrary hosts.

## Q9 — Phasing (two PRs, both this cycle)

| PR | Scope | Verify |
|---|---|---|
| **63b-1** | LLM Provider OAuth fields + `auth_mode`; `oauth/anthropic.py` (authorize/exchange/refresh) + `oauth/tokens.py` (store + get_fresh + JWT exp); provider.py + discovery OAuth branch for Anthropic; refresh cron; whitelisted endpoints + LLM Provider form buttons; wizard wiring | unit tests for PKCE/state/exchange/refresh/expiry; AnthropicProvider sends Bearer+betas; on a real bench, Login with Claude → paste → a chat turn runs on the subscription |
| **63b-2** | `oauth/codex.py` (device/poll/refresh) + a new `CodexProvider` (Responses API, `store:false`, Cloudflare+account headers) + provider.py codex branch + JWT account-id extraction; form buttons + wizard | unit tests for device/poll/exchange/JWT-decode/refresh-rotation + the Responses request shape; on a real bench, Login with Codex → a chat turn runs on the subscription |

## What's explicitly NOT in 63b-OAuth

- Auto-detecting an existing local `~/.claude/.credentials.json` (Hermes does;
  out of scope — explicit login only).
- Credential **pooling/rotation** across multiple tokens (Hermes' credential
  pool) — single token per provider row.
- Other OAuth providers (xAI, Qwen, Gemini-CLI, Nous) — Claude + Codex only.
- Streaming responses — same posture as the existing providers (non-streaming).
