# Design 58 — The Raven surface: Friday in your team's chat

**Status: LOCKED 2026-06-11 — all six decisions (Q1–Q6) accepted as recommended ("lock all").**

## What this is, in plain English

Your team opens Raven (Frappe's Slack-like chat app), DMs the Friday bot or
mentions it in a channel, and gets governed agent replies — same engine, same
audit trail, same cost accounting as the CLI, but for the whole team. Plus
the War Room comes alive: the task/delegation updates the code already emits
start appearing in a real channel.

## Q1 — Bundled, separate, or automated? (the user's question)

*Recommendation:* **Separate upstream app + full automation. Never bundled.**

| Option | Verdict |
|---|---|
| Bundle/fork Raven into Friday | ❌ Friday already maintains one hard fork (Frappe). Forking Raven too means owning a fast-moving React+Python codebase's merge conflicts forever — for zero architectural gain. |
| Separate app, manual install | 🟡 Works (standard `bench get-app` + `install-app`) but leaves setup friction. |
| **Separate app + `bench friday setup-raven`** | ✅ One command: detects Raven; with `--install` runs `get-app` + `install-app` + build for you; then **seeds everything** (bot, channels, wiring). Idempotent, like `friday setup`. |

The integration is loose-coupled by design: Friday's adapter only reads/writes
rows and is guarded by `table_exists("Raven Channel")` — the exact pattern the
War Room publisher already uses. **Friday runs identically with or without
Raven installed**; installing Raven simply lights the surface up.

## Q2 — The adapter contract (rows in, rows out — design 47/55 honored)

*Recommendation:* two thin hooks, no agent logic in either:

```
INBOUND:  Raven Message created (DM to the bot, or @mention in a channel)
          → hook writes ONE inbound Chat Message row (platform "raven",
            session = the Raven channel id)
          → Gateway v2 takes it from there (friday worker, locks, audit)

OUTBOUND: Chat Message outbound row written for platform "raven"
          → hook posts it back as a Raven Message from the agent bot
```

The adapter never imports `agent_runner` (the one rule). Cross-app
`doc_events` on Raven's DocTypes are wired from Friday's hooks and are
no-ops when Raven is absent.

## Q3 — When does the agent answer?

*Recommendation (v0.1):* **DMs to the bot: always. Channels: only when
@mentioned.** A channel where people are talking to each other is not an
agent prompt; a mention is. (Hermes' gateway has rich per-channel policy —
deferred; disclosed.)

## Q4 — Identity & sessions

*Recommendation:* seed ONE bot user ("Friday") bound to the default Agent
Profile via `Chat Platform.default_agent_profile` (the routing field that
already exists). Session mapping: one session per DM thread, one per channel
— so channel context is shared, DM context is private. Multi-bot (one Raven
bot per Agent Profile, e.g. a @Copywriter bot) is the disclosed follow-up —
the delegation skill already covers specialist access meanwhile.

## Q5 — What `setup-raven` seeds

*Recommendation:* idempotently — (a) the Friday bot user; (b) a
**FRIDAY_WAR_ROOM** channel (the existing warroom publisher activates by
itself the moment the table exists — zero new code); (c) a `Chat Platform`
row `raven` (dispatch_mode "async" → the dedicated worker, default profile
"Friday"); (d) bot membership in the War Room. With `--install`: runs
`bench get-app raven` + `install-app` + build first, with honest failure
messages (network, node version) rather than silent retries.

## Q6 — Loop prevention & governance

*Recommendation:* the inbound hook ignores (a) messages authored by any
Friday bot (no self-loops), (b) edits/system messages. Outbound posting runs
as the bot user. No new skill and no new permission class — a surface is
gateway plumbing, not an agent capability; everything the agent *does*
remains gated exactly as today.

## Honest risks (verified during implementation, disclosed now)

- **Version compatibility**: Raven targets stock Frappe v15/v16; Friday is a
  v16 fork. APIs should hold — the implementation starts with an
  install-and-smoke-test before any adapter code.
- **Raven's bot API surface** (Raven Bot doctype / message hooks) varies by
  version; the adapter pins to row-level DocTypes (Message/Channel), the
  most stable layer.

## What lands on disk (when locked)

- `surfaces/raven_adapter.py` — the two hooks (inbound mention/DM → row;
  outbound row → Raven post), table-guarded.
- `cli` — `setup-raven` command (`--install` optional).
- `skills/`-style bootstrap: `bootstrap_raven.provision` (bot, channels,
  platform row, memberships).
- hooks.py — cross-app doc_events (no-op without Raven).
- Tests FIRST (mocked Raven rows): mention/DM filtering, self-loop guard,
  session mapping, outbound post shape, absent-Raven no-ops.
- Live proof: install Raven on the bench via the command, DM the bot, get a
  governed reply; delegation War-Room posts appearing in the channel.
