# 18 — Go-to-Market Strategy

> See `00-glossary.md` for term definitions.
> See `07-legal-and-branding.md` for the license decision (GPL v3 today; AGPL v3 open question before Phase 2 launch).
> See `17-open-source-launch-playbook.md` for the launch sequence.

---

## 1. Mission

> Friday is an open-source agentic framework, built in India, for the next generation of growing businesses to automate intelligently — without vendor lock-in, predatory licensing, or compromise on governance.

Three non-negotiable pieces:

1. **Open-source** — GPL v3 today, AGPL re-evaluated once before public launch. No proprietary trap doors.
2. **Made in India** — Indian builders, Indian-hosted infrastructure (Friday Labs), Indian community first.
3. **Enterprise governance from day one** — not a hobbyist tool retrofitted for business.

---

## 2. Audience

### Primary (Phase 1 launch)

- Indian SMBs and growth-stage startups already using ERPNext, or considering it.
- System integrators and consultants serving Indian businesses.
- Indian software developers building automation for their employers.

Why ERPNext users specifically: they already trust open-source enterprise software, they run Frappe-based stacks, and they have real automation pain (manual data entry, repetitive workflow, supplier coordination). Friday lands on terrain they already understand.

### Secondary (Phase 2–3)

- Global Frappe community — same value proposition, broader geography.
- Mid-market companies in manufacturing, services, and healthcare where governance matters.
- Internal automation teams at larger enterprises evaluating open agentic platforms.

### Not the target yet

- Hobbyist personal-automation users — OpenClaw, Hermes, and Claude Code serve them.
- AI researchers — Friday is not an experimentation platform.
- Pure-LLM applications (chatbots, content generation) — wrong tool.

---

## 3. Positioning

| Alternative | What they have | What Friday adds |
|---|---|---|
| Custom in-house automation | Full control | Faster build, governance built-in, community |
| UiPath, Automation Anywhere (RPA) | Enterprise features | Open-source, no per-bot licensing, real LLM agents |
| LangChain, AutoGen, CrewAI | Agent frameworks | Enterprise governance, audit trails, role-based permissions |
| OpenClaw, Hermes Agent | Personal autonomy | Multi-tenant, enterprise-grade, ERPNext-native |
| ChatGPT Enterprise, Claude for Work | Polished UX | Self-hosted, data stays on-premise, no per-seat lock-in |
| ERPNext alone | Solid ERP | Agentic layer on top — autonomous workflows, not just records |

**One-line pitch:** "ERPNext for agents — open-source, enterprise-grade, made in India."

---

## 4. Differentiators

These are not marketing claims. They are properties enforced in code:

1. **Permission-first.** Every skill invocation gated by Frappe's role matrix. Competitors gate at config; Friday gates at runtime.
2. **Audit trail by default.** Every decision is a submittable Frappe DocType. SOC 2-ready out of the box.
3. **Sandbox isolation.** Docker-per-execution with scoped credentials. A compromised skill cannot pivot.
4. **Native ERPNext integration.** Project, Task, Issue ported from ERPNext; multi-user agent authentication respects ERPNext role separation.
5. **Community-owned revenue.** Friday Labs revenue flows back to contributors. Not an "open-source until acquisition" play.
6. **No external vector database.** pgvector inside PostgreSQL. Lower cost, fewer moving parts, easier audit.
7. **No vendor lock on LLM.** Provider-agnostic; runs against local models if desired.

---

## 5. Phasing

### Build & dogfood (months 1–4)

- Build Phase 1 v0.1 per `42-phase-one-authority-contract.md`.
- Dogfood: Friday tracks Friday's own development.
- Prove ERPNext autonomous ops on a real (or carefully simulated) Indian SMB scenario.
- **No marketing.** Do not launch what does not work.

### Quiet release (months 5–6)

- Open the repo per `17-open-source-launch-playbook.md`.
- Quiet announcement to the Frappe / ERPNext community first — Frappe forum, ERPNext Discord, Indian dev Twitter.
- Invite 10–20 design partners from Indian SMBs to pilot.
- Iterate weekly on feedback.

### Public launch (months 7–9)

- Show HN, Reddit, broader social.
- Document case studies from the design partners.
- Book demos for Friday Labs hosted (see §7).

### Sustained growth (year 2+)

- Friday Labs revenue begins.
- Contributor revenue-share model goes live (see §8).
- Indian conference circuit: FOSS, NASSCOM, PyCon India, Frappe Conference.
- Targeted partnerships with Indian ERPNext implementers and consultancies.

---

