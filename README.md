# Friday

**A governed agent kernel for Frappe.**

Most AI agent frameworks give the model your hands: it acts as you, with your
permissions, and nothing records why. Friday inverts that. An agent here is an
*employee*, not a borrowed session:

- **It acts as itself.** Every Agent Profile has its own Frappe User. Its roles
  are its job description — the same permission engine that governs a human
  governs the agent.
- **Every decision is checked before it runs** against a permission matrix, and
  written to an immutable Permission Decision Log.
- **Every execution is recorded** in a submitted Execution Log row.
- **High-risk skills pause** for a human at an approval gate.
- **Long work is durable.** A task pipeline with claim locks, lease tokens and a
  reconciler survives restarts, lost enqueues and stale executors.

## Install

Friday is an ordinary Frappe app. It requires **Frappe v16** and **Raven**
(Friday's chat front door — the bot you DM, per-project channels, the war room):

```bash
bench get-app --branch develop https://github.com/The-Commit-Company/raven
bench get-app https://github.com/Friday-Labs-Inc/friday
bench --site <site> install-app raven
bench --site <site> install-app friday
bench --site <site> migrate
bench --site <site> friday setup        # provider + agent profile, one step
```

The durable pipeline needs its own worker — add to your Procfile / supervisor:

```
friday-worker: bench worker --queue friday
```

PostgreSQL unlocks semantic and full-text memory recall (pgvector + tsvector);
on MariaDB, recall degrades to recency-only with no other loss.

## Architecture in one paragraph

Everything inbound — CLI, Raven, Slack, A2A, a signed webhook — becomes a Chat
Message, which passes through one gateway chokepoint. The agent runner builds a
prompt (system frame + history + memory + tools), calls a provider (MiniMax,
OpenAI, Anthropic, with OAuth and failover), and any tool call goes through the
dispatcher: permission check → approval gate → execution → audit row. Work too
long for a turn becomes a Task on the durable pipeline.

## Adding your own domain

Friday ships **no** business domain. A domain is data plus a thin app, wired
through published seams — never by editing this kernel:

| Seam | What an app contributes |
|---|---|
| `Domain Bundle` record | a work-item DocType + its Frappe Workflow + per-phase prompts, skills and agent personas |
| `friday_skill_handlers` | modules that register skill handlers |
| `friday_skill_definitions` | definition refreshers, re-run on every migrate |
| `friday_task_transition_hooks` | `fn(doc, state)` after every Task transition |
| `friday_reference_registry` | `@REC-0001` reference prefixes |

[`design_studio`](https://github.com/Friday-Labs-Inc/design_studio) is a
worked example: an entire design-studio pipeline — phases, gates, personas,
client surfaces — with no kernel changes.

## Documentation

| Doc | What it is |
|---|---|
| [START_HERE.md](START_HERE.md) | Front door for anyone — human or AI — picking the project up |
| [CODEX.md](CODEX.md) | The implementation brief |
| [docs/install.md](docs/install.md) | Install, provider setup, the sandbox image |
| [docs/architecture.md](docs/architecture.md) | How the pieces fit |
| [docs/design/](docs/design/00-README.md) | The full design dossier — ~90 documents, each with the decision and its reasoning |
| [docs/rollouts/](docs/rollouts/) | What actually shipped, slice by slice |
| [CONTRIBUTING.md](CONTRIBUTING.md) · [docs/contributing/AI_CONTRIBUTORS.md](docs/contributing/AI_CONTRIBUTORS.md) | PR workflow, and the policy for AI contributors |

## History

Friday began as a hard fork of Frappe v16. It is now an app: the kernel modifies
no framework file, so `bench update` works, upstream security releases arrive
normally, and Friday installs beside ERPNext. The one upstream fix it still
carries is documented in `friday/friday_core/compat.py`.

Derived from [Frappe Framework](https://github.com/frappe/frappe), GPL v3.
