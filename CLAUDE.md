# Friday — governed agent kernel (a Frappe app)

## What this repo is
- A **Frappe v16 app**, not a fork. `required_apps = ["frappe", "raven"]`. Installs beside ERPNext.
- Package `friday`, module folder `friday/friday_core/`, Module Def "Friday Core".
- The kernel contains **no domain code and no domain vocabulary**. Studio-specific logic lives in
  `Friday-Labs-Inc/randompack` and plugs in through six seams declared in `friday/hooks.py`:
  `friday_skill_handlers`, `friday_skill_definitions`, `friday_task_transition_hooks`,
  `friday_reference_registry`, the `doc_events["*"]` engine subscription, and the Domain Bundle field map
  (a seventh, `friday_surfaces`, is specified in Design 98).
- **Raven is leaving the kernel** (Design 98, #222): it becomes one surface behind the `friday_surfaces`
  contract, provided by randompack; until then it is still `required_apps` and still the chat front door.
  **No new kernel file may mention Raven** — `tests/test_surface_boundary.py` enforces it (allow-list only shrinks).
  Raven's own AI stays **off** regardless (`bootstrap_raven` pins `is_ai_bot = 0`).
- Work objects are `Agent Project` / `Agent Task` / `Agent Issue`. ERPNext owns `Project` / `Task` / `Issue`.

## Dev loop
- Dev container: `~/friday-dev` (`up.sh`). This repo is bind-mounted at `/workspace/friday_app`;
  bench at `/workspace/unfork-bench`; site `unfork.localhost` (Postgres + pgvector, raven, friday, randompack, erpnext).
- Whole suite, ~15 s:   `bench --site unfork.localhost run-tests --app friday`
- One module:           `bench --site unfork.localhost run-tests --module friday.friday_core.tests.test_x`
- The gate (same script CI runs, against the local site):
  `python ci/run_tests.py --site unfork.localhost --app friday --app-path friday --known-red ci/known-red.txt --min-tests 1200` (one process per module, sorted; add `--whole-suite` to hunt cross-module leaks)
- Schema:               `bench --site unfork.localhost migrate` must be clean.

## Rules
1. **Never edit `apps/frappe`.** An upstream fix is carried in `friday_core/compat.py` with the upstream issue linked.
2. **No domain words** in kernel code, prompts, skill names or descriptions — they ship to the LLM.
3. **Every AI write goes through the permission matrix** and lands in Execution Log / Permission Decision Log. No bypass paths.
4. **Guard Raven queries** with `frappe.db.table_exists("Raven …")` — on Postgres a missing table aborts the whole transaction.
5. **DocType renames** need a `pre_model_sync` patch gated on the source DocType's `module`, never on `exists()`.
6. **Tests first.** No new red modules. Touching a known-red module means fixing it and removing its line from `ci/known-red.txt`.
7. **Secrets** live in Password fields / `site_config.json`, never in code, fixtures or commit messages.

## Workflow
- One GitHub issue per unit of work, with a `Done means:` line that is checkable. One milestone per epic.
- Branch `feat/<issue#>-short-name` (also `fix/`, `refactor/`, `ci/`, `docs/`).
- Conventional commits: `feat | fix | refactor | docs | test | chore | perf | ci`.
- Before opening a PR: gate green locally, migrate clean, `code-reviewer` + `security-reviewer` run and every CRITICAL/HIGH fixed.
- PRs use `.github/pull_request_template.md`. Every PR gets an automated Claude review (`claude-review.yml`):
  CRITICAL/HIGH → *changes requested*, otherwise a comment; `@claude` in any comment asks a follow-up.
  `main` requires the Tests check and one human approval. **A human merges; Claude never merges or approves.**
- Definition of done: tests green · no new red module · migrate clean · review findings addressed · `docs/design` updated if a decision changed.

## Where things are
- `START_HERE.md`, `CODEX.md` (repo root), `docs/design/NN-*.md` — the design dossier
  (45 fork policy = SUPERSEDED, 58 Raven decision, 75 domain engine, 81 connectors).
- `friday/hooks.py` — all registration. `friday/friday_core/{engine,skills,tasks,llm,health,surfaces,setup,connectors,patches}`.
- `ci/` — the ratchet gate and the known-red list.
