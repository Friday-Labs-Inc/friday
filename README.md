# Friday

**Frappe + Hermes.** A hard fork of the Frappe framework with the Hermes agent
ported into it, making an agentic orchestration platform that Friday Labs runs
for itself — agents that act as themselves, under their own roles, with every
decision audited.

Frappe supplies the substrate: DocTypes, roles, workflows, the scheduler,
background jobs. Hermes supplies the agent: the turn loop, context assembly,
compression, the gateway, memory. Friday adds the governance neither has alone —
a permission matrix, immutable audit rows, an approval gate, actor provenance.

It hosts many domains; each is a separate Frappe app carrying its own pipeline
as data. It is a platform we operate, not software we distribute
([ADR-0003](docs/adr/0003-internal-enterprise-platform.md)).

**Status: under restructuring.** The port is architecturally complete on paper
and has never run end to end. What is and is not true today is recorded in
[CONTEXT.md](CONTEXT.md); the exit criterion is
[ADR-0012](docs/adr/0012-re-baseline-exit-criterion.md).

## Start Here

**New to Friday? Read [CONTEXT.md](CONTEXT.md) first** — the vocabulary of this
codebase and which of its rules are real.

After that:

- [Decisions](docs/adr/) — architecture decision records; start at [ADR-0001](docs/adr/0001-friday-is-frappe-plus-hermes.md)
- [Hermes port ledger](docs/ports/) — what Friday must contain, and its state
- [Roadmap](docs/ROADMAP.md)
- [GitHub Project Plan](docs/project/GITHUB_PROJECT_PLAN.md)
- [Contributing](CONTRIBUTING.md) — PR workflow and rules
- [AI Contributors Policy](docs/contributing/AI_CONTRIBUTORS.md) — rules for AI agents and their sponsors
- [Security](SECURITY.md)

## License

Friday is licensed under GNU GPL v3 or later. See [LICENSE](LICENSE).
