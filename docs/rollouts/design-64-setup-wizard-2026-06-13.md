# Design 64 — The Friday Setup Wizard (2026-06-13)

## The one-sentence version

`hermes setup`, Desk-native: a re-runnable, state-aware **Friday Setup** page
that walks an operator through provider → agent → surfaces → tools → verify and
*does the work* — then proves it actually works before saying "done".

## Why this ships

A fresh Friday site needed an operator to hand-create an LLM Provider, paste a
key, pick a model, create the Friday agent, set the default provider, run three
`bench execute` bootstraps, and remember to start the worker — from the CLI,
with nothing showing what's done. The user asked to "clone the Hermes setup
wizard to a Friday setup wizard." This is it.

## What this PR ships

### 1. The wizard controller — `setup/wizard.py`

Six `@frappe.whitelist()` endpoints, all **System-Manager-gated**, each
delegating to the *existing* `cli/setup.py` functions and the surface/tool
bootstraps (one implementation, not two):

- `setup_status()` — the single read the page renders from; every flag derived
  from live records, so it's honest no matter how things were created.
- `save_provider(...)` — LLM Provider + encrypted key + model + optional cost
  rates + optional set-as-default. Falls back to the per-type default model so
  the row is usable before you Discover Models.
- `save_agent(...)` — the Friday Agent Profile; seeds a default system prompt
  ("soul") when blank, mirroring Hermes seeding SOUL.md.
- `provision_surfaces()` — Raven war room, *iff* Raven is installed (else
  reports `skipped`).
- `provision_tools()` — read + file tool bootstraps onto the profile.
- `verify_and_complete()` — the surpass-Hermes step: a **live** `list_models`
  probe (`source == "live"`, not the catalog fallback) **and** `pipeline_health`
  (worker + scheduler up). Only when both pass does it set
  `Agent Settings.setup_complete`. Hermes never tests the model; we do — so
  "complete" means "actually works", the direct lesson from the 4-hour stall.

### 2. The Desk page — `page/friday_setup/`

A 5-step stepper (vanilla JS + theme-aware CSS, no build step). Each step shows
a ✓/○ badge from `setup_status()`, lets you fill the gap, and re-fetches. Step 1
has a **Discover Models** button (live, with a "key not verified" hint on
catalog fallback) and an "OAuth — coming soon" affordance (the deferred
63b-OAuth slice). Re-opening after completion shows everything green and lets
you re-run any step — Hermes' re-entrancy.

### 3. `Agent Settings.setup_complete`

A read-only Check flag set by the verify step — the explicit "finished and
verified" signal on top of the minimum-viable proxy (default provider + one
Active profile).

### 4. Discoverability

The Projects workspace gains an orange **Friday Setup** shortcut as its first
tile (next to Project Console).

## Compare with Hermes

Re-entrant and action-taking like `hermes setup`, but **Desk-native**
(DocType + encrypted Password fields instead of `config.yaml` + `.env`) and
**verifying** beyond it (live provider probe + health gate before completion).
Drops Hermes' CLI/host-specific sections (tts, terminal); Friday's gateway is
Raven, not Telegram/Slack. Per `feedback_hermes-floor-not-ceiling`.

## Why we know it works

11 unit tests in `frappe/friday_core/tests/test_setup_wizard.py`: each endpoint
delegates correctly, cost rates write only when provided (never a fake 0),
surfaces skip when Raven is absent, tools call both bootstraps, and the verify
contract is exact — `setup_complete` is set only on a live probe + non-down
health, and NOT on a catalog fallback or a down pipeline. Every endpoint asserts
the System-Manager guard. The console-views suite stays green with the new
workspace shortcut.

## What's NOT in this PR

- Provider **OAuth** login (Anthropic/OpenAI/Codex) — the 63b-OAuth slice; Step 1
  shows a placeholder.
- Telegram/Slack/other surfaces — Raven only (single-tenant v0.2).
- A smoke-test step (create project + run a task) — dropped from scope; the live
  verify covers "does it work" without throwaway data.
- Editing the bench Procfile to add the `friday` worker — bench-owned; the
  verify step *detects* a missing worker and prints the exact command.

## Operator note

After `bench migrate` + `bench build --app frappe`, open **Projects → Friday
Setup** (or `/app/friday-setup`) and walk the five steps. Re-runnable any time.
