# Design 64 — The Friday Setup Wizard

**Status:** LOCKED 2026-06-13. Two forks answered by the user: **mechanism =
bespoke Desk Page stepper** (not Frappe's one-shot native Setup Wizard, not a
route-to-forms Module Onboarding checklist); **scope = 5 steps**
(provider → agent → surfaces → tools → verify). API-key auth now; provider
OAuth login is the separate deferred 63b-OAuth slice.

Implementation: **one PR** (the wizard is self-contained) — a `setup/wizard.py`
whitelisted controller + a `page/friday_setup/` Desk page + an Agent Settings
`setup_complete` flag + a Workspace shortcut. Tests-first per
[[feedback_workflow-design-lock-before-roo-code]].

## Why this exists — the plain English

> *"I need [the] Hermes setup wizard to clone to [a] Friday setup wizard."*

A fresh Friday site today needs an operator to hand-create an LLM Provider,
paste a key, pick a model, create the "Friday" Agent Profile, set
`Agent Settings.default_provider`, run three `bench execute` bootstraps (Raven,
read tools, file tools), and remember to start the `friday` worker — all from
the CLI or by clicking through raw DocType forms, with nothing telling them
what's done or what's missing. Hermes makes this one re-runnable `hermes setup`
that *does the work for you*. Design 64 brings that experience to the Desk.

## The principle that drives every Q below

> **The wizard is an actor, not a checklist. It reads the live state, shows
> what's done, and applies each step itself — reusing the exact plumbing the
> CLI already uses. It is re-runnable and idempotent end to end.**

## Compare with Hermes — what it does, what we adapt

Hermes' wizard (`hermes_cli/setup.py`, `SETUP_SECTIONS`) is **re-entrant**: every
prompt shows the current value as default, any section runs standalone, and it
*takes actions* (live model discovery, writes `config.yaml` + `.env`). Its
sections are model / tts / terminal / gateway / tools / agent.

We adapt, single-tenant and Desk-native:
- **Drop** `tts` and `terminal` (CLI/host-specific — no Friday equivalent).
- **`model` → Step 1 (Provider & model):** the LLM Provider DocType + the
  Design 63 `list_models` discovery + Design 65d cost rates. API keys live in
  the encrypted `api_key` Password field (Frappe's secret store), not a `.env`.
- **`agent` → Step 2 (Agent):** the "Friday" Agent Profile. Hermes seeds
  `SOUL.md` silently; we seed a default `system_prompt` if the operator leaves
  it blank (governance-aware identity), so the agent has a soul without a prompt.
- **`gateway` → Step 3 (Surfaces):** Raven war room via the existing
  `bootstrap_raven.provision` (Friday's gateway is Raven, not Telegram/Slack).
- **`tools` → Step 4 (Tools):** `bootstrap_read` + `bootstrap_files`.
- **Step 5 (Verify) is a surpass-Hermes axis:** Hermes' wizard does *not* test
  the model end to end. Ours runs a live `list_models` probe **and**
  `pipeline_health` (worker + scheduler up?) before declaring done — so "setup
  complete" means *actually works*, directly answering the 4-hour-stall lesson
  (the operator learns the worker is down here, not four hours into a project).

Per [[feedback_hermes-floor-not-ceiling]]: re-runnable + state-aware like Hermes,
but **verifying** and **Desk-native** beyond it.

## Why a bespoke page, not the native mechanisms

- Frappe's **Setup Wizard** (`desk/page/setup_wizard`) is gated by
  `frappe.is_setup_complete()` — one-shot on a fresh site, hijacks the whole
  Desk, **not re-runnable**. Wrong tool.
- **Module Onboarding** is re-runnable and state-aware but its steps only
  *route to forms* (Create Entry / Update Settings / Go to Page). It cannot run
  the Raven/tools bootstrap functions or do live discovery/verify inline — the
  operator would still drop to the CLI. It models a checklist, not an actor.
- A **bespoke Desk Page** (the 65c console pattern) does the work, reuses every
  existing bootstrap, and is trivially re-runnable + state-aware.

---

## Q1 — The page *(LOCKED: bespoke stepper)*

`friday_core/page/friday_setup/` (route `friday-setup`, gated to System
Manager). Vanilla JS + Frappe primitives (no build step; served from disk). A
5-step stepper; each step renders its **current state** from one
`setup_status()` call, lets the operator fill gaps, and calls a step action
endpoint. Re-opening the page after completion shows everything green and lets
you re-run any step (e.g. swap providers) — exactly Hermes' re-entrancy.

## Q2 — The controller `setup/wizard.py` *(recommended)*

All `@frappe.whitelist()` + `frappe.only_for("System Manager")` (setup is an
admin act). Each delegates to the **existing** `cli/setup.py` functions and
bootstraps — no logic duplication:

| endpoint | does | reuses |
|---|---|---|
| `setup_status()` | returns per-step state (below) — the single read the page renders from | `pipeline_health`, `frappe.db` |
| `save_provider(name, type, api_key, base_url, default_model, in_cost, out_cost, make_default)` | create/update LLM Provider, set cost rates, optionally set as default | `cli.setup.provision_provider`, `set_default_provider` |
| `save_agent(profile_name, provider_name, model_name, system_prompt)` | create/update the Friday Agent Profile (status Active; seed default prompt if blank) | `cli.setup.provision_profile` |
| `provision_surfaces()` | provision Raven war room **iff** Raven installed; else report `skipped` | `surfaces.bootstrap_raven.provision` |
| `provision_tools(profile_name)` | provision read + file tools onto the profile | `skills.bootstrap_read.provision`, `bootstrap_files.provision` |
| `verify_and_complete(provider_name)` | live `list_models` probe + `pipeline_health`; set `setup_complete` when the provider responds and health isn't `down`; return the verdict | `llm.model_discovery.list_models`, `pipeline_health` |

`setup_status()` shape:
```json
{
  "provider":  {"configured": true, "default_provider": "Minimax", "providers": ["Minimax"]},
  "agent":     {"configured": true, "profile": "Friday", "has_system_prompt": true},
  "surfaces":  {"raven_installed": true, "war_room": true},
  "tools":     {"read": true, "files": true},
  "health":    {"verdict": "ok", "friday_worker": true, "scheduler": true},
  "setup_complete": false
}
```

Each `configured` flag is derived from live state, so the wizard is honest about
what exists regardless of how it was created (CLI, by hand, or the wizard).

## Q3 — Auth scope *(LOCKED: API-key only)*

Step 1 collects an **API key** into the LLM Provider's encrypted `api_key`
field. The provider-OAuth flows (Anthropic Claude, OpenAI Codex) are the
explicit **63b-OAuth** slice — Step 1 leaves a visible "OAuth login (coming
soon)" affordance but does not implement it here. (Hermes' OAuth lands tokens in
`auth.json`; Friday's equivalent credential store is 63b-OAuth's design.)

