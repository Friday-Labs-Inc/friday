# 26 — Dynamic Framework Version Management

> See `00-glossary.md` for term definitions.
> Companion: `28-github-driven-documentation-sync.md` (snapshot fetch / sync), `25-domain-specialized-agent-profiles.md` (specialised profiles consume version pins).
> Phase: not in v0.1 per `42-phase-one-authority-contract.md` §3. Phase 2+.

---

## 1. Problem

Friday agents work across many frameworks (Frappe v15 and v16, ERPNext v15+, Next.js 14/15, React 18/19, PostgreSQL 14/15/16, Kubernetes 1.28+, and so on). Each version has different APIs, deprecated patterns, new features, and best practices.

A naive agent that knows "React" gives generic answers — sometimes correct for v17, sometimes for v18, sometimes for v19. Production code breaks.

Agents must always know **which exact framework version a project uses** and pull skills and documentation matched to that version.

---

## 2. Design goals

1. Every Agent Project records the exact framework versions in play.
2. Skills are versioned per framework version. A skill for "Frappe DocType creation" exists separately for v15 and v16.
3. The dispatcher selects the right Skill version automatically based on project context.
4. Documentation snapshots are stored locally so agents work offline and don't hallucinate against stale memory.
5. Documentation auto-updates from upstream releases — see `28-github-driven-documentation-sync.md`.

---

## 3. DocTypes

### 3.1 Framework

Identity record.

| Field | Type |
|---|---|
| `framework_name` | Data (unique) |
| `category` | Select — Backend / Frontend / Database / Infra / DevOps / ML / Other |
| `homepage_url` | Data |
| `github_repo` | Data |
| `default_version` | Link → Framework Version (used when a project does not specify) |
| `tracked` | Check (whether Friday actively syncs docs) |

### 3.2 Framework Version

One row per (framework, version) pair supported.

| Field | Type |
|---|---|
| `framework_name` | Link → Framework |
| `version` | Data — e.g. `v16.18.2`, `19.0.0`, `16.1` |
| `release_date` | Date |
| `is_lts` | Check |
| `status` | Select — Active / Deprecated / EOL |
| `doc_url` | Data |
| `release_notes_url` | Data |
| `github_release_url` | Data — consumed by `28-github-driven-documentation-sync.md` |
| `latest_known_release` | Check (one per framework) |
| `breaking_changes_from_previous` | Long Text |

### 3.3 Agent Project — child table

`project_framework_versions`:

| Field | Type |
|---|---|
| `framework` | Link → Framework |
| `version` | Link → Framework Version |
| `notes` | Small Text — e.g. "production runs v15.40 but staging runs v15.42" |

On project creation the supervisor (or System Manager Agent) fills the table. Friday auto-detects for some frameworks: `package.json` for Node, `requirements.txt` for Python, `frappe --version` for Frappe sites.

### 3.4 Skill — version fields

| Field | Type |
|---|---|
| `applicable_frameworks` | Child table of Framework Version |
| `min_version` | Data (optional, semver-style floor) |
| `max_version` | Data (optional, ceiling) |
| `version_specific_notes` | Long Text |

A single Skill row can apply to multiple framework versions when behaviour is identical. Where behaviour differs, separate Skill rows ("Frappe DocType Save v15", "Frappe DocType Save v16").

---

## 4. Skill resolution

When the dispatcher matches a task to skills:

1. Read the Agent Project's `project_framework_versions`.
2. Filter Skills whose `applicable_frameworks` includes any matching (framework, version) pair, or whose `min_version`/`max_version` window contains the project's version.
3. Rank by version specificity: exact match > range match > generic Skill (no framework specified).
4. Tie-break by most recent `last_used` or highest `success_rate`.

Implemented in `friday.dispatcher.resolve_skills_for_task(project, task)`. Unit-tested with fixture projects across versions.

---

## 5. Documentation snapshots

Per tracked Framework Version, Friday stores a local snapshot:

- Path: `friday/framework_docs/{framework_name}/{version}/`.
- Format: Markdown indexed by topic.
- Optional: full HTML mirror for fidelity.
- Embeddings: each doc chunk goes into pgvector with `framework_version_id` as a metadata filter.

Snapshots are fetched by the scheduled job in `28-github-driven-documentation-sync.md`. Initial seeds are manual — maintainers download and commit the snapshot for each framework version on first support.

---

## 6. Skill `framework_doc_lookup`

```
framework_doc_lookup(query, framework=None, version=None)
```

1. Resolves framework + version from project context if not supplied.
2. Embeds the query; runs a pgvector similarity search filtered by `framework_version_id`.
3. Returns top N chunks with citations.

Agents call this skill **before** generating code, ensuring grounded responses. Below threshold → return "documentation not found in snapshot, escalating for human verification" rather than hallucinating.

---

## 7. Version upgrade workflow

On framework upgrade (e.g. Frappe v15 → v16 on a downstream app):

1. Supervisor opens an "Agent Project Framework Upgrade" workflow.
2. The Migration Specialist agent (specialised profile per `25-domain-specialized-agent-profiles.md`) reads `breaking_changes_from_previous` for the target version.
3. Generates an upgrade plan as Agent Tasks.
4. Each task references Skills filtered to the new version.
5. Plan goes to War Room for human approval before execution.

Upgrades become first-class operations, not last-minute scrambles.

---

## 8. Multi-version coexistence

Some projects run mixed versions (legacy app on Frappe v14, new app on v15). The `project_framework_versions` table supports multiple rows. Agents must specify which sub-project or app they are acting on; the dispatcher resolves Skills accordingly.

If ambiguity remains, the dispatcher asks in War Room which version applies before proceeding.

---

## 9. Deprecation and cleanup

When a Framework Version is marked EOL:

1. Associated Skills get a banner: "Skill applies to EOL framework version; consider upgrading."
2. Projects still using that version receive a weekly War Room notice.
3. Skills are not deleted — they remain available for legacy support but are deprioritised in ranking.

---

## 10. Phasing

| Phase | Scope |
|---|---|
| 1 (v0.1) | Not in scope per `42-phase-one-authority-contract.md` §3 |
| 2 | Framework + Framework Version DocTypes; project framework versions child table; Skill version fields; `framework_doc_lookup`; manual snapshot seed for Frappe v16, ERPNext v15+, PostgreSQL 15 |
| 3 | Automated sync per `28-github-driven-documentation-sync.md`; Migration Specialist profile; snapshot rotation and storage limits |
| 4 | Public API for community-contributed framework support |

---

## 11. Open engineering questions

- Storage budget per framework snapshot — cap at 500MB initially.
- Framework version auto-detection across many project types — per-framework rules registered as small Python plugins.
- Documentation URL structure changes between versions (Frappe Wiki vs `docs.frappe.io`) — sync needs per-framework adapter in `28`.
- Public API for community contribution of new framework support — likely Phase 3.
