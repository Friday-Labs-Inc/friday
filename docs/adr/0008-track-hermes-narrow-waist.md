# ADR-0008 — Track Hermes continuously, but only its narrow waist

**Status:** Accepted · 2026-09-17
**Relates:** ADR-0001, ADR-0003, ADR-0012

## Context

The Hermes port was taken as a snapshot around 2026-06-23 and declared complete
against it. Since then upstream has moved 10,000 commits and restructured (the
September "facade + siblings" decomposition), so the existing ledger's file map
no longer resolves. The reference copy it was audited against was never
committed and is gone; the snapshot commit was never recorded.

Upstream releases every three to four days. Its applicable source is ~338,000
lines against Friday's ~27,600. "Port every gap" without a boundary means a list
the size of Hermes.

Hermes states its own boundary: *"The core is a narrow waist; capability lives
at the edges."*

## Decision

**Track Hermes continuously. Port the waist; never the edges.**

- **Baseline:** `v2026.9.14` = `7a963716b81b`. The June snapshot is recorded as
  `40fddc9e4c45` for lineage. A pinned reference copy is restored so future
  audits have a source.
- **In scope (the waist):** the agent turn loop · context assembly and prompt
  caching · compression and state · the gateway (session, lifecycle, recovery,
  leases, slash commands, interrupt/steer/queue, delivery, mirror) · the core
  tool set as defined by `_HERMES_CORE_TOOLS` · cron.
- **Out of scope (edges), permanently, unless a domain app asks:** plugins, the
  CLI and TUI, optional skills, desktop/voice/TTS, specific third-party platform
  adapters, the website, browser control beyond what a domain needs.
- **Cadence:** re-run the ledger against each upstream release; port what the
  waist rule admits and what earns it.

Licence: Hermes is MIT, Friday is GPL v3. Carrying MIT code into a GPL work is
clean provided `attributions.md` keeps naming what was adapted.

## Consequences

- `_HERMES_CORE_TOOLS` includes **terminal**, **process_manage**, file
  read/write/patch, web search/extract, a browser suite and vision. Friday has
  none of the first two. These become real gaps — and the moment a terminal tool
  lands, "every skill runs sandboxed" (ADR-0003) stops being a property and
  becomes a prerequisite.
- The old ledger's "COMPLETE" verdicts are suspect twice over: stale against
  upstream, and never verified against a running system.
- `docs/ports/` survives the dossier archive because it is now the definition.

## Evidence

- Hermes `AGENTS.md`: "The core is a narrow waist; capability lives at the
  edges… the bar for a new *core* tool is high."
- `toolsets.py:11` `_HERMES_CORE_TOOLS`.
- Applicable LOC at `v2026.9.14`: agent 112,480 · tools 104,090 · gateway 84,886
  · state 16,488 · cron 14,907 · acp 4,140 · providers 785.
