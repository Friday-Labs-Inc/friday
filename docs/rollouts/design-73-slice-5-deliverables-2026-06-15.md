# Design 73, Slice 5 — Deliverable artifacts (Rollout)

**Date:** 2026-06-15
**Design:** [`73-project-conversation-surface.md`](../design/73-project-conversation-surface.md)
**Status:** Built + verified live.

## What this fixes, in plain words

Before today, a "100% complete" project had **nothing to show** — each task's output lived only as text in a hidden `result` field (and that text kept getting wiped). No files. Nothing a client could open or download.

Now: **when a task finishes, its output becomes real files attached to the task** — a Markdown source and a rendered PDF. When a project finishes, all the task deliverables are assembled into one **package** attached to the project.

## What changed

- **Per-task artifacts.** On task completion, the agent's output is written as `deliverable-<task>.md` + `deliverable-<task>.pdf` and attached to the task. Open the task in Desk → download the deliverable.
- **Project package.** When a project is marked Completed, every task's deliverable is concatenated into one `deliverable-<project>.md` + `.pdf` on the project.
- **Never fabricates.** A gate, an error, or an empty result produces **no** artifact — we only materialize real success content.
- **Best-effort.** Rendering is enqueued after commit; if PDF tooling (wkhtmltopdf) is missing, the Markdown still ships. Materialization never blocks a task/project transition.
- **Durable.** The artifact captures the content at completion time — so even though the `result` field gets clobbered afterward (a separate pre-existing bug), the deliverable survives. That's the whole point of materializing.

## Proven live

Re-ran the FLI-001 `strategy` task → it produced a real strategy draft → materialization attached a **4.6 KB Markdown** + **33 KB PDF** to the task. Confirmed the Markdown holds the actual "Strategy & Positioning Draft — Friday Labs Inc."

## Files

- `friday_core/deliverables/materialize.py` — extract → render (md + pdf) → attach; per-task + project package; idempotent; best-effort
- `friday_core/deliverables/__init__.py`
- `tasks/workflow.py` — on `Completed`, enqueue task materialization (after commit)
- `hooks.py` — `Project.on_update` → assemble package on `Completed`
- `tests/test_deliverables.py` — 11 tests (incl. real PDF render)

## Known follow-ups

1. **`result`-clobbering bug** (separate, pre-existing): something empties `Task.result` after completion. Materialization protects the deliverable from it, but the root cause should still be found.
2. **Project package should read the per-task artifact files**, not re-read `result` (which can be clobbered). Small refinement.
3. **DOCX** format (editable Word hand-off) not yet supported — md + pdf only.
4. To populate **all** of FLI-001's deliverables, the remaining tasks need re-running (their results are currently empty); only `strategy` was re-run as the live proof.
