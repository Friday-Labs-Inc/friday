# 28 — GitHub-Driven Documentation Sync

> See `00-glossary.md` for term definitions.
> Companion: `26-dynamic-framework-version-management.md` (consumer of the snapshots produced here).
> Phase: not in v0.1 per `42-phase-one-authority-contract.md` §3. Phase 2+.

---

## 1. Goal

Keep Friday's local framework documentation snapshots and skill knowledge bundles current automatically. When upstream projects (Frappe, React, Kubernetes, Postgres, etc.) cut a new release on GitHub, a Friday scheduled job detects it, fetches the new docs, and updates the relevant Framework Version + embedding store.

---

## 2. Why local snapshots, not web search

Web-search-as-you-go has three problems:

1. **Latency** — every code-writing task triggers a search, inflating response time.
2. **Hallucination risk** — scraped fragments out of context produce wrong answers.
3. **Version mismatch** — generic search returns the most-popular-on-Stack-Overflow version, not the project's actual version.

Local snapshots scoped to the project's exact framework version (`26-dynamic-framework-version-management.md`) solve all three. The remaining problem is keeping snapshots fresh — that is what this doc handles.

---

## 3. Documentation Source DocType

Registers each upstream Friday monitors.

| Field | Type |
|---|---|
| `framework` | Link → Framework |
| `source_type` | Select — GitHub Release / Git Tag / ReadTheDocs / Custom Webhook / Manual |
| `github_repo` | Data — e.g. `frappe/frappe` |
| `github_release_url` | Data — API endpoint polled |
| `docs_url_pattern` | Data — template like `https://docs.frappe.io/framework/{version}/` |
| `tarball_url_pattern` | Data — for fetching the docs subtree |
| `adapter_module` | Data — Python module path for source-specific parsing |
| `last_synced_at` | Datetime |
| `last_synced_version` | Data |
| `sync_status` | Select — Idle / Running / Failed |
| `sync_error_log` | Long Text |
| `enabled` | Check |

---

## 4. Scheduled job: `friday.sync.check_doc_sources`

Runs hourly via Frappe Scheduler.

For each enabled Documentation Source:

1. Hit the GitHub Releases API (or equivalent).
2. Compare `latest_release.tag_name` to `last_synced_version`.
3. If different, enqueue `friday.sync.fetch_documentation` for that source.

Rate limiting: GitHub allows 5000 authenticated requests/hour. With < 100 sources polled hourly, well within budget. A single Friday-controlled GitHub token is stored in the Credential Profile DocType per `23-secrets-credentials-management.md`.

---

## 5. Background job: `friday.sync.fetch_documentation`

For a given Documentation Source and target version:

1. Resolve the docs URL or tarball.
2. Download to a temp directory.
3. Run the source-specific adapter to extract markdown / HTML.
4. Chunk content (1000–2000 tokens per chunk; paragraph boundaries preserved).
5. Embed each chunk via the configured embedding model.
6. Insert chunks into pgvector with metadata: `framework_id`, `framework_version_id`, `topic`, `source_url`, `chunk_index`.
7. Atomic swap: write new chunks to a staging schema, then `BEGIN; DELETE old; INSERT new; COMMIT;`.
8. Update the Framework Version row: status, release_date, doc_url, latest_known_release flags.
9. Create a Skill Sync Notice listing Skills that may need review against the new version.
10. Post a War Room notification to a dedicated `#framework-updates` channel.

---

## 6. Source-specific adapters

Each upstream has its own structure.

| Adapter | Source |
|---|---|
| `friday.sync.adapters.frappe_framework` | Frappe's docs site structure |
| `friday.sync.adapters.erpnext` | ERPNext docs |
| `friday.sync.adapters.kubernetes` | Kubernetes website docs repo |
| `friday.sync.adapters.react` | `react.dev` docs repo |
| `friday.sync.adapters.postgresql` | PostgreSQL official docs (SGML) |
| `friday.sync.adapters.generic_mkdocs` | Any project using MkDocs |
| `friday.sync.adapters.generic_sphinx` | Any project using Sphinx |
| `friday.sync.adapters.deepwiki` | DeepWiki repo representation |

