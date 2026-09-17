# START HERE

> **For anyone — human or AI — who just landed on Friday and wants to help.**
>
> Read this in 5 minutes. By the end, you'll know exactly what to do next.

---

## What Is Friday, In Plain English

Friday is an AI agent system for businesses. The kind of AI that doesn't just chat — it can actually do work inside a company's software. Create records. Draft purchase orders. Send emails. Track tasks.

**The catch:** today's AI agents are reckless. They have no rules, no audit trail, no permissions. A business owner cannot trust them. Friday fixes that. Every action an AI agent takes inside Friday is:

- **Permission-checked** — like an employee with a job role
- **Logged** — like a receipt for every action
- **Sandboxed** — like working in a locked room, not the whole office
- **Reviewed** — humans can pause, approve, or revoke anything

Friday is built on **Frappe v16** (a proven business software framework from Mumbai) and made in India, for the world.

That's the project in 6 sentences.

---

## Where Friday Is Right Now (Be Honest, Set Expectations)

**Slice 1 is built and verified. The other 8 slices are not.**

What that means concretely:

- The repo is a fork of Frappe v16 with a `friday_core` module added.
- About 10 empty DocTypes exist (Agent Profile, Agent Task, Chat Message, Execution Log, etc.) — the data structures the rest of Friday will hang off.
- A `bench` env runs locally against PostgreSQL 17 with `pgvector` and `pg_trgm` enabled.
- Slice 1 tests pass: `bench --site friday.localhost run-tests --module frappe.friday_core.tests.test_doctypes_exist`.
- **No agent logic, no permission engine, no chat handling, no skill execution yet.** That's slices 2–9.

If you want to **build a slice from scratch**, today is the right day. If you want to **plug into a working system**, come back after slice 5 or so.

**Operating mode (v0.1):** one human (`@iamfriday86`) + one AI (`fridaylabs`), trunk-based, small PRs, sponsor-approved merges. The fuller AI contributor governance in `docs/contributing/AI_CONTRIBUTORS.md` is deferred until there's a second contributor.

---

## Are You Human or AI? Both Are Welcome

Friday is one of the very few open-source projects that **officially accepts AI agents as contributors**, alongside humans. Same rules apply to both:

- Write a proposal before coding
- Work in a sandboxed branch
- Tests must pass
- A human reviewer must sign off
- Your track record is public

**If you are an AI agent reading this:** continue to §3 of `docs/contributing/AI_CONTRIBUTORS.md` for your registration path. Your human sponsor opens an issue, you get added, you start at Level 0 and earn up.

**If you are a human:** continue below. The path is simpler — read `CONTRIBUTING.md` and pick a starter task from §5 of this document.

---

## The Map of This Repository

When you land here cold, the file tree looks intimidating. Here's what each file is actually for, in priority order:

| File | What it tells you | Read it when |
|---|---|---|
| `START_HERE.md` | This file — your entry point | Right now |
| `README.md` | Project overview | First minute |
| `CODEX.md` | Step-by-step build plan for Phase 1 | You want to write code |
| `CONTRIBUTING.md` | How to submit PRs | Before opening a PR |
| `docs/contributing/AI_CONTRIBUTORS.md` | Rules for AI agents | You ARE an AI, or sponsor one |
| `docs/design/00-README.md` | Index of all design docs | You want depth |
| `docs/design/42-phase-one-authority-contract.md` | What Phase 1 must include | Before designing anything |
| `docs/design/10-agent-execution-guide.md` | The 9 slices to build | You'll write a slice |
| `docs/design/11-agent-validation-checklist.md` | How to know a slice is done | Before submitting a slice |
| `docs/decisions/spike-results.md` | All locked stack decisions | Don't re-open these |
| `docs/ROADMAP.md` | What ships when | You're planning ahead |
| `LICENSE` | GPL v3 | If you care about licensing |
| `SECURITY.md` | How to report vulnerabilities | Found a security issue |

**Rule of thumb:** if you only read three files, read this one, `CODEX.md`, and `docs/design/42-phase-one-authority-contract.md`. Those three tell you the entire plan.

---

## What You Can Actually Do Today

The project needs different kinds of help. Pick the one that matches your skills.

### 🛠️ I want to write code

The Phase 1 build plan is in `CODEX.md`. It splits the work into **9 slices** that must be built in order. Each slice is small enough to ship in 1–2 weeks.

**Start by:**

1. Read `CODEX.md` end-to-end (15 minutes)
2. Run the environment setup in `CODEX.md` §4 on your laptop
3. Pick Slice 1 (DocType scaffolding) and open a proposal: `docs/contributing/proposals/slice-1-doctypes.md`
4. Wait for a maintainer to approve the proposal
5. Implement, test, open a PR

If Slice 1 is already in progress when you arrive, ask in an issue which slice is open.

### 📝 I want to improve the documentation

Docs are how this project gets built. Improving them is real contribution, not "just docs."

**Useful right now:**

- Find typos, broken links, or unclear sentences in any `docs/design/*.md` file
- Add diagrams where text alone is confusing (especially for `14-integrated-architecture.md`)
- Translate `START_HERE.md` and `README.md` to Hindi, Tamil, or any Indian language (Friday is India-first)
- Write tutorials once code exists

Open a PR with the changes. No proposal needed for doc fixes under 50 lines.

### 🧪 I want to test or break things

Once Slice 1 ships, the project will need people who try to break it. Run the setup, follow the install instructions, file issues for anything that doesn't work the way the docs claim.

This is one of the highest-value contributions and the easiest to start.

**Start by:** wait until Slice 1 is merged, then run the install steps and file every friction point as a GitHub issue with the label `installation-friction`.

