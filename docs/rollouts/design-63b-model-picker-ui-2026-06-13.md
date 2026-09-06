# Design 63b — Model picker in the Desk (2026-06-13)

## The one-sentence version

Open any **LLM Provider** in the Desk, click **Discover Models**, pick
from the real live list — no more typing model strings by hand.

## What this PR ships

A single Frappe form script
(`doctype/llm_provider/llm_provider.js`, auto-loaded by the Desk because
it sits next to `llm_provider.json`):

- Adds a **Discover Models** custom button on the LLM Provider form.
- Calls the whitelisted `friday.friday_core.llm.model_discovery.list_models`
  endpoint shipped in PR #89.
- Renders the response in a click-to-fill dialog:
  - Each row is a one-click button. Click → writes the model id into
    `default_model` → saves → green "Default model set to X" alert.
  - A coloured banner says whether the list is **● live from
    `<type>` /v1/models** (green) or **● built-in catalog (fallback)**
    (amber), with the fallback reason inline (e.g. "no api key
    configured").
- New rows show a yellow hint: *"Save the provider first, then click
  Discover Models."* (The endpoint needs a persisted row to resolve
  its key.)

## Why this lands now

PR #89's data layer is wasted until an operator can use it without
running bench commands. This is ~70 lines of JS that closes that loop
visually, and uses the same fail-loud signalling (live vs catalog,
explicit error) the endpoint already returns.

## Why we know it works

Verified on `friday.localhost`: `FormMeta("LLM Provider").__js` carries
3,938 chars of form script — Frappe is serving it to the Desk. All
three markers verified: the `"Discover Models"` button registration,
the `show_model_picker` dialog, and the `list_models` whitelisted call.
The endpoint itself is the same one with 9 unit tests + live proof
from PR #89.

## What's NOT in this PR

- **OAuth login** (Anthropic Claude OAuth, OpenAI Codex OAuth) — still
  the explicit 63b-OAuth follow-up; a substantial slice on its own.
- Per-model context-length / cost hints in the picker (Hermes'
  `model_metadata.py`).
- A bulk "test connection + sync default_model" CTA.

## Operator note

After merging, `bench build --app frappe` once on each bench, then
hard-refresh the Desk. No migration, no provisioning.
