# Design 73, Slice 1 — Project conversation channels (Rollout)

**Date:** 2026-06-15
**Design:** [`73-project-conversation-surface.md`](../design/73-project-conversation-surface.md)
**Status:** Built + verified live.

## What this is, in plain words

Friday is meant to be used like you'd message a coworker — in a browser chat, not a command line. The first step toward that: **every project now gets its own chat room automatically.** Make a project → a dedicated Raven channel appears for it, named after the project, ready for the team's conversation.

## What changed

- **Make a project, get a room.** When a Project is created, Friday auto-creates a Raven channel for it (e.g. project `FLI-001` → channel `proj-fli-001` in the Friday workspace). The channel and the project are linked both ways.
- **The room opens with a welcome.** Friday (the bot) posts an opening message: what the project is, and "talk to @Friday to give direction."
- **The room follows the project.** When the project is marked Completed or Cancelled, its channel is archived automatically.
- **It never breaks a project.** All of this is best-effort and savepoint-guarded — if Raven is down (or not installed), creating a project still works fine; you just don't get the room. The project (in Friday's own tables) is always the source of truth; the chat room is a window onto it.

## The bug we fixed along the way (the big one)

The war room kept "breaking" all session with a red *"You are already a member of this channel"* error, and messages silently went missing. We finally found the root cause:

When Friday posted a message *as a user* (e.g. Administrator), Raven runs a "track your visit to the channel" step that has a bug — it checks membership one way but adds membership another way, so it tries to re-add someone who's already a member and crashes the whole message.

**The fix:** Friday now posts **as the Friday bot** instead of as a user. Raven skips the buggy step for bot messages — so messages always land. It's also just *correct*: messages from Friday should say they're from Friday, not from "Administrator." Applied to both the new project-room welcome and the existing war room feed.

## How to see it

Open Raven → the **`proj-fli-001`** channel (provisioned live for the existing Friday Labs Inc project) has its welcome message and is linked to the project.

Create any new project from the Desk → its channel appears automatically.

## Files

- `friday_core/conversation/project_channel.py` — provisioning + archive + the bot-seeded welcome
- `friday_core/conversation/__init__.py`
- `Project.conversation_channel` field (Data — the linked channel's name)
- `hooks.py` — `Project` after_insert / on_update
- `warroom/publisher.py` — now posts as the Friday bot (the reliability fix)
- `tests/test_project_channel.py` — 8 tests

## What's next (Design 73 slices)

The big one is **Slice 3: the inbound path** — typing "Friday, do X" in a channel and having it actually work. That's the platform's main entrance and it's still to build. Then multi-agent visibility (Slice 4), deliverables-as-files (Slice 5), and gate approvals in chat (Slice 6).
