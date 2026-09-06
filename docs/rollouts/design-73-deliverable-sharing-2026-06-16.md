# Design 73 — Deliverable sharing in chat (Rollout)

**Date:** 2026-06-16
**Design:** 73 use-case #5 (the chat side of design 66b deliverables)
**Status:** Built + verified live (Legion, real Northwind Coffee project).

## What this is, in plain words

You can now ask Friday, in a project's chat room, to **share the project's files** — and it actually posts them into the channel as real downloadable attachments. Before today it couldn't: asked "share those files here," it had no tool, so it refused or (worse) guessed a filename.

## The gap we found (live)

While testing Slice 3 in the real UI, a human asked Friday *"@Friday can you share those files here."* Friday answered honestly that it had no way to retrieve or share files — and, on the pre-snapshot code, even guessed a filename. Two things were missing: it didn't reliably know the real filenames, and it had no verb to hand them over. Slice 3's snapshot fixes the *knowing*; this adds the *verb*.

## What changed

- **New skill `share-deliverables`.** When someone in a project's channel asks to share / send / post the deliverables, the agent calls this skill. It finds the project's **package** files (the assembled `deliverable-*` md + pdf attached to the Project) and posts each into the channel as a real file message, sent by the Friday bot.
- **The project comes from the room, not a parameter.** The skill always uses the project of the *current channel*, so an agent can never post one project's files into another's room.
- **Honest when empty.** No deliverables → it says "nothing to share" — it never invents a file.
- **Scope = the package.** The two assembled project files (what a client means by "the deliverables"). Per-task artifacts stay reachable via the existing `list-project-files`.
- **Governance.** Low-risk, no approval. A tight `Friday Deliverable Sharer` role (read File + Project, create Raven Message) gates it; every call writes an Execution Log row.

## Proven live (Legion, real Northwind Coffee project)

Provisioned the skill, then in the real Northwind channel asked: *"@Friday please share the deliverable files for this project here."*

- The agent **called `share-deliverables`** — Execution Log: **success**.
- **Two file messages appeared in the channel** (0 → 2), both posted as the Friday bot:
  - `/private/files/deliverable-northwind-coffee---brand-identityc9466c.pdf`
  - `/private/files/deliverable-northwind-coffee---brand-identity2fea7d.md`
- The agent's reply named the **real** files (no guessing): *"I've shared the two deliverable files… Markdown… PDF… You should see them in this channel now."*

(Verified via sync dispatch in a console; the provisioning was then removed and Legion restored to clean `main` — the feature lands for real when this PR merges and `bootstrap_deliverables.provision` runs on deploy.)

## How to turn it on (per site)

    bench --site <site> execute friday.friday_core.skills.bootstrap_deliverables.provision

Idempotent. Grants the role + skill to the `Friday` profile; pass a different `profile_name` to grant another agent.

## Files

- `friday_core/skills/handlers_deliverables.py` *(new)* — the `share_deliverables` handler
- `friday_core/skills/bootstrap_deliverables.py` *(new)* — role + Skill row + profile wiring
- `friday_core/agent_runner/dispatcher.py` — import the handler module so it registers
- `friday_core/tests/test_share_deliverables.py` *(new)* — 5 mock-based tests

## Known follow-ups

- **Private-file download for non-admin members.** The package files are `is_private=1`; the bot posts them by `file_url`. Admins download fine; confirm in the UI that ordinary channel members can download them — if not, add a Raven file-share/copy step so channel membership grants access.
- **Per-task artifacts.** Default scope is the package; a future `scope` argument could share specific per-task files on request.
- **Async-worker path.** Verified via sync dispatch; a smoke test through the real async worker on the next deploy closes the last gap (same as Slice 3).
