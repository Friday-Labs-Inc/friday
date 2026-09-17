# ADR-0001 — Friday is Frappe + Hermes

**Status:** Accepted · 2026-09-17

## Context

Friday's purpose had drifted across three incompatible readings: a public
open-source framework, the engine under one studio product, and internal
infrastructure. The repository showed all three at once — a public repo
described as a kernel, a vocabulary ratchet defending kernel purity, and a
product's vocabulary leaking through 37 of 166 design and rollout documents.

The founding thesis was never actually abandoned; it was buried. Documents
41, 48, 51, 52 and 54 describe one thing: take the Hermes agent, port it into a
forked Frappe backend, and get an agentic orchestration platform with Frappe's
governance underneath it.

## Decision

**Friday is Frappe plus Hermes.** A hard fork of Frappe with the Hermes agent
ported in as a first-class part of the framework, producing an enterprise-grade
agentic orchestration platform that supports multiple domains.

Frappe supplies the substrate: DocTypes, roles and permissions, workflows, the
scheduler, background jobs, the Desk. Hermes supplies the agent: the turn loop,
context assembly, compression, the gateway, memory, cron. Friday is the
combination, plus the governance layer neither has alone — a permission matrix,
immutable audit rows, an approval gate, and actor provenance.

OpenClaw is an acknowledged design influence (`docs/design/15`), not a source of
code.

## Consequences

- The fork is required by the definition, not a tactical choice. See ADR-0002.
- "Complete" for a Hermes capability means *observed running*, never *code
  exists*. See ADR-0012.
- Domain-specific work belongs to a domain app, never the kernel. See ADR-0004.
- The Hermes port ledger (`docs/ports/`) is promoted from a historical record to
  the working definition of what Friday must contain. See ADR-0008.

## Evidence

- `docs/design/41-porting-strategy-hermes-erpnext-raven.md` — "Hermes proves the
  right coordination shape. The failure case proves why Friday needs Frappe."
- `attributions.md` — `gateway` REWRITE, `cli` and `agent_runner` ADAPT.
- `NOTICE` — "Friday is not a fork of Hermes Agent or OpenClaw." Hermes is MIT;
  Friday is GPL v3; adaptation with attribution is clean.
