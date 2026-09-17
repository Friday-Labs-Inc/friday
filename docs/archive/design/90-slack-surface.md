# Design 90 — Slack adapter (2nd chat surface)

> **Status:** Built 2026-06-24. Closes the "2nd surface" gap from the ports
> re-audit. Proves the unified-gateway claim that surfaces are interchangeable
> thin adapters over `Chat Message` rows.

## Plain English

Friday's gateway says any chat surface is a thin adapter that reads/writes
`Chat Message` rows; only Raven existed. This adds Slack by **mirroring
`raven_adapter.py` almost line-for-line** — only the transport differs (Slack's
Events API webhook in, Web API `chat.postMessage` out).

## How it works (mirror of Raven)

- **Inbound** — `receive_event` (a `@frappe.whitelist(allow_guest=True)` webhook,
  modelled on `surfaces/randompack.py`): verify the Slack signature, handle the
  `url_verification` handshake, then for a real user message apply the same
  guardrails as Raven (DMs answered; channels only on an explicit `<@BOT>`
  mention; skip the bot's own messages + bot/subtype events) and write ONE
  inbound `Chat Message` row (`platform="slack"`, `session_id`=Slack channel).
  The gateway worker does the rest.
- **Slash commands** — a leading `/` routes through the shared
  `gateway.commands.dispatch_command` (Design 82), exactly like
  `raven_adapter._handle_command`. Slack gets `/approve …/stop …/steer` for free.
- **Outbound** — `handle_outbound_to_slack` (`Chat Message.after_insert`) posts
  `direction=outbound, platform=slack` rows via `chat.postMessage`. Best-effort
  inside a savepoint — a Slack outage never breaks the gateway pipeline.

## Decisions

**D1 — Secrets in an encrypted single, not JSON.** A `Slack Config` single
doctype holds `bot_token` + `signing_secret` as **Password** fields (encrypted),
plus `default_agent_profile`, `bot_user_id`, `enabled`. Never store secrets in a
plain `config_json` (the established rule — the live MiniMax key lives in a
Password field too).

**D2 — Signature verification is the auth.** The webhook is guest-reachable; every
request is verified with Slack's scheme: `X-Slack-Signature = v0=HMAC-SHA256(secret,
"v0:{ts}:{body}")`, constant-time compared, with a 5-minute freshness window
(replay defence). Modelled on `connectors.core.verify_signature`.

**D3 — Reuse the routing + command spine.** `routing.resolve.resolve_profile`
(project lead → default) and `gateway.commands` are surface-agnostic; Slack uses
them unchanged. The only Slack-specific code is the transport + signature.

## Divergence from Hermes (disclosed)

- **frappe-adapted:** Hermes' Slack platform is an in-process asyncio adapter;
  Friday's is a webhook + row insert (the unified-gateway model). Same user-facing
  behaviour.
- **simplified (v1):** text messages only (no files/blocks/threads); a channel
  mention must be the literal `<@BOT>`. Blocks/threads are a follow-up.

## Operator setup (one-time, external)

Create a Slack app → add a bot token + signing secret to **Slack Config** in Desk
→ set `bot_user_id` + `default_agent_profile` + enable → point the app's Event
Subscriptions request URL at
`…/api/method/frappe.friday_core.surfaces.slack_adapter.receive_event` and
subscribe to `message.im` + `app_mention`.

## Tests

`tests/test_slack_adapter.py` (14, mock-based): signature good/bad/stale; bot-own
+ subtype skip; channel-no-mention skip; DM + mention write a correct inbound row;
slash command routes to `dispatch_command` (no conversational row); outbound posts
with the bearer token inside a savepoint and never raises.

**Migrate gate:** the `Slack Config` doctype is a schema change — run by the
coordinator before merge.
