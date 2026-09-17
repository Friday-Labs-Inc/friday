# 46 — Security Claims Audit

> **Purpose:** Resolve Gap 9 from `40-gap-analysis-and-resolution-plan.md`. Friday's public-facing security narrative (docs `04` and `20`) leans on specific factual claims about Hermes and OpenClaw — CVE numbers, vulnerability counts, audit dates, named issues. This document audits each claim, marks what can and cannot be verified before public release, and supplies replacement language for anything that cannot be sourced.

---

## 1. Why This Audit Exists

Doc `40` records the decision plainly:

> Replace uncited competitor-specific security claims with broader architectural risk statements until sources are verified.

Friday's security thesis is **structural**: permission-as-architecture, not permission-as-configuration. That thesis stands on its own. It does not need named CVEs to be true. Specific numbers, on the other hand, are:

- **Reputationally expensive if wrong** — a single bad CVE number undermines the whole document.
- **Legally adjacent** — naming a competitor product and attaching unverified severity scores invites pushback.
- **Easy to fix** — every load-bearing claim can be rewritten as an architectural statement without losing rhetorical force.

This document is the gate. Nothing in docs `04` or `20` referring to Hermes or OpenClaw CVE numbers, vulnerability counts, audit dates, or issue numbers may remain in a publicly published Friday repository until it is verified here or rewritten per Section 4.

---

## 2. Claims Inventory

Every specific factual claim about Hermes or OpenClaw currently appearing in the dossier.

| ID  | Claim (verbatim or close) | Source | Specificity |
|-----|---------------------------|--------|-------------|
| C1  | "Token exfiltration via crafted webpages (CVE class)" — OpenClaw | `04-security-model.md:8` | Generic class, no CVE number |
| C2  | "Privilege escalation through token scope misuse (CVE-2026-32922, CVSS 9.9)" — OpenClaw | `04-security-model.md:9` | **Specific CVE + CVSS** |
| C3  | "Prompt-injection-driven tool call chains without admin approval" — OpenClaw | `04-security-model.md:10` | Generic |
| C4  | "Data exfiltration via malicious skills" — OpenClaw | `04-security-model.md:11` | Generic |
| C5  | "January 2026 audit: 512 vulnerabilities, 8 critical" — OpenClaw | `04-security-model.md:12` | **Specific count + date** |
| C6  | "Default Allow-All security posture in fresh installs" — Hermes | `04-security-model.md:15` | Specific behaviour claim |
| C7  | "Path traversal in WeChat adapter (CVE-2026-7396)" — Hermes | `04-security-model.md:16` | **Specific CVE** |
| C8  | "Memory poisoning (issue #496)" — Hermes | `04-security-model.md:17` | **Specific issue number** |
| C9  | "Supply chain risk via LiteLLM dependency" — Hermes | `04-security-model.md:18` | Named dependency |
| C10 | "LiteLLM-style attacks" — threat model item | `04-security-model.md:29` | Named dependency, attack-pattern reference |
| C11 | "Tirith integration … inherited" — claim Friday adopts a specific Hermes component | `04-security-model.md:107-113` | Specific component name |
| C12 | "Hermes: allow-all default, WeChat path traversal, memory poisoning" | `20-brainstorm-session-tree.md:43` | Bundle of C6/C7/C8 |
| C13 | "OpenClaw: 512 vulnerabilities, prompt injection, token exfiltration" | `20-brainstorm-session-tree.md:44` | Bundle of C5/C3/C1 |

Doc `01-vision-and-architecture.md` mentions Hermes/OpenClaw only at the capability level (agent loop, skills, learning loop). It carries no security severity claims and needs no edits from this audit.

Doc `15-openclaw-insights-friday-refinements.md` cites a named talk (Krentsel, UC Berkeley NEXT, March 2026) and explicitly states Friday is "not affiliated with OpenClaw, Krentsel, or UC Berkeley." It makes no CVE or vulnerability-count claims. **No edits required.**

---

## 3. Verification Status

Each claim is placed in one of four buckets.

### Bucket A — Verified with Primary Source
Empty. As of writing, no claim in Section 2 has a primary-source citation in the Friday dossier.

### Bucket B — Unverifiable / Likely Synthetic
Specific identifiers that cannot be confirmed against any public registry or tracker the maintainer can cite:

- **C2** — `CVE-2026-32922` and the CVSS 9.9 score. No primary citation in the dossier. Treat as unverifiable.
- **C5** — "January 2026 audit: 512 vulnerabilities, 8 critical." No audit report attached, no auditor named, no link.
- **C7** — `CVE-2026-7396`. No primary citation.
- **C8** — Hermes "issue #496." No repository link.

These are exactly the kind of details that look authoritative in a doc and collapse the moment anyone checks them. They must not appear unmodified in a public Friday release.

### Bucket C — Generic and Defensible
Pattern-level claims that describe well-known agentic-system failure modes and do not depend on a specific CVE to be true:

- **C1** — token exfiltration via crafted webpages (a documented class of LLM-tool-use attacks).
- **C3** — prompt-injection-driven tool chains without approval (broadly documented in the LLM security literature).
- **C4** — data exfiltration via malicious skills (inherent to plugin-style agent architectures).
- **C6** — permissive-by-default posture in agent frameworks (commonly observed pattern).
- **C9 / C10** — supply chain risk via third-party LLM-routing dependencies (named in industry post-mortems).

