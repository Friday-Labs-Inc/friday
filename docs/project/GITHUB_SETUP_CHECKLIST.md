# GitHub Repository Setup Checklist

> **Purpose:** A step-by-step list of one-time setup tasks for the Friday GitHub repository. Some are done from the GitHub website, some via the `gh` CLI. Tick each box as you complete it.

This complements the file-based setup already in the repo:

- `.github/ISSUE_TEMPLATE/` — issue forms
- `.github/PULL_REQUEST_TEMPLATE.md` — PR template
- `docs/project/LABELS.md` — label taxonomy reference
- `scripts/setup-labels.sh` — script to create all labels at once

---

## 1. Repository Settings (Web UI)

Go to **Settings** on the Friday-Labs-Inc/friday repo.

### General
- [ ] **Description:** *"Governed agentic framework on Frappe v16 — where AI agents are first-class contributors. Made in India."*
- [ ] **Website:** leave blank for now (add when there's a landing page)
- [ ] **Topics:** add `frappe`, `agentic-framework`, `ai-agents`, `open-source`, `india`, `governance`, `gpl-v3`, `erpnext`
- [ ] **Visibility:** Public (when you're ready to share — not required for setup itself)
- [ ] **Features → Wikis:** disabled (we use `docs/` instead)
- [ ] **Features → Issues:** enabled
- [ ] **Features → Sponsorships:** decide later
- [ ] **Features → Discussions:** **enabled** (this is your community Q&A surface)
- [ ] **Features → Projects:** enabled
- [ ] **Pull Requests → Allow merge commits:** enabled
- [ ] **Pull Requests → Allow squash merging:** enabled (recommend as default)
- [ ] **Pull Requests → Allow rebase merging:** disabled (keeps history cleaner for a first-timer)
- [ ] **Pull Requests → Automatically delete head branches:** enabled

### Branch Protection
Settings → Branches → Add rule for `main`:

- [ ] **Require a pull request before merging** — yes
  - [ ] **Required approvals:** 1 (set this even though you'll often be the only reviewer; it forces explicit approval)
  - [ ] **Dismiss stale pull request approvals when new commits are pushed** — yes
- [ ] **Require status checks to pass before merging** — turn on once CI exists (Slice 9)
- [ ] **Require conversation resolution before merging** — yes
- [ ] **Require linear history** — yes (cleaner history)
- [ ] **Do not allow bypassing the above settings** — leave off while you're solo, turn on later

### Security
Settings → Code security and analysis:

- [ ] **Dependency graph:** enabled
- [ ] **Dependabot alerts:** enabled
- [ ] **Dependabot security updates:** enabled
- [ ] **Secret scanning:** enabled
- [ ] **Push protection:** enabled (blocks accidental secret commits)

---

## 2. Labels (CLI Script)

The label taxonomy is in `docs/project/LABELS.md`. To create all labels at once:

```bash
# Authenticate gh CLI (one-time)
gh auth login

# Run the label setup script
./scripts/setup-labels.sh
```

- [ ] Authenticated `gh` CLI with write access
- [ ] Ran `./scripts/setup-labels.sh` successfully
- [ ] Visited https://github.com/Friday-Labs-Inc/friday/labels and verified labels exist

---

## 3. Milestones (Web UI)

Go to **Issues → Milestones → New milestone**. Create one per Phase 1 slice plus the post-slice phases. Use these exact titles so label/milestone names align:

- [ ] `Slice 1 — Foundations & DocType Skeletons`
- [ ] `Slice 2 — Permission Engine`
- [ ] `Slice 3 — Skill Loader`
- [ ] `Slice 4 — Gateway + CLI`
- [ ] `Slice 5 — LLM Integration`
- [ ] `Slice 6 — First Skill: create_note`
- [ ] `Slice 7 — Docker Sandboxing`
- [ ] `Slice 8 — Tasks, Dispatcher, Kanban`
- [ ] `Slice 9 — Polish & Hardening`
- [ ] `Phase 1.5 — Production Hardening`
- [ ] `Phase 2 — Public Launch & Raven`

Leave due dates blank for now — set them once Slice 1 ships and you know your velocity.

---

## 4. GitHub Project Board (Web UI)

Go to **Projects → New project → Board**.

- [ ] **Project name:** `Friday Phase 1 — Fundamentals`
- [ ] **Visibility:** Public
- [ ] **Template:** Board (Kanban)

Add columns:
- [ ] **Backlog**
- [ ] **Ready** (proposal approved, ready to work)
- [ ] **In Progress** (someone is actively coding)
- [ ] **Review** (PR open, awaiting human review)
- [ ] **Done** (merged)

Add custom fields:
- [ ] **Slice** (single-select): `Slice 1` through `Slice 9`
- [ ] **Area** (single-select): values from `LABELS.md` §4
- [ ] **Phase** (single-select): `v0.1`, `1-business-flagship`, `1.5`, `2`
- [ ] **Risk** (single-select): `Low`, `Medium`, `High`, `Critical`

Workflows (auto-add items):
- [ ] When an issue is opened with a `slice:*` label → add to Backlog
- [ ] When a PR is opened → add to Review
- [ ] When a PR is merged → move to Done

---

## 5. Discussions Categories (Web UI)

Once Discussions is enabled, go to **Discussions → ⚙ icon → Categories**. Create:

- [ ] **Announcements** (announcement type) — for project updates from maintainers
- [ ] **Q&A** (Q&A type) — for questions about how to use Friday
- [ ] **Show and tell** (open-ended) — for contributors to demo what they're building
- [ ] **Ideas** (open-ended) — for feature proposals before they become formal `[Proposal]` issues
- [ ] **AI Contributors** (open-ended) — coordination space for sponsors and their agents

Pin a welcome post in **Announcements**:

> *"Welcome to Friday. Read `START_HERE.md` first. Read `docs/contributing/AI_CONTRIBUTORS.md` if you are or run an AI agent. Ask anything in Q&A."*

---

## 6. Seed Issues (Web UI or CLI)

Open issues for every Slice 1 sub-task so first contributors have something to grab.

- [ ] `[Build]: Slice 1 — Scaffold friday app and modules.txt` (labels: `slice:1-foundations`, `phase:v0.1`, `area:framework-core`, `good-first-task`, `for:humans`)
- [ ] `[Build]: Slice 1 — Create Agent Profile DocType` (labels: `slice:1-foundations`, `phase:v0.1`, `area:agent-kernel`)
- [ ] `[Build]: Slice 1 — Create Skill DocType` (labels: same)
- [ ] `[Build]: Slice 1 — Create Agent Task and Agent Project DocTypes` (labels: same, `area:workflow`)
- [ ] `[Build]: Slice 1 — Create Chat Message and Chat Platform DocTypes` (labels: same, `area:cli`)
- [ ] `[Build]: Slice 1 — Create Execution Log (submittable) DocType` (labels: same, `area:agent-kernel`)
- [ ] `[Build]: Slice 1 — Create Permission Decision Log (submittable) DocType` (labels: same, `area:permissions`)
- [ ] `[Build]: Slice 1 — Migration runs clean on fresh site` (labels: same, `area:ci`)
- [ ] `[Build]: Slice 1 — test_doctypes_exist.py covering all 8 DocTypes` (labels: same, `area:ci`)

Each issue should link to:
- The relevant section of `docs/design/05-module-design.md` for the field schema
- `docs/design/11-agent-validation-checklist.md` "Slice 1" for done criteria

---

## 7. Optional — Useful Apps and Integrations

- [ ] **all-contributors-bot** — recognises every contributor (human and AI) in a `CONTRIBUTORS.md`
- [ ] **stale bot** — auto-closes inactive issues after 90 days (turn on later when issue volume justifies it)
- [ ] **dependabot.yml** — once `pyproject.toml` and `package.json` exist

Skip these until they're needed. They are noise more than help on day 1.

---

## 8. Done When

- [ ] A stranger can land on `Friday-Labs-Inc/friday`, read `START_HERE.md`, open an issue using a template, and the issue lands in the project board automatically with the right labels.
- [ ] An AI sponsor can find the AI Contributor Registration template without searching.
- [ ] A PR opened from a feature branch follows the PR template and shows the validation checklist.
- [ ] Branch protection prevents direct pushes to `main`.
- [ ] Secret scanning prevents accidental credential commits.

When all eight boxes in section 8 are green, the GitHub infrastructure is complete and the repo is ready for public traffic.