Each adapter implements:

```python
class DocsAdapter:
    def fetch(self, source: DocumentationSource, version: str) -> Path: ...
    def parse(self, raw_path: Path) -> Iterator[DocChunk]: ...
```

Community contributors can add adapters via PR.

---

## 7. Skill Sync Notice

When a new framework version is synced, Skills whose `applicable_frameworks` cover the prior version automatically receive a Skill Sync Notice:

- Type: Information.
- Action required: maintainer reviews whether Skill behaviour changed between versions.
- Outcomes:
  - **No change** → mark notice resolved; extend `applicable_frameworks` to include the new version.
  - **Behaviour changed** → create a new Skill row for the new version; the old Skill remains scoped to prior versions.

Human-mediated in Phase 2. Phase 3 explores automated behavioural testing of Skills against new versions.

---

## 8. DeepWiki integration

DeepWiki (`https://deepwiki.com/{owner}/{repo}`) provides AI-friendly summaries of GitHub repos. For frameworks whose official docs are sparse but whose source is canonical (small libraries), the DeepWiki adapter is the primary source.

The adapter fetches the DeepWiki representation as a single document, chunks, and embeds it. Especially useful for less-documented internals (e.g. Frappe internals beyond the user-facing docs).

---

## 9. ReadTheDocs webhook

For projects on ReadTheDocs with outgoing webhooks, Friday registers an endpoint:

```
POST /api/method/friday.sync.readthedocs_webhook?token=...
```

Pushes updates within seconds of upstream publication, removing reliance on polling.

---

## 10. Manual refresh

A "Refresh now" button on Documentation Source enqueues `fetch_documentation` immediately. Used when:

- A maintainer is testing a new adapter.
- An upstream pushed a critical patch and waiting is undesirable.
- A new framework was just added and seeding is needed.

---

## 11. Storage and retention

Per Framework Version:

- Raw fetched docs: kept for 30 days, then purged (re-fetchable from upstream).
- Embeddings in pgvector: kept until version reaches EOL + 1 year.
- Chunk source URLs: always kept for citation.

Estimate: 50 frameworks × 5 active versions × ~200MB embeddings each ≈ 50GB. Reasonable on a single PostgreSQL instance.

---

## 12. Failure handling

On sync failure:

1. Mark `sync_status = Failed`.
2. Write a detailed error to `sync_error_log`.
3. Post a Raven message to `#framework-updates`.
4. **Do not delete or modify the prior snapshot** — fall back to last good.

Sync failures do not block agents: they continue against the last-good snapshot with a stale-warning banner in War Room.

---

## 13. Security

- Doc sources fetched from public URLs only. Private repos require an explicit token and supervisor approval.
- Fetched content is untrusted: parsing happens inside a sandbox worker per `24-sandbox-architecture-implementation.md`.
- Validate that fetched content is plausibly documentation (markdown, reStructuredText, HTML with text content) before storing — prevents arbitrary binaries.
- GitHub token is least-privilege: read-only, public-repos-only by default.

---

## 14. Phasing

| Phase | Scope |
|---|---|
| 1 (v0.1) | Not in scope per `42-phase-one-authority-contract.md` §3 |
| 2 | Documentation Source DocType; hourly scheduled job; adapters for Frappe and ERPNext; manual refresh button; pgvector storage with version metadata |
| 3 | React, Kubernetes, PostgreSQL adapters; DeepWiki adapter; ReadTheDocs webhook; Skill Sync Notice workflow |
| 4 | Community-contributed adapters via plugin registry; automated behavioural Skill testing against new versions; differential analysis ("Frappe v15 → v16, here are the API changes that affect your project") |

---

## 15. Open questions

- Docs for closed-source upstreams (e.g. AWS service docs) — adapter scrapes the public docs; legality reviewed before shipping.
- Per-framework storage when a major project has huge docs (e.g. PostgreSQL is ~10MB SGML) — cap at 1GB per Framework Version; truncate or sub-select if exceeded.
- Multi-language docs (Frappe English + others) — Phase 2 English only; later add language metadata to chunks.
