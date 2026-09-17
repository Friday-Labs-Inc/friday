# Design 63b-2 — OpenAI Codex OAuth + the Responses-API transport (2026-06-13)

## The one-sentence version

Log Friday into your **ChatGPT/Codex subscription** with a device code, and
agents run on it through a new OpenAI **Responses-API** transport — completing
63b-OAuth (Claude landed in 63b-1).

## Why this is PR #2 of two

63b-1 shipped the OAuth foundation + Claude. Codex is its own PR because it
needs two things Friday didn't have: a **device-code** login (not manual-paste)
and the **Responses API** wire format (`/responses`, `store:false`) — Codex does
not speak Chat Completions.

## What this PR ships

### 1. The Codex flow — `llm/oauth/codex.py` (device-code)

OpenAI's proprietary device-code chain: `start_device` requests a user code and
persists the `device_auth_id` transiently; the operator enters the code at
`auth.openai.com/codex/device`; `poll_device` polls once per call (so a worker
never blocks), returning `{pending: true}` until approved, then exchanges the
authorization code (with the **server-supplied** PKCE verifier) and stores
tokens. The access token is a JWT — `jwt_claims` reads `exp` (for expiry, since
Codex returns no `expires_in`) and the `chatgpt_account_id` claim (for the
inference header). `refresh` is **rotation-aware**: a `refresh_token_reused`
(409) means another client consumed the single-use token → fail loud, require
re-login (never a silent stale token).

### 2. The Responses-API transport — `CodexProvider` in `llm/provider.py`

A new provider class. Unlike every other adapter it speaks the OpenAI
**Responses API** (`/responses`, `store:false`), not chat completions:

- **Headers** OpenAI requires from non-browser clients: `Authorization: Bearer`,
  `originator: codex_cli_rs` (passes Cloudflare — without it `chatgpt.com/
  backend-api/codex` returns a challenge), a `codex_cli` user-agent, and
  `ChatGPT-Account-ID` from the JWT.
- **Translation**: canonical messages → Responses `input` items (system →
  top-level `instructions`; user/assistant text → `input_text`/`output_text`
  message items; tool calls → `function_call` items; tool results →
  `function_call_output`). Tools → the flat Responses function-tool shape.
- **Parsing**: the `output` array → text (`output_text` blocks) + canonical
  `{id, name, arguments}` tool calls; `usage` → the canonical token fields.

`_build_provider`'s `openai-codex` branch builds it with the OAuth token +
account id; refresh dispatch (`tokens._refresh_for_flavor`) and the `*/30` cron
already handle Codex from 63b-1.

### 3. Endpoints + UI

`start_codex_login` / `poll_codex_login` (System-Manager-gated). The LLM Provider
form gains a **Login with Codex** button: shows the user code + opens the
verification page, then polls until approved.

## Compare with Hermes

Faithful to the proprietary protocol Hermes reverse-engineered (exact endpoints,
the server-supplied verifier, the Cloudflare `originator` header, the JWT
account-id claim, single-use refresh) per [[feedback_true-1to1-ports]]; the host
is Frappe-native (encrypted fields, whitelisted endpoints, the scheduler).

## Honest caveats (disclosed, not hidden)

This path is inherently more fragile than Claude's, and that's a property of the
provider, not the port:
- OpenAI **polices** the spoofed `originator`/user-agent — a server IP can still
  be Cloudflare-challenged, and the headers may need updating over time.
- Refresh tokens are **single-use**; concurrent refresh from two processes will
  trip `refresh_token_reused` (we fail loud + require re-login).
- The Responses-API request/parse shapes are verified by unit tests against
  documented payloads; live behaviour depends on OpenAI not changing the surface.

## Why we know it works

12 unit tests in `test_oauth_codex`: JWT decode (+ malformed → {}), device start
(persist + user code), poll pending vs success (exchange + store + account id),
the reused-refresh-token → re-login, and the **Responses transport** — request
headers (Bearer/originator/account-id), payload (`store:false`, `instructions`,
input items, flat tools), and output parsing (text + tool calls + usage). The
provider build branch test confirms a `CodexProvider` with the token + account
id. All green; 63b-1's suite unaffected.

## Operator note

`bench migrate` + `bench build --app frappe` → LLM Provider → **OAuth Login →
Login with Codex**, enter the code at the opened page, wait for approval. If you
hit a Cloudflare challenge from a server IP, that's OpenAI's mitigation — the
`originator`/user-agent in `CodexProvider` may need refreshing.