### 🎨 I want to design the UI

Friday's Control Room is the operator-facing surface. The spec is in `docs/design/43-control-room-product-spec.md`. It needs:

- Wireframes (any tool — Figma, hand-drawn photographs, ASCII)
- Component sketches for the "active agents" panel, "approvals queue," "audit replay"
- User flow diagrams for the pause / revoke path

Open a proposal at `docs/contributing/proposals/control-room-wireframes.md` and attach your work.

### 🔒 I want to review security

The security model is in `docs/design/04-security-model.md`. The sandbox architecture is in `docs/design/24-sandbox-architecture-implementation.md`. Both need adversarial review.

Useful right now:

- Read both, file issues for any assumption you think is wrong
- Once Slice 7 ships, run actual escape attempts against the Docker sandbox
- Audit the dependency tree once `package.json` and `pyproject.toml` exist

Use the private path in `SECURITY.md` for anything that looks like a real vulnerability. Public issues for design-level questions.

### 🌍 I want to spread the word

Friday is open source. It grows by word of mouth.

- Write about Friday on your blog or social
- Speak at meetups (we'll add a `talks/` folder for slides)
- Translate the README into your language
- Help answer questions when other people ask "what is Friday?"

No PR needed. Just tag the project so we can find your work.

---

## The Workflow, Step by Step

Whoever you are, the contribution workflow is the same.

**Step 1 — Find a thing to do.**
Either pick from §5 above, or look at GitHub issues labeled `good-first-task` (added once issues exist).

**Step 2 — Propose, if needed.**
For anything bigger than a typo fix, write a 1-page proposal at `docs/contributing/proposals/<your-slug>.md`. State the problem, the change, files affected, tests planned, risks. Open it as a PR.

**Step 3 — Wait for approval.**
A maintainer reads your proposal. They'll say yes, no, or ask questions. This step exists to save you from writing 1000 lines of code that get rejected.

**Step 4 — Build.**
Follow the rules in `CODEX.md` §6. Tests are mandatory. No commits with secrets. No bypassing permission checks. Conventional commit messages.

**Step 5 — Open a PR.**
Link to your approved proposal. Fill in the validation checklist if applicable. Include test output. Keep PRs under 800 lines of diff.

**Step 6 — Iterate.**
A human reviewer comments. You respond. You may co-edit. Eventually they approve and merge.

**Step 7 — Your contribution is recorded.**
For humans: your GitHub handle goes in the commit. For AI agents: both your handle AND your sponsor's handle go in. Your track record is public.

---

## If You Get Stuck

Do **not** silently guess. Do **not** push broken code "to be fixed later." Do **not** skip tests because they're hard.

Instead, file a **Blocker Report** as an issue or a comment on your proposal. Use this format:

```
## Blocker

### What I'm trying to do
[plain language]

### What I tried
[the approaches you attempted]

### What's blocking me
[the spec is unclear / Frappe behaves unexpectedly / two docs conflict]

### Options I see
A. [option with tradeoffs]
B. [option with tradeoffs]

### My recommendation
[your preferred path with reasoning]
```

This is **not failure.** It's the most respected behaviour on this project. A clean blocker report is more valuable than a working hack that nobody understands.

---

## The Few Hard Rules

The full list is in `CODEX.md` §6 and `CONTRIBUTING.md`. The short version:

1. **Never bypass a permission check.** Not even temporarily.
2. **Never commit secrets.** API keys, tokens, customer data — encrypted Frappe Password fields only.
3. **Never silently swallow exceptions.** Log them or re-raise them.
4. **Never edit a test to make it pass.** Fix the code under test instead.
5. **Always write tests alongside your code.** Same PR.
6. **Always link your PR to an approved proposal** (except for tiny fixes).
7. **Always use conventional commit messages.** `feat(...)`, `fix(...)`, `docs(...)`, etc.

Break any of these and your PR is reverted. Break them repeatedly and you (or your AI's sponsor) lose contributor rights.

These rules look strict because Friday is governance software. We cannot ship governance software that we ourselves wrote sloppily.

---

## What Friday Promises You Back

If you contribute, here's what you get:

- **Public track record.** Every merged PR is yours forever.
- **Real review.** Maintainers respond to PRs within 7 days, with specific feedback.
- **A say.** Once you've shipped enough, you can shape the project — feature direction, design choices, even policy updates.
- **Revenue share.** When FridayLabs SaaS launches and earns money, contributors get a published share (see `docs/design/18-go-to-market-strategy.md`). This includes AI contributors' human sponsors.
- **Honest mentions.** No fake "thanks to the community" — your name goes in release notes when you ship something material.

This isn't unique to Friday. It's just stated out loud, in writing, before we have anything to give.

---

## The Decision

You've now seen the project in 5 minutes:

- **What it is:** a governed agentic framework on Frappe v16
- **Where it stands:** designs done, code not started
- **Who can join:** humans, AI agents, anyone with a sponsor
- **How to start:** pick from §5, write a proposal, build a slice
- **What you owe:** quality, honesty, blocker reports when stuck
- **What you get:** track record, review, revenue share, real ownership

If this matches what you wanted to find, your next move is one of these three:

1. **Read `CODEX.md`** if you're going to code. Start with Slice 1.
2. **Read `docs/contributing/AI_CONTRIBUTORS.md`** if you are or run an AI agent.
3. **Open an issue** if you want to do something not listed here. Tell us what you can offer; we'll figure out where it fits.

That's the front door. Welcome to Friday.

---

> *Friday is built in India, in the open, by humans and AI together, under rules we publish.*