These can stay, with phrasing tightened to architectural-pattern language. They do not need to name a specific competitor to make Friday's structural case.

### Bucket D — Component Inheritance Claim
- **C11** — Tirith integration. This is not a vulnerability claim about a competitor; it is a Friday architectural claim that Friday inherits a specific external component. Verify by Phase 1: either Tirith is in the port plan (`41-porting-strategy-hermes-erpnext-raven.md`) and the spike (`44-technical-feasibility-spike.md`) confirms it ships in v0.1, or this paragraph is rewritten as a deferred Phase 2 design note.

---

## 4. Replacement Language

For each Bucket B claim, the public-safe replacement.

### Replace C2, C5, C7, C8, C12, C13

The "Why This Matters" section of `04-security-model.md` (lines 5–20) currently leads with specific CVE numbers and a vulnerability count. Replace with architectural-pattern language:

> Both Hermes and OpenClaw, like most current-generation agentic frameworks, are documented to share a common security shape: permissions are treated as runtime configuration rather than architectural invariants, default postures lean permissive, and tool/skill execution boundaries are enforced inside the agent process rather than at a separate trust boundary. Public discussion of both projects has surfaced examples of token exfiltration via untrusted web content, prompt-injection-driven tool-call chains, malicious-skill data exfiltration, permissive defaults in fresh installs, adapter-level input-handling bugs, memory-channel poisoning, and supply-chain exposure through shared LLM-routing dependencies.
>
> The root cause across the category — not unique to any one project — is that **security is treated as configuration, not as architecture.** Friday inverts this: Frappe's role-based permission system enforces access at the gateway layer before any skill executes.

This keeps the rhetorical force, removes every unverified identifier, and makes the claim about an industry pattern rather than two named products' specific bug counts.

### Replace doc 20 lines 43–44

Currently:

```
└─ Security issues in both Hermes and OpenClaw
   ├─ Hermes: allow-all default, WeChat path traversal, memory poisoning
   └─ OpenClaw: 512 vulnerabilities, prompt injection, token exfiltration
```

Replace with:

```
└─ Security issues common to current agentic frameworks
   ├─ Permissive defaults in fresh installs
   ├─ Adapter / input-handling bugs (path traversal class)
   ├─ Memory-channel poisoning
   ├─ Prompt-injection-driven tool chains
   ├─ Token exfiltration via untrusted web content
   └─ Supply-chain exposure via shared LLM-routing dependencies
```

Same patterns, no fragile numbers.

### Keep (with light edits): C1, C3, C4, C6, C9, C10

These survive in the replacement paragraph above. No further action needed.

### Resolve C11 (Tirith) by Phase 1 spike

`04-security-model.md:107–113` currently states Friday "inherits Hermes' Tirith integration." This is a forward-looking architectural claim, not a competitor vulnerability claim, but it is load-bearing for the security narrative.

Action: confirm during the spike (`44-technical-feasibility-spike.md`) whether Tirith ships in v0.1. If yes, keep the section. If no, rewrite as:

> **Layer 7 — Shell-Command Policy Engine (Phase 2)**
> For shell-style commands invoked by skills, Friday will integrate a pattern-matching policy engine (curl-pipe-bash, homograph URLs, exfiltration patterns) before container execution. Phase 1 disallows shell-style skills entirely; the policy engine is a Phase 2 prerequisite for re-enabling them.

This is consistent with `42-phase-one-authority-contract.md`'s "fewer features, defensible" stance.

---

## 5. Edit Plan

Concrete file changes triggered by this audit, to be made as a follow-up commit before any public release:

1. **`04-security-model.md`** — replace lines 5–20 with the architectural-pattern paragraph in Section 4. Update lines 107–113 per the C11 resolution after the spike.
2. **`20-brainstorm-session-tree.md`** — replace lines 42–44 per Section 4.
3. **`40-gap-analysis-and-resolution-plan.md`** — mark Gap 9 as resolved by this document; move `docs/security-claims-audit.md` from "Missing Documents" to "Completed."
4. **No other docs require edits.** Doc `01` is capability-level only; doc `15` is talk-attributed and CVE-free.

Edits are deliberately deferred to a follow-up commit so this audit lands first as a reviewable decision record, and the source-doc edits land second with a clear pointer back to this file.

---

## 6. Standing Rule

Going forward, any new factual claim in a public Friday document that names a third-party product and attaches a CVE number, CVSS score, vulnerability count, audit date, or issue number must be:

1. Linked to a primary source (NVD, GitHub Security Advisory, the project's own security disclosure, or a named audit report), **or**
2. Rewritten as an architectural-pattern claim per Section 4, **or**
3. Held out of any branch that may be made public.

This rule applies to docs in `docs/design/`, `docs/project/`, `README.md`, the website, and any blog or launch material derived from them. The maintainer is the sole approver.

---

## 7. Status

| Gap 9 sub-item | Status |
|----------------|--------|
| Inventory of specific claims | Complete (Section 2) |
| Verification bucketing | Complete (Section 3) |
| Public-safe replacement language drafted | Complete (Section 4) |
| Source-doc edits applied | **Pending follow-up commit** |
| Standing rule recorded | Complete (Section 6) |

Gap 9 is resolved at the **decision** level by this document. It is resolved at the **codebase** level once the edits in Section 5 land.
