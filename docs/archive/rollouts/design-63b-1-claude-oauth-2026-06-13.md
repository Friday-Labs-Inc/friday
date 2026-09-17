# Design 63b-1 — Anthropic Claude OAuth + the OAuth foundation (2026-06-13)

## The one-sentence version

Log Friday into your **Claude Pro/Max subscription** with a browser approval +
paste — no API key — and agents run on it; plus the shared OAuth plumbing
(encrypted token store, auto-refresh) that 63b-2 (Codex) builds on.

## Why this is PR #1 of two

Design 63b-OAuth ("provider OAuth login like Hermes") ships in two PRs: **63b-1
(this PR)** = the shared OAuth infra + the Anthropic Claude flow end-to-end;
**63b-2** = the OpenAI Codex device-code flow + a new Responses-API transport.
Claude lands first because it reuses the Messages API Friday already speaks.

## What this PR ships

### 1. OAuth data model on `LLM Provider`

`auth_mode` (`api_key`/`oauth`, default `api_key` — existing rows unaffected),
`oauth_flavor` (`anthropic-claude`/`openai-codex`), and encrypted Password fields
for `oauth_access_token` / `oauth_refresh_token` / `oauth_pkce_verifier` plus
`oauth_expires_at`, `oauth_account_id`, transient `oauth_state` / `oauth_device_id`.
`api_key` is no longer required (an OAuth provider has none) and hides when
`auth_mode == oauth`.

### 2. The Claude flow — `llm/oauth/anthropic.py` (manual-paste PKCE)

The Claude Pro/Max login (the same public protocol Claude Code uses). **No
callback route**: `build_authorize_url` mints PKCE (S256) + a CSRF `state`,
persists them transiently, and returns a `claude.ai/oauth/authorize` URL. The
operator approves; Anthropic's own page shows a `code#state` string; the operator
pastes it; `exchange_code` validates the state, exchanges the code (JSON grant,
with host fallback), stores tokens, and wipes the transient verifier/state.
`refresh` renews via the refresh-token grant.

### 3. The shared store — `llm/oauth/tokens.py`

Stores tokens (encrypted) + clears transient state; `is_expiring` (120s skew);
`get_fresh_access_token` returns a guaranteed-fresh token, refreshing in-line via
the right flavour if it's about to expire (the on-use guarantee). Errors raise a
real `OAuthError` — never a silent stale-token fallback.

### 4. Inference integration — `llm/provider.py`

`_build_provider` gains an `auth_mode == "oauth"` branch (fetched *before* the
api-key path so an OAuth row never hits `_get_api_key`). For `anthropic-claude`
it builds an `AnthropicProvider` carrying the OAuth token; `AnthropicProvider`
now switches its auth header set: **OAuth** → `Authorization: Bearer` + the
required `anthropic-beta` (`claude-code-20250219,oauth-2025-04-20,…`),
`user-agent: claude-cli/<ver> (external, cli)`, `x-app: cli`; **API key** →
`x-api-key` (unchanged). `openai-codex` raises a clear "lands in 63b-2".

### 5. Endpoints, refresh cron, UI

- `llm/oauth/endpoints.py` — System-Manager-gated `start_claude_login` /
  `complete_claude_login` / `oauth_status` (never returns the token).
- `llm/oauth_token_refresh.tick` on `*/30 * * * *` — backstop refresh of expiring
  OAuth providers, failure-isolated per provider.
- `llm_provider.js` — a **Login with Claude** button (opens the URL, collects the
  pasted code, exchanges it) + an OAuth status comment on the form.

## Compare with Hermes

The Claude OAuth *protocol* is external; per [[feedback_true-1to1-ports]] we port
the constants + behaviour faithfully (exact client_id, endpoints, betas,
user-agent, 120s skew) but the host is Frappe-native: encrypted Password fields
instead of `~/.claude/.credentials.json`, whitelisted endpoints + a Desk dialog
instead of a CLI prompt, the scheduler instead of an on-disk refresh loop. The
manual-paste flow needs no redirect registration — a clean fit for Desk.

## Security (the CRITICAL bar — [[feedback_v01-skills-first-party-trust]])

Tokens + PKCE verifier in encrypted Password fields; never logged or returned by
a read; CSRF `state` validated and the verifier/state wiped right after exchange;
every endpoint System-Manager-gated; token POSTs go only to the literal Anthropic
hosts; refresh failures fail loud.

## Why we know it works

25 unit tests across `test_oauth_tokens` (expiry/skew, store+clear, fresh/refresh),
`test_oauth_anthropic` (PKCE S256 vector, authorize URL, state-mismatch reject,
code exchange, refresh, host fallback), `test_provider_oauth` (Bearer+betas vs
x-api-key; the build branch), and `test_oauth_endpoints` (delegation, guard, the
refresh cron + failure isolation). All green.

## What's NOT in this PR

OpenAI Codex (63b-2 — needs the Responses-API transport); auto-detecting a local
`~/.claude/.credentials.json`; credential pooling/rotation.

## Operator note

`bench migrate` + `bench build --app frappe`. Open an LLM Provider → **OAuth Login
→ Login with Claude** (or via the setup wizard), approve in the browser, paste the
`code#state`. The provider flips to `auth_mode = oauth`; agents linked to it run
on the subscription. **Maintenance:** the spoofed `claude-cli` version in
`AnthropicProvider.CLAUDE_CLI_VERSION` must be bumped periodically — Anthropic
rejects OAuth traffic from stale CLI versions.
