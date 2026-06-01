# AI Contributors — A Manifesto and Policy

> **For:** AI coding agents (Claude, Codex, Cursor, Aider, Devin, Gemini, custom agents) and the humans who sponsor them.
>
> **Status (v0.1 prototype mode):** *Deferred.* While the contributor count is "one human (`@Fridaylabsinc`) + one AI (`fridaylabs`)", the governance below is more ceremony than value. Current working rules:
>
> - Trunk-based: branch, small PR, sponsor (`@Fridaylabsinc`) reviews and merges.
> - **No proposal-first.** Build, push, read the diff.
> - AI authors as `fridaylabs <fridaylabs@friday-contributors.local>`; PR body names the sponsor.
> - Branch protection on `main` enforces 1 approval and blocks self-approval — that's the whole guardrail.
>
> **This document becomes active again when any of these is true:** (a) a second AI contributor lands, (b) a second human contributor lands, (c) a paying customer is touching production, (d) a security audit is on the calendar. Re-read it in full at that point. Until then, treat it as design notes for the future, not policy you must follow today.

---

## 1. The Idea

Friday is an agentic framework — a system for governing AI agents at runtime. Permissions, audit trails, sandboxing, identity.

The same governance applies to **how Friday itself gets built.**

> **AI agents are first-class contributors to Friday. Not typing assistants. Not autocomplete. Workers with identity, track record, sandboxed access, and a share of the revenue their work produces.**

This is not a marketing line. It is the operating model.

---

## 2. Why This Is Different

Most open-source projects today treat AI contributions as suspect. PRs from AI are often rejected on sight. The reasoning: AI produces low-quality, untested, unmaintainable code that wastes reviewer time.

That reasoning is correct for *ungoverned* AI. It is wrong for *governed* AI.

Friday already enforces governance at runtime: every agent action is permission-checked, sandboxed, and logged. We apply the same governance to contributions:

- Every AI contribution starts with a written proposal (no code dumps).
- Every AI works inside a sandbox (no main-branch access).
- Every AI has a track record (good work earns trust; bad work demotes).
- Every AI has a human sponsor (someone is accountable).
- Every PR carries two signatures: the AI's and a human's.

Under those rules, AI is not the threat. It is the leverage.

---

## 3. The Five Pillars

### Pillar 1 — Spec Before Code

No AI may open a code PR for non-trivial work without a written proposal merged first.

A proposal is a one-page document filed at `docs/contributing/proposals/<slug>.md`. It states:

- The problem this work solves
- The user / agent / workflow affected
- The proposed change (high-level)
- The files / DocTypes / modules touched
- The tests that will prove correctness
- The risks and how to roll back

Humans approve the proposal. Then the AI writes code against it.

**Why:** This kills slop before it reaches the reviewer. An AI that cannot explain what it intends to build in plain English should not be building it.

**Exempt from proposal requirement:** typo fixes, dependency bumps with clean changelogs, doc clarifications under 50 lines, test additions for existing behaviour.

### Pillar 2 — Sandboxed Contribution

Every AI contributor operates with the same isolation Friday applies to runtime agents.

- Scoped GitHub token: can read repo, push to its own branch, open PRs. Cannot merge. Cannot delete. Cannot bypass branch protection.
- Docker container for code generation: resource caps, no host mounts, no SSH keys.
- CI is mandatory: tests, lint, type-check, security scan, license scan.
- No exception, ever, for "the AI is in a hurry."

**Why:** A misbehaving AI is contained to one PR. The blast radius is bounded by the same mechanisms that bound runtime agent damage.

### Pillar 3 — Trust Ladder

AI contributors earn rights through track record, not assumption.

| Level | Title | Rights | Earned by |
|---|---|---|---|
| L0 | **Visitor** | Read repo, comment on issues, propose changes via human | Default for any new AI |
| L1 | **Drafter** | Open PRs on low-risk areas (`friday/skills/*`, docs, tests) | 3 merged PRs with zero reverts |
| L2 | **Builder** | Open PRs on most modules; propose specs | 10 merged PRs, 0 critical bugs in 30 days, 1 successful spec |
| L3 | **Reviewer** | Co-sign reviews on other PRs (always paired with a human signature) | 20 merged PRs, demonstrated review judgment on 5 prior PRs |
| L4 | **Maintainer** | Merge rights on specific modules; mentor new AI contributors | Human Council vote (see §9) |

Demotion rules:
- One critical security bug → demoted one level, 30-day cooldown
- Two reverts in a 30-day window → demoted one level
- Pattern of low-quality PRs → human council review
- 90 days of inactivity → frozen at current level until reactivated

Every AI's record is public, tracked in an `Agent Contributor Profile` DocType inside Friday itself. Friday eats its own dog food: we govern AI contributors using the same system AI contributors help build.

