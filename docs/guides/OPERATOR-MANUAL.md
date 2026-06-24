# Friday — Operator Manual

> **Who this is for.** The person *running* Friday — configuring agents and trying
> features. Not a developer guide (that's `docs/contributing/AI_PROJECT_BRIEFING.md`).
> This tells you, in plain English, **what Friday can do today, how to set each
> thing up, and how to test it.**
>
> **Where you work — two places:**
> - **Desk** (`/app`, log in as Administrator) — the admin UI where you
>   *configure* things (agents, providers, cron jobs, roles).
> - **Raven** (`/raven`) — the chat app where you *talk to* and *control* agents.
>   This is Friday's primary "talk to your agents like coworkers" surface.

---

## 0. One-time prerequisites

Everything below depends on these. On the live AWS box (`ai.randompack.com`)
they're already in place — listed so you understand the dependencies and can
check them in Desk.

| Prereq | Check in Desk | Why it's needed |
|---|---|---|
| **LLM provider + key** | `LLM Provider` → one **Active** row (MiniMax), key stored encrypted | No agent can think without a model |
| **An active agent** | `Agent Profile` → at least one **Active** profile (an Orchestrator) | The thing you talk to |
| **Raven provisioned** | `Raven Bot` → "Friday" exists; a War Room channel exists | The chat surface + the bot's identity |
| **Your roles** | `User` → your account → Roles → **Friday Operator** (and **Friday Cron Manager** for cron) | Gates `/approve`, `/stop`, and cron |

**Rebuilding from scratch?** Two commands (run on the server):
```bash
FRIDAY_API_KEY=sk-... bench --site <site> friday setup --provider-type minimax   # provider + agent
bench --site <site> friday setup-raven --install                                 # Raven bot + channel
```

---

## 1. Talk to an agent ⭐ (the core)

**What.** Message the Friday bot in Raven; it answers as a real governed agent —
it thinks, can use tools, and replies.

**Configure.** Nothing beyond §0. (In a channel, the bot only answers when
**@mentioned**; in a DM, it answers every message.)

**Test.** Open a DM with **Friday** in Raven → "What can you help me with?"

**Expect.** A real reply authored by the agent. This is the foundation every
other feature rides on.

---

## 2. Run real project work

**What.** Agents create Projects + Tasks, run a durable pipeline
(dispatch → run → auto-heal), and produce downloadable deliverables (Markdown + PDF).

**Configure.** Nothing beyond §0.

**Test.** Ask an Orchestrator to do a multi-step job: *"Draft a one-page brief on
X and save it."* Watch in Desk: the `Project` and `Task` lists, and the **Task
Pipeline Kanban** (Projects workspace).

**Expect.** Tasks move `Pending → Assigned → Executing → Completed`; a finished
task attaches real deliverable files you can download.

---

## 3. The human-approval gate — from chat 🔒

**What.** A risky action pauses and waits for a human. You approve or deny **from
Raven**, not just Desk. This is Friday's governance headline.

**Configure.** You must have the **Friday Operator** role (§0).

**Test.** When an agent hits a gated action it posts that it needs approval (a
`Workflow Request` goes **Pending**). In the channel type:
- `/approve` — approve the channel's oldest pending request (or `/approve <id>`)
- `/deny too risky` — reject it, with a reason

**Expect.** `/approve` flips the request to **Approved** *and resumes the paused
work*; `/deny` rejects it and records your reason. *(AWS-verified end-to-end.)*

---

## 4. Control a running agent (slash commands)

**What.** Operator commands in any Raven channel. `/status` and `/help` are open
to anyone; the rest need **Friday Operator**.

| Command | Does | Test → Expect |
|---|---|---|
| `/help` | List commands | Bot posts the list |
| `/status` | This channel's state | "N pending approval(s)" |
| `/approve` · `/deny` | The gate (§3) | Resumes / rejects |
| `/stop` | Interrupt the running turn **and its delegated work** | "🛑 Stopping this turn and N delegated task(s)" |
| `/stop force` | **Hard-kill** a wedged turn immediately | "💀 Force-killed: N job(s) cancelled…"; tasks flip to `ForceKilled` |
| `/steer <text>` | Nudge a running turn without stopping it | Agent adapts on its next step |

**Good to know (not bugs):**
- `/stop` and `/steer` take effect at the agent's **next thinking step** (after its
  current model call returns), not mid-sentence.
- `/stop force` is the escalation for a turn stuck inside one long operation — it
  kills the underlying job immediately. Use `/stop` first; `/stop force` when that
  won't land.
- A plain message sent while an agent is busy **queues** and runs after — it does
  not interrupt. Only `/stop`/`/steer` do.

---

## 5. Scheduled agent runs (Cron Jobs) ⏰

**What.** "Run agent X with prompt P on schedule S, deliver the result to T." A
scheduled run is a normal durable Task under the hood.

**Configure.** New **Cron Job** in Desk (needs the **Friday Cron Manager** role):
- **Agent Profile** — who runs it
- **Prompt** — e.g. *"Summarise today's completed tasks"*
- **Schedule Kind** + **Schedule Expression**:
  - `cron` → `0 9 * * *` (every day 9am)
  - `interval` → `30` (every 30 minutes)
  - `once` → `2026-07-01T09:00:00`
- **Deliver To** — `local` (a private file), or `raven:<channel-id>` (post into a channel)
- **Repeat Times** — `0` = forever, `1` = once, `N` = N times

**Test.** Create one with `interval = 1` (every minute) and `Deliver To = local`.

**Expect.** Within a minute a **Task** spawns and runs; the result is saved as a
private **File** (open it from the job's `Last Task`). Switch `Deliver To` to
`raven:<channel-id>` and the result posts into that channel. With `Repeat Times =
1`, the job auto-disables after one run (the row stays, for history).

---

## 6. Supporting capabilities (configured, mostly automatic)

- **Memory** — agents remember durable facts and recall them by relevance
  (`Agent Memory` in Desk). Mostly automatic; you can read/seed memories.
- **Skills + permissions** — every agent action is permission-checked and logged
  (`Skill`, `Execution Log`). High-risk skills trigger the approval gate (§3).
- **Connectors** — inbound events from external systems (e.g. RandomPack) flow in
  through a signed webhook (`Connector`, `Connector Event`).
- **Per-project channels** — creating a Project provisions its own Raven channel;
  the agent posts deliverables there on request.

---

## 7. What's *not* there yet (so expectations are set)

- **Agents scheduling their own cron jobs** — you create cron jobs in Desk; an
  agent doing it via chat is a planned next slice.
- **Lifecycle hook plugins** — custom code on agent start/step/end is not exposed
  (Friday already emits lifecycle *events* internally for the console/audit).
- **A second chat surface** (Slack/Telegram) — Raven is the surface today.

---

## Quick-start test checklist

Run these in order on `ai.randompack.com` (as Administrator, with **Friday
Operator** + **Friday Cron Manager** roles):

1. [ ] DM **Friday** in Raven → get a reply. *(§1)*
2. [ ] `/help` in a channel → bot lists the commands. *(§4)*
3. [ ] Ask for a multi-step job → watch Tasks complete + a deliverable attach. *(§2)*
4. [ ] Trigger an approval gate → `/approve` → the paused work resumes. *(§3)*
5. [ ] During a long run: `/steer use the staging data` → agent adapts; `/stop` → it ends. *(§4)*
6. [ ] Create a Cron Job (`interval 1`, `deliver local`) → a result File appears within a minute. *(§5)*
