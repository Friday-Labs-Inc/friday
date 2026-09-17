# CONTEXT

The vocabulary of this codebase, and which of its rules are real.

For agents and for anyone new. When your output names a domain concept — an
issue title, a test name, a comment, a refactor proposal — use the word as
defined here. If the concept you need isn't in this glossary, that's a signal:
either you're inventing language the project doesn't use, or there's a genuine
gap worth recording.

Decisions live in `docs/adr/`. Where this file and an ADR disagree, the ADR is
newer and wins — and the disagreement is a bug in one of them.

---

## What Friday is

**Frappe + Hermes.** A hard fork of the Frappe framework with the Hermes agent
ported into it, making an agentic orchestration platform that Friday Labs runs
for itself. Frappe supplies the substrate — DocTypes, roles, workflows, the
scheduler, background jobs. Hermes supplies the agent — the turn loop, context
assembly, compression, the gateway, memory. Friday is what they become
together: agents that act as themselves, under their own roles, with every
decision audited.

It is a **platform**, not a product. Products live in their own apps on their
own benches. See [ADR-0001](docs/adr/0001-friday-is-frappe-plus-hermes.md).

---

## The nouns

**Kernel** — `frappe/friday_core/`. Everything Friday adds to Frappe. Names no
product and no customer, not even in a comment; `tests/test_kernel_vocabulary.py`
fails the build otherwise. A domain reaches the kernel through seams in
`frappe/hooks.py`, never by being imported into it.

**Waist** — Hermes' own term for its core: the turn loop, gateway, session and
state, the core tool set, cron. Capability outside the waist (plugins, CLI, TUI,
optional skills, platform adapters) is an *edge*. Friday ports the waist and
nothing else. See [ADR-0008](docs/adr/0008-track-hermes-narrow-waist.md).

**Agent Profile** — one agent's identity: its role tier, permitted skills, LLM
provider, system prompt, and the Frappe **User** that backs it. An agent's roles
are its job description. The backing user is what makes an agent write
attributable.

**Actor** — who is acting right now: a `human`, an `agent`, or the `system`,
plus which one and under which trace. Carried in `frappe.local.actor`, stamped
onto every row an agent writes. Distinct from *user*: Frappe knows the user;
only Friday knows the actor.

**Skill** — a callable tool: description, `when_to_use`, JSON parameter schema,
the DocTypes and operations it needs, a risk level, and whether it requires
approval. A skill is a **row**, not a function — the handler is registered in
code, the definition lives in the database, and the two are kept in step by a
bootstrap that runs on every migrate.

**Handler** — the Python function behind a skill: `(skill_name, parameters) -> dict`.
Registered via the `friday_skill_handlers` hook so an app contributes skills
without the kernel importing it.

**Matrix** — the permission matrix: `{doctype: frozenset(operations)}` built
from the roles a profile holds. `evaluate` is pure and writes nothing;
`check` evaluates and records. The menu is filtered with `evaluate`, the call is
gated with `check` — two gates, so a stale cache cannot let anything through.

**Decision** — one allow-or-deny, recorded as a submitted **Permission Decision
Log** row carrying a snapshot of the matrix that produced it. Immutable; a
correction is a new row, never an edit.

**Execution Log** — one row per skill dispatch: parameters, result, status,
duration, tokens, and the decision that permitted it. Submitted (immutable) on
success, rejection, and pending-approval. Left in draft only on error, so it can
be inspected.

**Approval** — the human pause. A skill marked `requires_approval` creates a
**Workflow Request** and stops; a person resolves it with `/approve` or
`/deny`. The claim is a single-winner conditional update, so two approvers
cannot both fire the action.

**Turn** — one inbound message processed to one outbound reply. Bounded by an
iteration budget; journalled to **Turn Event** rows so a crashed turn resumes
instead of re-running.

**Session** — a conversation's continuity, keyed by `session_id` (a Raven
channel, a CLI uuid). Guarded by a Redis lock: a second message for a live
session queues, never drops.

**Chat Message** — the universal message row, inbound or outbound. It **is** the
contract between a surface and the engine; the gateway's chokepoint is an
`after_insert` hook on it.

**Surface** — a place humans reach the agent (Raven, Slack, CLI). A thin
row-in/row-out adapter, never agent logic. Surfaces never import the runner.

**Task** — a unit of agent work that outlives a turn: assigned, claimed with a
lease and a heartbeat, dependent on other tasks, and rolled up to a project.
Where delegation lands.

**Domain app** — a separate Frappe app carrying one business domain: its
pipeline, its personas, its skills, its surfaces. Installs onto the Friday
bench. `randompack_ai` is the first. A domain app is never part of the kernel.

**Domain Bundle** — the manifest that tells the kernel a DocType is a governed
work item: which Frappe Workflow drives it, and the field names the kernel needs
to name, link and reference it. The seam that lets a domain plug in without the
kernel knowing what it is.

**Transition Meta** — per-transition metadata on a workflow: the phase key, the
execution mode, which agent role runs it, which skills it needs, its prompt. A
pipeline is **data**, shipped by the domain app and seeded on migrate.

**Connector** — a governed integration: signed inbound events persisted as
**Connector Event** rows, and outbound calls through a signing client. How a
product talks to Friday.

---

## The rules that are real

- **One chokepoint per concern.** Every inbound message goes through
  `gateway.service.handle_inbound`; every skill call goes through
  `agent_runner.dispatcher.dispatch`. A second path is a bug, not a shortcut.
- **The dispatcher is where governance happens**, not the gateway — so a task,
  a cron job, or a future surface cannot route around it.
- **Audit rows are submitted, never updated.** Corrections are new rows.
- **An agent acts as its own user.** `acting_as` sets the user and the actor and
  restores both, even when the body raises.
- **If Friday is down, every product keeps working by hand.** Nothing on a
  product's critical path calls Friday and waits.
  See [ADR-0005](docs/adr/0005-friday-is-never-a-dependency.md).
- **The kernel names no product.** Enforced by a test.
- **Failure-isolated seams.** One broken domain app must not take the kernel
  down; hook failures are logged, never raised.

## Words we deliberately don't use

- **Plugin** for a domain app — Frappe's word is *app*, and the mechanism is
  hooks. Say **domain app**.
- **Tool** for a skill in Friday's own prose — *tool* is what the LLM sees;
  *skill* is what Friday governs. (Hermes says tool; that's their word.)
- **Agent** for a background worker — a worker runs turns; an **agent** is an
  Agent Profile with an identity and roles.
- **User** when you mean **actor**. See above.
- **Framework** for Friday — it's a **platform** we operate, not something
  others install. See [ADR-0003](docs/adr/0003-internal-enterprise-platform.md).

---

## What is NOT true yet

This section exists because the previous documentation set lost the distinction
between decided, built, and observed working. Keep it honest or delete it.

- **The governed loop has never run end to end** — message in, LLM, skill
  dispatched, submitted Execution Log out. Every "COMPLETE" in the old port
  ledger means *code exists*, never *observed running*.
- **CI runs zero tests.** `tests.yml` names a module that collects nothing and
  ends every step in `|| true`. 108 test modules go unexecuted.
  See [ADR-0010](docs/adr/0010-blocking-test-ratchet.md).
- **Skills do not run sandboxed.** Only `create_note` is in the sandbox image;
  the dispatcher runs everything else in-process.
- **The seam to RandomPack has never carried a real message.** No subscriber,
  no shared secret.
- **Cost and quota are not enforced** anywhere.