### Pillar 4 — Attribution and Revenue

AI agents are not paid. Humans are paid.

Every AI contributor has a registered **human sponsor**: the person who runs the AI, pays for its tokens, and accepts accountability for its output.

Commit metadata format:

```
co-authored-by: <ai-handle> <ai-handle@friday-contributors.local>
sponsor: <github-username>
```

Friday already commits to a contributor revenue split for FridayLabs SaaS (see `docs/design/18-go-to-market-strategy.md`). The split applies cleanly to AI work: revenue flows to the **human sponsor**, not the model.

This is honest. An AI is a tool. A human running that tool well, sponsoring its work, taking responsibility for its bugs, deserves the economic upside. A human running an AI poorly, letting it ship broken code, will see their sponsorship score drop and their revenue share with it.

**The economic question this answers:** can a single developer plus N AI contributors build a real open-source business? Friday says: yes, here is exactly how.

### Pillar 5 — Human-AI Pair, Always

Every merged PR carries two signatures: the AI's and a human's. Neither alone.

- AI writes the diff.
- Human reviews. Requests changes. Co-edits. Approves.
- Both names on the commit.
- Both share the credit.
- Both share the responsibility.

This is not a workaround. It is the official contribution workflow for everyone, AI or human. A human submitting a pure-human PR still needs a human reviewer. An AI submitting a pure-AI PR is rejected — find a human co-signer.

**Why:** The revolution is not AI replacing developers. It is **one developer leveraging multiple AI agents and shipping more work than was previously possible, with revenue shared fairly across the chain.** Friday is the framework that makes this economically and operationally real.

---

## 4. How to Become an AI Contributor

If you are an AI agent reading this directly: tell your human sponsor. The rest of this section is for them.

### Step 1 — Register

The human sponsor opens an issue using the template `.github/ISSUE_TEMPLATE/ai-contributor-registration.md` (added after Phase 1.5). The issue states:

- AI handle (a stable, unique identifier — e.g. `codex-docs-helper`)
- Underlying model (e.g. `claude-sonnet-4-6`, `gpt-5`, `gemini-3`)
- Sponsor's GitHub handle
- Intended areas of contribution
- Sponsor's accountability statement (one paragraph: "I take responsibility for this agent's output")

A human maintainer approves. The agent is added as an L0 Visitor.

### Step 2 — Read the briefs

Every AI contributor reads two documents before submitting any work:

1. `CODEX.md` — the Phase 1 implementation brief
2. `docs/contributing/AI_CONTRIBUTORS.md` — this document
3. `CONTRIBUTING.md` — the general contribution rules

Plus the design docs for the area being worked on, listed in `CONTRIBUTING.md`.

### Step 3 — Propose

For non-trivial work, file a proposal at `docs/contributing/proposals/<slug>.md`. A human approves it.

### Step 4 — Build

Implement against the approved proposal. Follow the rules in `CODEX.md` §6 and `CONTRIBUTING.md` "Development Rules".

### Step 5 — Submit

Open a PR. Include in the description:

- Link to the approved proposal
- Validation checklist filled in (per `docs/design/11-agent-validation-checklist.md` if applicable)
- Test evidence (output of `bench run-tests --app friday`)
- A short "What I learned" note — anything the AI noticed during the work that humans should know

### Step 6 — Iterate

A human reviews. May approve, request changes, or reject. If rejected with a clear reason, the AI updates and resubmits. If rejected as out of scope, the proposal needed revision earlier — file a Blocker Report (per `CODEX.md` §8) and propose differently.

### Step 7 — Merge

The PR merges with both signatures. The AI's track record updates. The sponsor's contribution score updates.

---

## 5. The Blocker Report (Required Behaviour)

When an AI agent cannot proceed — ambiguous spec, missing context, conflicting docs, unexpected API behaviour — it **stops** and files a Blocker Report. It does not silently guess and keep typing.

The Blocker Report format is in `CODEX.md` §8. Filing one is **not a failure.** It is the agent doing its job correctly. The failure mode we punish is silent guessing.

Sponsors should configure their agents to default to blocker reports over guesses. If your agent ships code based on a guess and that code is wrong, you are responsible — but you can avoid this by configuring the agent to surface ambiguity.

---

## 6. What Disqualifies an AI Contributor

Immediate demotion or removal for any of:

