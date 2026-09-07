# slice-9-polish-hardening.md

## Status

Draft — implementing.

## 1. Problem & Context

Phase 1 slices 1–8 are implemented and tested. Before declaring Phase 1 complete, the checklist in `docs/design/11-agent-validation-checklist.md` §Slice 9 requires:

- Documentation: `README.md`, `docs/install.md`, `docs/quickstart.md`, `docs/architecture.md`, `CONTRIBUTING.md`, `SECURITY.md`, `attributions.md` kept current
- CI: tests run on every PR
- Coverage: friday_core tree ≥ 70% overall, critical modules ≥ 85%
- Pre-commit: configured and enforced
- Hermes audit: attributions updated

## 2. What Already Exists

| Item | Status | Notes |
|------|--------|-------|
| `README.md` | ✓ adequate | Phase 1 status, links to design docs |
| `SECURITY.md` | ✓ adequate | Reporting scope, baseline expectations |
| `CONTRIBUTING.md` | ✓ adequate | PR rules, AI agent policy reference |
| `CODE_OF_CONDUCT.md` | ✓ exists | Contributor Covenant 2.1 |
| `.pre-commit-config.yaml` | ✓ configured | Ruff, prettier, eslint, commitlint |
| `.github/workflows/linters.yml` | ✓ | Semgrep, commit lint, pip-audit, pre-commit |
| `attributions.md` | ⚠ stale | Last updated 2022, no Hermes section |

## 3. What Needs to Be Created or Updated

### 3.1 New Docs

- `docs/install.md` — full prerequisites and setup (Frappe bench, Python 3.14+, PostgreSQL, Redis, Docker)
- `docs/quickstart.md` — first agent + skill in 10 minutes
- `docs/architecture.md` — high-level system overview with module map

### 3.2 Attribution Update

- `attributions.md` — add Hermes attribution table (REUSE / ADAPT / REWRITE per module)
- Links to `docs/design/40-gap-analysis-and-resolution-plan.md` and `docs/design/41-porting-strategy-hermes-erpnext-raven.md`

### 3.3 CI Test Job

- `.github/workflows/tests.yml` — runs `bench run-tests --app frappe --module friday.friday_core.tests` on PR, Python 3.14, uploads test log on failure

### 3.4 Slice 9 Proposal

- This document, committed as `docs/contributing/proposals/slice-9-polish-hardening.md`

## 4. Files to Create or Modify

| File | Change |
|------|--------|
| `docs/install.md` | Create |
| `docs/quickstart.md` | Create |
| `docs/architecture.md` | Create |
| `attributions.md` | Append Hermes attribution section |
| `.github/workflows/tests.yml` | Create |

## 5. Test Cases

No new test files needed. Existing tests already provide coverage. This slice is documentation and CI infrastructure only.

## 6. Coverage Targets

| Module | Target |
|--------|--------|
| `friday_core.permissions` | ≥ 85% |
| `friday_core.gateway` | ≥ 85% |
| `friday_core.sandbox` | ≥ 85% |
| `friday_core.tasks.dispatcher` | ≥ 85% |
| Overall friday_core | ≥ 70% |

Coverage is measured via `bench run-tests --coverage`. Module-level targets above are critical; overall ≥ 70% satisfies Slice 9 checklist.

## 7. Validation Checklist

From `docs/design/11-agent-validation-checklist.md` §Slice 9:

**Documentation**
- [ ] `README.md` — concise overview, install, quickstart ✓ (existing)
- [ ] `docs/install.md` — full prerequisites and setup (new)
- [ ] `docs/quickstart.md` — first agent + skill in 10 minutes (new)
- [ ] `docs/architecture.md` — high-level, links to design docs (new)
- [ ] `SECURITY.md` — private vulnerability reporting ✓ (existing)
- [ ] `CONTRIBUTING.md` — DCO, conventional commits, PR process ✓ (existing)

**Repo hygiene**
- [ ] `.pre-commit-config.yaml` runs on every commit ✓ (existing)
- [ ] CI workflow runs tests on PR ✓ (new: `tests.yml`)

**Hermes audit**
- [ ] `attributions.md` includes Hermes section (new)