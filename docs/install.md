# Installing Friday

Friday is a Frappe app. It requires a running Frappe bench with Python 3.14+.

## Prerequisites

- Frappe bench (v16 or later) — **stock**; Friday patches no framework file
- Python 3.14+
- PostgreSQL 14+ (or SQLite for development)
- Redis 6+
- **Raven** — required. Friday's chat front door: the bot you DM, the
  per-project channels, and the war room. Friday runs its own governed agent
  engine on top of it; Raven supplies the surface, not the intelligence.
- Docker (optional — only needed for sandboxed skill execution)

## Step 1 — Get a Bench on Stock Frappe

Friday is an ordinary Frappe app. Nothing about the framework is patched, so a
plain bench is all it needs:

```bash
bench init friday-bench --frappe-branch version-16
cd friday-bench
bench new-site friday.localhost --db-type postgres
```

## Step 2 — Add the App

```bash
bench get-app https://github.com/Friday-Labs-Inc/friday
bench --site friday.localhost install-app friday
```

## Step 3 — Install Raven

Raven is a required part of the platform, not an optional add-on:

```bash
bench get-app --branch develop https://github.com/The-Commit-Company/raven
bench --site friday.localhost install-app raven
```

Without it, `friday setup` refuses to provision surfaces and the health check
reports `down`. (Frappe's `required_apps` can only be declared by an app, not by
the framework — until Friday is packaged as an app, this install step and the
health check are how the requirement is enforced.)

## Step 4 — Apply Migrations

```bash
bench --site friday.localhost migrate
```

This creates the Friday DocTypes:
- Agent Profile
- Skill + Skill Credential
- Agent Project + Agent Task
- Chat Message + Chat Platform
- Execution Log + Permission Decision Log

## Step 5 — Configure an LLM Provider

1. Go to **Frappe Desk → Agent Settings**.
2. Create an **LLM Provider** (e.g., Minimax M2):
   - `provider_type`: `minimax`
   - `api_key`: your API key (stored encrypted)
   - `default_model`: `MiniMax-Text-01`
3. Link the provider to an **Agent Profile**.

## Step 6 — (Optional) Enable Docker Sandbox

For production skill execution, build the sandbox image:

```bash
cd apps/friday/friday/friday_core/sandbox
docker build -t friday/sandbox:latest -f Dockerfile .
```

The sandbox runs skill handlers in isolated containers with:
- No host network access (only Frappe API allowed)
- CPU and memory limits
- Short-lived scoped API tokens

## Step 7 — Verify

```bash
bench --site friday.localhost run-tests --app friday --module friday.friday_core.tests.test_doctypes_exist
```

All tests should pass.

## What's Next?

- [Quickstart](quickstart.md) — create your first agent and skill in 10 minutes
- [Architecture](architecture.md) — understand how the pieces fit together
- [Design docs](design/00-README.md) — full documentation