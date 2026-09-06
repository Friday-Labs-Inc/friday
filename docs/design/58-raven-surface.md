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


---

## Locked decision (2026-09-06) — Raven is the surface, Friday is the engine

Raven 3.0 ships **Raven AI**: its own agent runtime (OpenAI Agents SDK; OpenAI,
Google, or any OpenAI-compatible endpoint) whose bots can call eighteen kinds of
function — Create / Update / Delete / Submit / Cancel Document, Set Value, and
`Custom Function`, an arbitrary dotted Python path an admin types into a field.
Those calls run as **the human who typed the message**, using Frappe's ordinary
document permissions.

That is a reasonable design for a chat assistant. It is not Friday's.

| | Raven AI | Friday |
|---|---|---|
| Acts as | the human who typed | the agent's own Frappe User — its roles are its job description |
| Before acting | Frappe document permissions | permission matrix check per skill, logged immutably |
| After acting | nothing recorded | submitted Execution Log row |
| High-risk actions | proceed | approval gate — pauses for a human |
| Models | OpenAI-compatible | MiniMax, OpenAI, Anthropic (incl. OAuth), with failover |
| Long-running work | one chat turn | durable task pipeline, survives restarts |

**The decision: Raven supplies the surface — channels, DMs, @mentions, presence,
mobile, the UI. Friday supplies the intelligence. Raven AI stays off.**

The reason is not feature envy, it is auditability. Two engines writing to the
same records means "which one did this?" has no answer for half the surface, and
Friday's entire product claim is that an AI agent has a badge, a job description,
and a timesheet. An asterisk on that claim is worth more than the convenience.

### How the decision is enforced

- `surfaces/bootstrap_raven._ensure_bot` pins `is_ai_bot = 0` on Friday's bot at
  creation, and resets it (with a warning) if it is ever switched on — that flag
  would route turns through Raven AI and past the permission engine entirely.
- `health/pipeline_health` reports `surfaces.raven_ai_enabled`, and a site with
  Raven's AI integration switched on reads **degraded**: not a Friday outage, a
  governance gap the operator should see.
- `setup/wizard.setup_status` returns `surfaces.engine = "friday"` alongside the
  Raven AI state, so the choice is visible during setup rather than discovered
  later.

### Revisit when

A studio asks why the Raven AI toggle exists if it cannot be used. The answer
then is not to switch it on, but to make Raven's function layer call **Friday
skills** — one governed engine behind two front doors. That is a v2 design, not
a reversal of this one.
