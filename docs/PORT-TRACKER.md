# Friday Port Tracker — the one list to watch

**This is your single tracker.** Every Hermes core capability, in plain English,
with a status. When every line that isn't ⬛ is ✅, the port is done.

## How to read the status
| | meaning |
|---|---|
| ✅ | **Done + faithful** — built, and it's a true 1:1 copy of Hermes |
| 🟨 | **Done but loose** — works, but rebuilt loosely; needs an exact re-do |
| 🟡 | **Partly built** — started, not finished |
| ⬜ | **Not built yet** — needed |
| ⬛ | **Skip** — Frappe/Raven already gives it, or it's not for your business |

## WHERE WE ARE RIGHT NOW (the honest headline)
- **The safety + governance layer is the most done** — permissions, audit trail,
  human approval, sandbox. This is Friday's whole edge, and it's real.
- **The thinking engine runs but is shallow** — a basic version of the loop, two
  pieces now faithfully copied, the rest still loose.
- **The agent's "hands" (tools) and "learning" are mostly empty** — this is the
  big gap.
- **Your product (the skills that do brand work) is 1 of many.**
- **Talking to it works** (command line); nicer chat surfaces aren't built.

So: **a real, governed agent that runs — on a thin engine, with almost no skills
yet.** Foundation: solid. Product: barely started.

---

## 1. The thinking loop (the agent's brain)
*Think → act → look at the result → think again, until the job's done.*
- 🟨 The loop itself — runs, but a thin 180-line version of Hermes' 4,350-line one
- ✅ Step limit (stops after 15 cycles)
- ✅ Don't-repeat-the-same-action-twice
- ⬜ Streaming (reply appears word-by-word as it's written)
- ⬜ Interrupt (stop it mid-thought)
- ⬜ "Grace call" (one more attempt when it's stuck)

## 2. Talking to AI models
*Which AI brain powers the agent.*
- ✅ Provider setup as a database record (no config files) — and a `setup` command
- 🟨 MiniMax, OpenAI, Anthropic — they work, but rebuilt, not exactly copied
- ⬛ ~37 other model brands (Gemini, Bedrock, xAI…) — skip; add only if needed
- ⬛ Key pool + rotation — skip (you use one key)
- 🟡 Model info / pricing list
- 🟡 Usage + cost tracking
- ⬜ Rate-limit handling (slow down when the model says "too fast")

## 3. Cleaning the model's output
*Make raw model text safe and clean before it reaches anyone.*
- ✅ Strip the model's private "thinking" out of replies — **faithful copy (#59)**
- ✅ Repair broken JSON in the agent's actions so they don't fail — **faithful copy (#60)**
- ⬜ Fix bad/unicode characters that crash the API
- ⬜ Strip images / non-text for models that can't take them

## 4. Memory & context
*What the agent remembers and carries into each reply.*
- 🟡 Compress long conversations (summarize old turns) — built, loose
- ✅ Use a cheaper model to write those summaries
- ⬜ Context engine (deciding what to include each turn)
- ⬜ @-references (point the agent at a file or record)
- ⬜ Long-term memory / recall across sessions

## 5. The tools the agent can use (its hands)
*What the agent can actually DO.*
- ✅ Every skill IS a tool (database record)
- ⬜ **Delegate / sub-agents** (one agent spawns helpers) — needed for many-agent work
- ⬜ **MCP** (plug in outside tools without coding each one) — needed for integrations
- ⬜ Browser control · ⬜ Computer use · ⬜ Code execution · ⬜ Web search
- ⬛ Shell/terminal — skip (banned in v0.1) · ⬛ Image/video/voice/vision — skip
- ⬛ Discord / Feishu / etc. — skip (those are business skills, add on demand)
- ⬜ Memory tool · ⬜ Checkpoint / interrupt
- ✅ Send a message back to the human
- 🟡 To-do / kanban / scheduled jobs (you have the tracker + Frappe's scheduler)

## 6. Skills (the agent's playbooks) + Learning
*The agent's know-how — and whether it can teach itself.*
- ✅ Skill format (a database record)
- ✅ Skill menu, filtered by what each agent is allowed to use
- 🟡 Skill usage stats
- ⬜ **Curator** (auto-promote good skills, retire stale ones)
- ⬜ **Learner** (the agent writes NEW skills from experience) — Hermes' signature "learning loop"
- ⬜ Memory / recall
- ⬜ Safety audit for self-written skills
- ⬜ **YOUR business skills** (brand directions, copy, mockups, the website) — **the product. 1 built so far.**

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
- 🟡 Command-line chat (works) + setup (just built)
- ⬜ Raven (chat inside Frappe) — the first real human surface
- ⬜ Telegram / Slack / WhatsApp / … — add per need
- ⬜ Agent-to-agent messaging

## 10. Coordinating many agents (orchestration)
*A supervisor handing work to specialist agents — the multi-agent vision.*
- 🟡 Work list (Project / Task / Issue)
- 🟡 Orchestrator that matches a task to a capable agent
- ⬜ "Waiting on another agent" (dependency)
- ✅ A failed task auto-files a ticket
- ⬜ Sub-agents (see §5)

## 11. Command-line & setup
- ✅ `friday chat` (talk to an agent)
- ✅ `friday setup` (configure a model in one command)
- ⬛ login / backup / cron commands — skip (Frappe + bench already do these)

## 12. Behind-the-scenes plumbing
- ⬛ Credential pool / storage — skip (single key)
- 🟡 Usage + cost accounting
- ⬜ Rate-limit tracker
- ⬜ Prompt caching (cuts the model bill on every turn)
- ⬜ Conversation titles, onboarding, misc helpers

---

## The two next paths (pick one, anytime)
1. **Make the engine solid + faithful** — turn the 🟨/🟡 rows into ✅ by copying
   Hermes exactly (like we just did for §3).
2. **Build the first real product skill** — turn one ⬜ in §6 into a working ✅
   (the agent producing real brand work).

*Updated as we ship. Open this file anytime to see where we are.*
