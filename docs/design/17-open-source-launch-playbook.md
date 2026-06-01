# 17 — Open-Source Launch Playbook

> See `00-glossary.md` for term definitions.
> See `07-legal-and-branding.md` for license, naming, and contributor-licensing decisions.
> See `42-phase-one-authority-contract.md` — Phase 1 v0.1 must be complete before this playbook starts.

---

## 1. Pre-launch checklist

Flipping the repo from private to public requires every box green.

### Code quality

- [ ] All Phase 1 tests pass on CI.
- [ ] Coverage ≥ 70% overall, ≥ 85% on `permissions`, `gateway`, `sandbox`, `tasks/dispatcher`.
- [ ] `pre-commit run --all-files` clean.
- [ ] No `TODO: security` comments left in code.
- [ ] No hard-coded credentials, tokens, or site names.
- [ ] `bench migrate` clean from an empty site to current state.

### Repository hygiene

- [ ] `LICENSE` — GPL v3 verbatim.
- [ ] `README.md` — concise overview, 60-second install, link to docs.
- [ ] `CONTRIBUTING.md` — DCO, code style, PR process, claiming issues.
- [ ] `CODE_OF_CONDUCT.md` — Contributor Covenant 2.1.
- [ ] `SECURITY.md` — private reporting channel, response SLA.
- [ ] `AUTHORS` / `NOTICE` — attribution for Hermes, OpenClaw, Raven, Frappe references.
- [ ] `CHANGELOG.md` — Keep-a-Changelog format, starting v0.1.0.
- [ ] `.github/ISSUE_TEMPLATE/` — bug, feature, security, question.
- [ ] `.github/PULL_REQUEST_TEMPLATE.md`.
- [ ] `.github/workflows/` — tests, lint, build, docs.

### Documentation

- [ ] `docs/install.md` — full prerequisites and step-by-step setup.
- [ ] `docs/quickstart.md` — first agent + skill in 10 minutes.
- [ ] `docs/architecture.md` — high-level diagram + links to the design docs.
- [ ] `docs/skills.md` — Skill authoring guide.
- [ ] `docs/security.md` — threat model, deployment hardening checklist.
- [ ] `docs/faq.md` — anticipated questions.
- [ ] `docs/design/` — design dossier committed.

### Brand and legal (per `07-legal-and-branding.md`)

- [ ] Project name confirmed: **Friday**.
- [ ] Tagline: "An agentic framework, built on a hard fork of Frappe v16."
- [ ] Naming rules in `07` followed (no "Frappe Friday", no "Friday by Frappe").
- [ ] Wordmark for v0.1.0 (logo can iterate).
- [ ] GitHub repo description and topics set.
- [ ] Domain registered.
- [ ] AGPL v3 re-evaluation completed (per `07` §License).
- [ ] Trademark search for "Friday" performed; rename if conflict requires it.

---

## 2. Repository layout

The repo IS the Frappe v16 fork (per `45-fork-policy.md`). Agent kernel modules live inside the Frappe tree.

```
friday/                              ← repo root = the fork
├── LICENSE
├── README.md
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── SECURITY.md
├── AUTHORS
├── NOTICE
├── CHANGELOG.md
├── pyproject.toml
├── .pre-commit-config.yaml
├── .github/
│   ├── ISSUE_TEMPLATE/
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── workflows/
│       ├── test.yml
│       ├── lint.yml
│       └── docs-publish.yml
├── frappe/                          ← Frappe v16 source tree (the fork)
│   └── friday_core/                 ← agent kernel modules per 05-module-design.md
├── docs/
│   ├── install.md
│   ├── quickstart.md
│   ├── architecture.md
│   ├── skills.md
│   ├── security.md
│   ├── faq.md
│   └── design/                      ← the design dossier
└── tests/
```

### Branches

- `friday/main` — always green, releasable.
- Feature branches — `feat/{slug}`, `fix/{slug}`, `docs/{slug}`.
- Release tags — semver, `v0.1.0` for the first public release.

### CI

- `test.yml` — Python 3.14, PostgreSQL 15 (+ pgvector ≥ 0.8.2), Redis 7. Full pytest + `bench migrate`.
- `lint.yml` — `black`, `ruff`, `mypy` on critical modules.
- `docs-publish.yml` — publish docs to GitHub Pages or Cloudflare Pages on `friday/main`.

---

## 3. Release engineering

### Versioning

Semantic versioning. `v0.x.y` signals "early, breaking changes possible".

| Version | Milestone |
|---|---|
| v0.1.0 | First public release — Phase 1 v0.1 |
| v0.2.0 | Additional platform adapters (Telegram, Slack, etc.) and Memory module with pgvector |
| v0.3.0 | Learning loop + autonomous curator |
| v0.4.0 | Multi-site agent-to-agent (`37-multi-site-inter-agent-communication.md`) |
| v0.5.0 | Sandbox hardening — warm pool, egress proxy, gVisor backend (per `42` §5 deferred items) |
| v1.0.0 | Production-ready, API-stable, first business-automation flagship complete |

If Raven is included in v0.1 per the feasibility spike, v0.2.0's Raven scope shifts to advanced features (Approve Skill, document-share previews, archive automation).

### Cadence