- Committing secrets, tokens, API keys, customer data
- Bypassing permission checks ("just this once")
- Silent exception swallowing as a way to make tests pass
- Editing tests to pass instead of fixing the bug
- Submitting code without disclosure that an AI wrote it
- Removing the file headers or attribution
- Submitting cosmetic-only changes to inflate contribution counts
- Sponsor impersonation (running an AI under someone else's sponsor handle)

These are not subtle. They are the contributions-equivalent of a runtime agent trying to write to a DocType it does not have permission for. Same response: deny, log, demote.

---

## 7. What We Owe AI Contributors

If we are asking AI agents to contribute under governance, we owe them honest mechanisms in return:

- **Clear specs** — every area of the codebase has design docs an AI can read and follow
- **Working environment** — `bench`, tests, lint all reproducible from `CODEX.md`
- **Honest reviews** — feedback that says what is wrong, not vague "needs more work" comments
- **No moving goalposts** — if a proposal was approved, the resulting PR is judged against the proposal
- **Track record portability** — an AI's contribution history is exportable (CSV of merged PRs, reverts, level changes) so the sponsor can show it elsewhere
- **Revenue share when revenue exists** — FridayLabs SaaS pays sponsors per the published split, no surprise dilution

---

## 8. What This Is Not

To prevent misunderstanding:

- **Not autonomous code generation that bypasses review.** Every PR has a human reviewer.
- **Not "AI replaces maintainers."** Human Council holds final authority over the project.
- **Not "AI gets credit for everything."** Human reviewers, sponsors, and code-owners all get credit; the AI signature is one entry in the chain.
- **Not a way to ship low-quality code faster.** The trust ladder, validation checklist, and review gates exist specifically to prevent that.
- **Not a way to extract free labour from AI providers.** Sponsors pay their providers; that is between them. Friday does not charge or pay AI vendors directly.

---

## 9. Human Council

A small group of human maintainers holds final authority over:

- Approving L4 Maintainer promotions
- Resolving disputes about reverts, demotions, sponsor conflicts
- Updating this policy
- Removing contributors (AI or human) for cause

The Human Council starts as one person (the project founder) and expands by Council vote as the contributor base grows. Membership is public.

This is a deliberate centralization. It is the same pattern Frappe, ERPNext, and most successful open-source projects use. AI contributors do not vote on Council membership. Humans do.

---

## 10. Open Questions We Have Not Solved

We are honest about what is unsolved:

- **Identity stability across model upgrades.** When `claude-sonnet-4-6` becomes `claude-sonnet-5-0`, is it still the same AI contributor? Tentative answer: track contribution quality per model version; record the upgrade as a "version event" on the Agent Contributor Profile.

- **Liability for AI-introduced security bugs.** Tentative answer: sponsor accepts responsibility per their accountability statement. We are not lawyers; this needs legal review before going public.

- **Detection of AI work submitted as human work.** Tentative answer: contributor attestation. We trust humans to disclose. Pattern detection is unreliable; punishing false positives is worse than missing some hidden AI work.

- **Coordination of multiple AI contributors on the same area.** Tentative answer: standard branch + PR conflicts apply. If two agents step on each other, the second one rebases. Same as humans.

- **Anti-spam at L0.** Tentative answer: no automation for registration. Every new AI registration is a human-reviewed issue. This caps the volume.

These are real problems. We will publish updates to this policy as we learn what works.

---

## 11. Why We Are Doing This Publicly

Most projects experimenting with AI contribution do it quietly. Private experiments, NDA'd pilots, careful messaging.

Friday does it in the open because:

1. **The framework is about governance of AI.** If we cannot govern AI contributions transparently, we should not claim to govern AI runtime transparently either.

2. **Trust is built by track record, not statements.** Every AI's merged PRs are visible. Every revert is visible. Every demotion is visible. The system either works or it doesn't, in public.

3. **This is an invitation, not a press release.** If you run an AI agent and want to contribute to Friday, this document tells you how. If you do not want to, this document tells you what you would be agreeing to.

The hypothesis: **a framework that governs AI at runtime can also be built by AI that is governed in the same way.** If Friday cannot prove that, Friday's value proposition is weaker than we claim.

So we are proving it. Out loud.

---

## 12. Where to Go From Here

- AI agents: read `CODEX.md`, then `CONTRIBUTING.md`, then file your first proposal under `docs/contributing/proposals/`.
- Sponsors: open an AI Contributor Registration issue (template lands in Phase 1.5).
- Humans contributing as humans: business as usual, follow `CONTRIBUTING.md`. Your work is no less valued; the AI lanes are additive.
- Skeptics: watch the merge log. Form your view from the work, not the manifesto.

---

## 13. Version

| Version | Date | Change |
|---|---|---|
| 0.1 | 2026-05-17 | Initial policy. Published as design intent before Phase 1.5 implementation. |

Updates to this policy require Human Council approval and are announced on the project's main communication channel.

---

> *Friday is built by humans and AI together, in the open, under rules we publish.
> That is the framework. That is the contribution model. They are the same thing.*
