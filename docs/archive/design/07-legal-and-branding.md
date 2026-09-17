# 07 — Legal & Branding

> See `00-glossary.md` for term definitions.
> See `00-README.md` and `01-vision-and-architecture.md` for the standing license decision (GPL v3) referenced throughout.

---

## License — GPL v3

Friday is licensed under the **GNU General Public License v3** to match Frappe Framework. The `LICENSE` file at the repo root carries the verbatim GPL v3 text.

**Practical implications:**

- Source code remains freely available.
- Distribution of modified Friday triggers GPL v3 reciprocal obligations.
- Internal deployment is unrestricted — GPL only triggers on distribution.
- Commercial use is allowed without license fees.
- Relicensing to a permissive licence (MIT, Apache) is not possible without consent from every contributor — and is not planned.

### AGPL v3 — open question, not a pending decision

Frappe Technologies has moved newer apps (Helpdesk, Gameplan) to AGPL v3, which extends reciprocal obligations to SaaS deployments. For an agentic framework whose expected deployment shape is heavily hosted, AGPL v3 has clear strategic appeal: it prevents commercial forks from offering proprietary hosted Friday without contributing back.

**Friday ships v0.1 under GPL v3.** Re-evaluation of AGPL v3 happens once before the public open-source launch (Phase 2) — not iteratively. If AGPL is adopted, the change must land before the first public release; relicensing after public adoption requires contributor consent and is slow.

---

## Copyright and contribution

- Copyright is held by the contributors; the original author is the primary copyright holder for initial code.
- `LICENSE` (verbatim GPL v3) lives at the repo root.
- `AUTHORS` (or `NOTICE`) tracks significant contributors and inherited works.
- File headers carry: `Copyright (c) [year] Friday Labs and contributors. Licensed under GPL v3.`
- Contributions are gated by **Developer Certificate of Origin (DCO)** via `git commit -s`. Simpler than a CLA and sufficient for an OSS project of Friday's profile.

---

## Documentation license — CC-BY-SA-3.0

Documentation is licensed under **Creative Commons Attribution-ShareAlike 3.0**, matching Frappe's documentation license. Marked explicitly in `docs/LICENSE` and the docs site footer.

---

## Naming and branding

### Product name

**Friday** — the framework. Short, memorable, "Man Friday" connotation.

### Tagline

> "An agentic framework, built on a hard fork of Frappe v16."

Avoid taglines that imply Hermes lineage at the product level; Friday ports Hermes patterns into a different framework. The product is Friday.

### Naming rules

| Do | Don't |
|---|---|
| "Friday — an agentic framework built on a hard fork of Frappe v16" | "Frappe Friday" (implies an official Frappe product) |
| "Friday (Frappe-derived agentic framework)" | "Friday by Frappe" (implies Frappe Technologies authorship) |
| Reference Frappe factually as the upstream | Use the Frappe logo unmodified as Friday's logo |

The names "Frappe" and the Frappe logo are trademarks of **Frappe Technologies Pvt. Ltd.** Factual reference is allowed ("built on a hard fork of Frappe Framework"). Implying endorsement, partnership, or origin is not.

### Hermes, Nous Research, OpenClaw

Friday **ports Hermes patterns** and draws on OpenClaw concepts; Friday is **not a fork** of either. The fork is Frappe v16.

| Do | Don't |
|---|---|
| Cite Hermes / OpenClaw in architecture discussions ("the gateway pattern is Hermes-derived") | Copy substantial source code without complying with their licenses |
| Implement the same design ideas — ideas are not copyrightable | Use "Hermes" or "OpenClaw" in Friday's product name |
| Quote short, attributed snippets under fair use | Imply endorsement by Nous Research or OpenClaw maintainers |

When any Hermes code is reused verbatim, the original license header is preserved and attribution is recorded in `AUTHORS` / `NOTICE`.

---

## Public-repo readiness

At the Phase 1 → Phase 2 flip, the repository ships with:

| File | Purpose |
|---|---|
| `LICENSE` | GPL v3 verbatim |
| `README.md` | Project overview, install, quick start, docs link |
| `CONTRIBUTING.md` | Contribution flow, DCO, code style, PR process |
| `CODE_OF_CONDUCT.md` | Contributor Covenant 2.1 |
| `SECURITY.md` | Private vulnerability reporting channel |
| `AUTHORS` / `NOTICE` | Contributor and inherited-work attribution |
| `CHANGELOG.md` | Versioned release notes |
| `.github/ISSUE_TEMPLATE/` | Bug, feature, security templates |
| `.github/PULL_REQUEST_TEMPLATE.md` | Standardised PR description |

---

## Trademark — deferred

For the first 12–24 months no trademark filings are pursued. Once meaningful adoption exists (a few hundred stars, multiple production users), a USPTO search on "Friday" in the software / SaaS classes is run. The trademark space for "Friday" is likely crowded; pivoting the mark to "Friday Framework" or similar may be necessary.

Renaming after public launch is painful. The name decision is revisited **before** the Phase 2 launch, not after.

---

## Patents — none

- Frappe Technologies asserts no patents against derivative works.
- Hermes and OpenClaw assert none either.
- Friday inherits the GPL v3 patent grant from GPL-licensed dependencies — sufficient defensive coverage.
- Friday will not file patents on its own design. Doing so would conflict with the open-source posture and deter contribution.

---

## Compliance status

| Area | Status |
|---|---|
| License (code) | GPL v3 — committed; `LICENSE` present at repo root |
| License (docs) | CC-BY-SA-3.0 — pending `docs/LICENSE` |
| AGPL v3 re-evaluation | One-time pass before Phase 2 launch |
| Frappe license compatibility | GPL v3 ↔ GPL v3 — no action |
| Third-party trademark — Frappe | Used factually only |
| Third-party trademark — Hermes / OpenClaw | Referenced as upstream inspiration only |
| Friday trademark | Deferred; revisited before Phase 2 |
| Patents | None filed, none planned |
| Contributor licensing | DCO documented in `CONTRIBUTING.md` |
