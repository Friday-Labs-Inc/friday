# Design 96, Slice 3 — The Studio Workspace ("The Bench")

## The problem, in one sentence

The human Creative Director's work queue was invisible: the only signal that a
brand was waiting on him was a chat post in the war-room, and acting meant
finding the right Brand Brief form and knowing which workflow button to press
— the founder's verdict on the backend ("completely confusing") was correct.

## What shipped

A new Desk page at **`/app/studio`** — the CD's craft station. Built on the
codebase's proven rich-UI pattern (project-console: Page + JS +
`make_app_page` + whitelisted snapshot endpoints).

### The Bench (the queue)

Every Brand Brief parked at one of the two human-CD states shows as a card,
longest-waiting first:

- **the brand's name**, large and light — the studio sees brands, not brief ids
- the state (`CD Creative` / `CD Internal Gate`), days waiting, refine round
- a link to the underlying Brand Brief form for the full picture

An empty bench says so plainly ("The bench is clear. Nothing waits on you.")
— and an API error shows AS an error, never a silently empty queue.

### Review material

**Review package** opens every `production-package` version on the brief's
project, rendered markdown→HTML, newest first and expandable side by side —
so the CD compares refine rounds without downloading anything.

### One-click verbs

| State | Actions |
|---|---|
| CD Creative | **Creative Ready** |
| CD Internal Gate | **Approve Production** · **Request Refinement** (notes required) |

Actions fire through Frappe's own `apply_workflow` **as the signed-in CD** —
the workflow's role gate (`Brand Creative Director`) is the enforcement; the
endpoints add no parallel permission scheme. A lockstep test pins the Bench's
action table to the actual `randompack_brand` TRANSITIONS, so machine changes
break a test instead of silently breaking the UI.

### Notes are the training signal

The refinement notes box writes `cd-refinement-notes-r<N>.md` to the project
**before** the transition fires — so the production agent reads the correction
the moment its phase starts. The file is private and unflagged, so the slice-2
leak guard keeps it away from the customer. This is exactly the file the
Friday Labs E2E created by hand three times; it is also the data-entry surface
Design 95 Slice 2 (the apprenticeship study loop) will learn from.

### Design bar

The page obeys the CD's own bar: mono base, at most one accent (the theme's
primary), large light type, every element earns its place. All colors ride
Frappe's CSS variables, so light/dark themes both work.

## Deliberately deferred (per the design's Q4 lock)

Brand-card palette chips + marks, realtime badges, and the console-polish
ride-alongs (human project titles, the DOWN-badge reconciliation) are the
follow-up — this slice is Bench + actions + previews.

## Deploy notes

- `bench migrate` required: the new **studio** Page record syncs, and the
  Friday hub workspace gains a **Studio** shortcut tile (provisioner).
- Page access: System Manager + Brand Creative Director.

## Tests

`tests/test_studio_api.py` (11 DB-free tests): the domain-lockstep invariants,
queue filter/order/meta, fail-loud envelope, read-permission gate,
invalid-action rejection, notes-required, **notes-before-transition order**,
notes round numbering + privacy, preview rendering/order.