## Q4 — "Setup complete" state *(recommended)*

Add a `setup_complete` Check to the `Agent Settings` singleton (mirrors
`System Settings.setup_complete`). `verify_and_complete` sets it. The page reads
it to show the final "✅ Friday is ready" state. We also surface the wizard via a
**Workspace shortcut** ("Friday Setup") on the Projects workspace so it's
discoverable; a first-login redirect is intentionally NOT added (too intrusive
for a re-runnable tool) — the shortcut + the console health strip are enough.

The minimum-viable-configured proxy remains `Agent Settings.default_provider`
being set + one Active Agent Profile; `setup_complete` is the operator's explicit
"I finished and it verified" flag on top.

## Q5 — Default system prompt seed *(recommended)*

If the operator leaves the agent's `system_prompt` blank, seed a short
governance-aware default (Friday's "soul") — so a freshly-created agent is never
prompt-less. Mirrors Hermes seeding `SOUL.md`. One constant in `wizard.py`.

## Q6 — Implementation phasing

Single PR. Order (tests-first):
1. `setup/wizard.py` + `test_setup_wizard.py` (the controller — the testable core).
2. `Agent Settings.setup_complete` field.
3. `page/friday_setup/` (json + js + css).
4. Workspace shortcut in `provision_console`.

Verify: `bench migrate` clean; on a fresh-ish site, the page walks
provider→agent→surfaces→tools→verify and ends green; re-opening shows live
state; each endpoint is idempotent and System-Manager-gated.

## What's explicitly NOT in Design 64

- Provider **OAuth** login (63b-OAuth).
- MCP/outside-world tools (Design 67) — not a setup step yet.
- Telegram/Slack/other surfaces — Raven only (single-tenant v0.2).
- A smoke-test step (create project + run a task) — considered and dropped from
  scope; the live verify (Step 5) covers "does it actually work" without
  creating throwaway data.
- Editing the Procfile to add the `friday` worker — bench-owned; the verify step
  *detects* a missing worker and tells the operator the exact command instead.