- Patches (`x.y.Z`) — as needed for bugs and security.
- Minors (`x.Y.0`) — monthly during active development, then quarterly.
- Majors (`X.0.0`) — only with breaking changes; advance notice.

### Release process

1. Create `release/vX.Y.Z`.
2. Bump version in `pyproject.toml`.
3. Update `CHANGELOG.md`.
4. Run full test suite + manual smoke test.
5. Tag `vX.Y.Z`, push tag.
6. CI builds and publishes to PyPI (and Frappe Cloud app marketplace if applicable).
7. Publish GitHub Release with changelog excerpt.
8. Announce per §6.

---

## 4. Contribution process

### DCO

All commits signed: `git commit -s`. CI rejects unsigned commits. Lighter than a CLA and sufficient for Friday.

### Issue triage

- New issues triaged within 7 days.
- Labels: `bug`, `feature`, `docs`, `good-first-issue`, `help-wanted`, `security`, `breaking`, `priority/{low,med,high,critical}`.
- 60 days without activity → stale; 30 more → auto-close. Security issues never auto-close.

### PR review standards

- Every PR links to an issue (except trivial doc fixes).
- One maintainer approval required.
- CI must be green.
- Security-sensitive areas (permissions, sandbox, gateway): two approvals required.
- PRs > 800 lines diff are blocked — split required.

### Maintainer tiers

- **Founder / BDFL** — final direction decisions.
- **Core Maintainers** — full commit access, can merge to `friday/main`.
- **Trusted Contributors** — can review and approve; cannot merge.
- **Contributors** — anyone with a merged PR.

Promotion is based on demonstrated quality and community fit, not contribution count.

---

## 5. Security policy

Per `SECURITY.md`:

- **Private reporting:** GitHub private vulnerability reporting (preferred) or a dedicated `security@` mailbox.
- **Response SLA:** acknowledgement within 48 hours.
- **Disclosure timeline:** 90 days standard; shortened for actively-exploited or high-severity issues.
- **Credit:** reporters credited in the changelog and a SECURITY hall of fame.
- **Bug bounty:** none in v0.x; revisited at v1.0.

---

## 6. Launch sequence

### T-30 days

- Finalise public-facing docs.
- Lock the API surface — anything renamed after v0.1.0 is a breaking change.
- Internal red-team review of the security model.

### T-14 days

- Soft launch to 5–10 trusted reviewers (private fork or NDA).
- Collect feedback, fix critical issues.
- Draft launch posts and tweet thread.

### T-7 days

- Final code freeze on `release/v0.1.0`.
- Generate v0.1.0 release artefacts.
- Pre-write the blog post, Show HN draft, LinkedIn post.

### T-0

- Flip repo to public.
- Tag v0.1.0.
- Publish the blog post.
- Submit to Hacker News (Show HN), Reddit r/selfhosted and r/programming, dev.to, lobste.rs.
- Post in the Frappe forum and Frappe Discord.
- Post on Twitter/X and LinkedIn with the architecture diagram.

### T+1 to T+7

- Respond to every comment and issue within 24 hours.
- Patch critical bugs (v0.1.1, v0.1.2).
- Watch for install-experience friction.

### T+30

- Retrospective: what worked, what did not.
- Plan v0.2.0 based on community feedback.

---

## 7. Community spaces

Set up before launch:

| Channel | Purpose |
|---|---|
| GitHub Discussions | Q&A, ideas, show-and-tell |
| Discord or Matrix | Real-time chat, dev coordination |
| Low-volume mailing list | Releases, security advisories |
| Twitter/X account | Announcements, dogfood updates |
| Project blog | Long-form writing, case studies, design rationale |

Do not set up Telegram, WhatsApp, Slack (closed-source), or any walled-garden as the **primary** community space.

---

## 8. Documentation site

GitHub Pages or Cloudflare Pages, static site from `docs/` markdown. Stack: MkDocs Material, Docusaurus, or Astro Starlight — pick one and commit.

Structure:

- Landing page with the 60-second value pitch.
- "Get Started" — install + first agent.
- "Concepts" — Agent Profile, Skill, War Room, etc. (terms drawn from `00-glossary.md`).
- "How-to" — recipes.
- "Reference" — DocType schemas, REST API, configuration.
- "Design" — the design dossier.

---

## 9. Anti-patterns to avoid

- **Vanity metrics.** Don't optimise for stars early. Optimise for repeat users.
- **Surface-only marketing.** If the install experience is broken, no LinkedIn post will save it. Fix friction first.
- **Roadmap theatre.** Keep a public roadmap; never commit to what cannot be delivered. Under-promise.
- **Burning out one maintainer.** Delegate aggressively. Documented contribution paths matter more than personal throughput.
- **Closing issues fast.** An old open issue is honest. A closed-without-resolution issue burns trust.

---

## 10. Success criteria (T+90 days)

- [ ] ≥ 100 GitHub stars.
- [ ] ≥ 10 external contributors with merged PRs.
- [ ] ≥ 3 documented production deployments.
- [ ] No unfixed critical security issues.
- [ ] Active Discussions traffic (≥ 5 threads per week).
- [ ] At least one third-party blog post or video covering Friday.
- [ ] Time-to-first-running-agent for a new user: < 30 minutes.

Deliberately modest. Healthy growth is the goal, not virality.