## 6. Distribution

How Friday reaches its first 1,000 users:

| Channel | Tactic |
|---|---|
| Frappe forum and community | First place to announce; native audience |
| ERPNext partner network | Direct outreach to top 20 Indian ERPNext implementers |
| Indian dev Twitter / LinkedIn | Founder-led content; weekly architecture posts |
| Hacker News | Show HN at v0.1.0 with a technically substantive post |
| YouTube | Architecture walkthroughs; "Friday managing an ERPNext business" demos |
| Conferences | PyCon India, FOSDEM India, Frappe Conference, NASSCOM events |
| Indian tech press | YourStory, Inc42, Entrackr — the "Indian open-source agentic framework" angle |
| GitHub trending | Repo metadata tuned for trending exposure on launch day |

Paid ads on Google / Facebook / LinkedIn are rejected until v1.0. OSS acquisition cost is dominated by organic; ads waste budget.

---

## 7. Friday Labs hosted platform

Separate project, separate revenue line. Starts year 2+.

**Concept.** Managed Friday for businesses that want the value but not the operations. Friday Labs hosts; customers use.

**Tiers.** Free trial, Starter (solo / micro-SMB), Growth (growing SMB), Enterprise (mid-market with SLA), and Self-Host Support contracts. Specific pricing is set during the design-partner phase based on observed unit economics — pre-pricing here would be speculation.

**Friday Labs owns:** hosting in Indian regions for data residency; auto-upgrades and security patches; usage metering and billing; multi-tenant isolation; customer dashboard; L1 support.

**Friday Labs does not own:** the open-source code (GPL v3, public repo), customer data (encrypted with customer-controlled keys), or any lock-in mechanism (one-click export to self-hosted is always available).

Open-core done right: the platform is free, the convenience is paid.

---

## 8. Contributor revenue share

The novel piece. Friday Labs revenue, after operations, flows back to community contributors based on contribution metrics.

**Metric sources:**

- Merged PRs (weighted by size, complexity, criticality).
- Skill contributions (weighted by usage across Friday Labs tenants).
- Documentation contributions.
- Issue triage and community support.
- Security disclosures.

**Distribution model** (placeholder, ratified by the community before activation):

- **40%** retained for Friday Labs operations and reserves.
- **30%** to core maintainers, split by contribution score.
- **20%** to the broader contributor pool, split by contribution score.
- **10%** to a community fund for grants, events, outreach.

**Why this matters.** Most "open-source startups" extract value from contributors and monetise privately. Friday inverts that: contributors whose work generates revenue receive a share. Especially relevant for Indian developers — even a modest share is meaningful at INR purchasing power.

**Governance.** Revenue and distribution reported publicly in an annual transparency report. Contribution scores public and auditable. A community-elected committee reviews and adjusts the formula yearly.

---

## 9. Success markers

### Year 1 — launch and initial growth

- 1,000 GitHub stars.
- 50 production deployments (mostly self-hosted).
- 20 active contributors.
- 3 written case studies of Indian businesses using Friday.

### Year 2 — Friday Labs launch

- 10,000 GitHub stars.
- 500 self-hosted deployments.
- 50 Friday Labs paying customers.
- 100 active contributors.
- First contributor revenue distribution.

### Year 3 — sustained growth

- Friday is the default agentic framework for Indian Frappe/ERPNext deployments.
- Friday Labs revenue covers full operations and a meaningful contributor share.
- Recognised by NASSCOM, the broader Indian open-source community, and the Frappe project.
- One dedicated conference: Friday Conf India.

---

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Anthropic or OpenAI release competing enterprise agent platforms | Lean into open-source, self-hosting, and data sovereignty — they cannot match those |
| Frappe core absorbs agentic features; Friday becomes redundant | Become so good and so embedded that Friday is what they would absorb; collaborate, don't compete |
| Community contributions don't materialise | Core team produces 80% of value for the first year; revenue-share kicks in to attract contributors |
| Friday Labs operational complexity sinks the team | Don't launch Friday Labs until Phase 1 product is rock-solid; small early-customer beta first |
| Indian SMBs don't adopt agentic automation fast enough | Lead with concrete ROI on a single concrete workflow, not "platform" pitches |
| Founder bandwidth | Document everything (the design dossier already does); build for handoff from day one |

---

## 11. The decision filter

Every decision passes this test:

> Does this make Friday more useful for an Indian SMB founder running their business on ERPNext, who wants automation without losing control or paying through the nose?

If yes → ship. If no → drop.

Opinionated on purpose. Optimising for everyone optimises for no one.
