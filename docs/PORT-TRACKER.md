# Friday Port Tracker — the one list to watch

**This is your single tracker.** Every Hermes core capability, in plain English,
with a status. When every line that isn't ⬛ is ✅, the port is done.

## How to read the status
| | meaning |
|---|---|
| ✅ | **Done + faithful** — built; either a true 1:1 Hermes copy **or** Friday's own by-design build with divergences disclosed (each line says which) |
| 🟨 | **Done but loose** — works, but rebuilt loosely; needs an exact re-do |
| 🟡 | **Partly built** — started, not finished |
| ⬜ | **Not built yet** — needed |
| ⬛ | **Skip** — Frappe/Raven already gives it, or it's not for your business |

## WHERE WE ARE RIGHT NOW (the honest headline)
- **The safety + governance layer is the most done** — permissions, audit trail,
  human approval, sandbox. This is Friday's whole edge, and it's real.
- **The thinking engine is now faithful** — the loop, output-cleaning, and
  compression are copied from Hermes exactly (or honestly disclosed where they
  diverge by design); the 3 model providers are Friday's own clean build, audited.
- **The agent's "hands" (tools) and "learning" are mostly empty** — this is the
  big gap.
- **Your product (the skills that do brand work) is 1 of many.**
- **Talking to it works** (command line); nicer chat surfaces aren't built.

So: **a real, governed agent that runs — on a thin engine, with almost no skills
yet.** Foundation: solid. Product: barely started.

---

## 1. The thinking loop (the agent's brain)
*Think → act → look at the result → think again, until the job's done.*
- ✅ The loop itself — faithful port of Hermes' core. The 4,350 lines were mostly streaming/40-provider/display that Friday correctly skips; the two real gaps (unicode + empty-retry) are now closed.
- ✅ Step limit (stops after 15 cycles)
- ✅ Don't-repeat-the-same-action-twice
- ⬜ Streaming (reply appears word-by-word as it's written)
- ⬜ Interrupt (stop it mid-thought)
- ✅ "Grace call" — an empty model response is retried up to 3× before giving up (#63)

## 2. Talking to AI models
*Which AI brain powers the agent.*
- ✅ Provider setup as a database record (no config files) — and a `setup` command
- ✅ MiniMax, OpenAI, Anthropic — Friday's own clean 3-provider build (audited: no false "matches Hermes" claims; not a copy *by design* — Hermes' 40-provider sprawl is correctly skipped)
- ⬛ ~37 other model brands (Gemini, Bedrock, xAI…) — skip; add only if needed
- ⬛ Key pool + rotation — skip (you use one key)
- 🟡 Model info / pricing list — pricing is now operator-set rates on the provider row (#69); per-model context-window metadata still uses one default
- ✅ Usage + cost tracking — one LLM Usage Log row per model call, tokens + estimated USD (#69, verified live)
- ✅ Rate-limit handling — a 429's Retry-After header is honored, capped at 120s (#66)

## 3. Cleaning the model's output
*Make raw model text safe and clean before it reaches anyone.*
- ✅ Strip the model's private "thinking" out of replies — **faithful copy (#59)**
- ✅ Repair broken JSON in the agent's actions so they don't fail — **faithful copy (#60)**
- ✅ Fix bad/unicode characters that crash the API — **faithful copy (#62)**
- ⬜ Strip images / non-text for models that can't take them

## 4. Memory & context
*What the agent remembers and carries into each reply.*
- ✅ Compress long conversations — summary text now verbatim Hermes, threshold corrected to 0.50, divergences disclosed (#64)
- ✅ Use a cheaper model to write those summaries
- ✅ Context engine (v0.1 scope) — memory recall + @-reference expansion + compression decide each turn's context
- ✅ @-references — @BB-0001-style record refs, permission-gated, not-found reported (#80)
- ✅ Long-term memory — Agent Memory rows + `remember` skill + fenced every-turn recall, proven across sessions (#80)

## 5. The tools the agent can use (its hands)
*What the agent can actually DO.*
- ✅ Every skill IS a tool (database record)
- ✅ **Delegate / sub-agents** — delegate-task, proven live (#75)
- ⬜ **MCP** (plug in outside tools without coding each one) — needed for integrations
- ⬜ Browser control · ⬜ Computer use · ⬜ Code execution · ⬜ Web search
- ⬛ Shell/terminal — skip (banned in v0.1) · ⬛ Image/video/voice/vision — skip
- ⬛ Discord / Feishu / etc. — skip (those are business skills, add on demand)
- ✅ Memory tool (`remember`, #80) · ⬜ Checkpoint / interrupt
- ✅ Send a message back to the human
- 🟡 To-do / kanban / scheduled jobs (you have the tracker + Frappe's scheduler)

## 6. Skills (the agent's playbooks) + Learning
*The agent's know-how — and whether it can teach itself.*
- ✅ Skill format (a database record)
- ✅ Skill menu, filtered by what each agent is allowed to use
- 🟡 Skill usage stats
- ⬜ **Curator** (auto-promote good skills, retire stale ones)
- ⬜ **Learner** (the agent writes NEW skills from experience) — Hermes' signature "learning loop"
- ✅ Memory / recall (#80)
- ⬜ Safety audit for self-written skills
- 🟡 **YOUR business skills** — brand directions live (#73); copy/mockups/site next. 5 skills total now.

## 7. Permissions & safety (governance — your edge)
*Who's allowed to do what, and proof of everything that happened.*
- ✅ Deny-by-default permission check on every action (Frappe roles)
- ✅ Immutable audit log of every action + every allow/deny
- ✅ Human approval gate for risky actions
- ✅ Locked Docker box per skill run
- ✅ One scoped, short-lived token per run
- ⬜ Threat / bad-URL / unsafe-file guards

## 8. Running skills safely (the sandbox)
- ✅ Docker box + warm pool (fast starts)
- ⬛ 5 other runtimes (SSH, Modal, Daytona…) — skip (one safe runtime)
- 🟡 Network lockdown (only allowed hosts)

## 9. Talking to humans (the front door)
- ✅ One gateway every message flows through
- ✅ Command-line chat + setup + setup-raven
- ✅ Raven — team chat surface live, War Room lit (#77)
- ⬜ Telegram / Slack / WhatsApp / … — add per need
- ⬜ Agent-to-agent messaging

## 10. Coordinating many agents (orchestration)
*A supervisor handing work to specialist agents — the multi-agent vision.*
- 🟡 Work list (Project / Task / Issue)
- ✅ Orchestrator capability matcher — in live use by delegation (#75)
- ⬜ "Waiting on another agent" (dependency)
- ✅ A failed task auto-files a ticket
- ✅ Sub-agents (see §5, #75)

## 11. Command-line & setup
- ✅ `friday chat` (talk to an agent)
- ✅ `friday setup` (configure a model in one command)
- ⬛ login / backup / cron commands — skip (Frappe + bench already do these)

## 12. Behind-the-scenes plumbing
- ⬛ Credential pool / storage — skip (single key)
- ✅ Usage + cost accounting (#69 — see §2)
- ✅ Rate-limit tracker (#66 — see §2)
- ✅ Prompt caching — Anthropic system-prefix cache_control, ~75% input savings (#68)
- ⬜ Conversation titles, onboarding, misc helpers

---

## The two next paths (pick one, anytime)
1. **Make the engine solid + faithful** — turn the 🟨/🟡 rows into ✅ by copying
   Hermes exactly (like we just did for §3).
2. **Build the first real product skill** — turn one ⬜ in §6 into a working ✅
   (the agent producing real brand work).

*Updated as we ship. Open this file anytime to see where we are.*
