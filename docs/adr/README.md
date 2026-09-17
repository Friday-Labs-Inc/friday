# Architecture Decision Records

One decision per file, numbered, newest wins. Read `../../CONTEXT.md` first for
the vocabulary these use.

An ADR is **Accepted** (a decision we stand behind) or **Superseded** (by a
later ADR, named). There is no status meaning "built" — claims about behaviour
need evidence, and live in the ADR's Evidence section with the command that
proved them.

If your work contradicts an ADR, surface it rather than silently overriding:
> _Contradicts ADR-0007 (quarterly upstream merge), but worth reopening because…_

Older decisions also live in `../decisions/spike-results.md` (D1–D8, 2026-05-17)
and, for historical reasoning only, `../archive/`. Contradicting those is the
same kind of event: surface it.

| # | Decision |
|---|---|
| [0001](0001-friday-is-frappe-plus-hermes.md) | Friday is Frappe + Hermes |
| [0002](0002-keep-the-frappe-fork.md) | Keep the hard fork of Frappe |
| [0003](0003-internal-enterprise-platform.md) | Internal platform, enterprise-grade |
| [0004](0004-multi-domain-one-bench.md) | One Friday bench hosts every domain app |
| [0005](0005-friday-is-never-a-dependency.md) | If Friday is down, every product still works |
| [0006](0006-domain-manifest-is-the-configuration.md) | A domain app's manifest is its configuration |
| [0007](0007-track-frappe-upstream-quarterly.md) | Merge upstream Frappe v16 quarterly |
| [0008](0008-track-hermes-narrow-waist.md) | Track Hermes continuously, waist only |
| [0009](0009-archive-the-design-dossier.md) | Archive the dossier; CONTEXT.md + ADRs replace it |
| [0010](0010-blocking-test-ratchet.md) | CI blocks on a shrink-only test ratchet |
| [0011](0011-first-class-means-core-only-where-frappe-must-know.md) | "First-class" means core only where Frappe must know |
| [0012](0012-re-baseline-exit-criterion.md) | Re-baseline ends at verdicts + one running turn |
| [0013](0013-parked-domain-decisions.md) | Decisions parked as domain-app concerns |
| [0014](0014-week-one-scope.md) | Week one: ledger v2, one pillar running, docs cleared |
