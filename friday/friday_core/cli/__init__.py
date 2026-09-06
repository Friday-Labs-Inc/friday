# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
The Friday CLI — `bench friday chat`, the first interactive surface.

This package is where the local interactive surfaces of Friday live. For
v0.1 there is exactly one: an in-process REPL that lets you converse
with an Agent Profile from the terminal.

PLAIN ENGLISH
=============

To interact with Friday from a terminal, run:

    $ bench --site friday.localhost friday chat --profile "My Agent"
    Friday chat — profile 'My Agent', session abc-123
    > hello
    You have 0 tool(s) available: (none).
    echo: hello
    >

Every line you type is recorded as a Chat Message DocType row
(direction=inbound). Every reply is also recorded (direction=outbound).
The audit trail is automatic.

HOW THIS CLI FITS INTO THE UNIFIED GATEWAY PATTERN
===================================================

The CLI is a **thin adapter** in the unified-gateway sense (see
`docs/design/47-gateway-design-decisions.md`). It does NOT import
`agent_runner` directly. It writes inbound Chat Message rows; the
gateway picks them up via `doc_events.after_insert` and runs the
pipeline. The CLI then reads the outbound row directly from the
database (which is safe because the platform "cli" has
`dispatch_mode="sync"`, so the gateway runs inline within the
inbound row's `insert()` call — by the time `insert()` returns,
the outbound row exists).

WHY DIRECT DB READ AND NOT publish_realtime FOR CLI
====================================================

Per §4 Q2 of the design-decisions doc — under single-tenant scope,
adding a socket.io client to the CLI is overhead with no benefit.
The gateway still fires `publish_realtime("chat.outbound", ...)`
universally, so future Telegram / Slack / Raven adapters subscribe
to it without any gateway change. CLI just reads the DB.

MODULES
=======

  - `chat.py`     — the REPL function `run_repl`, the inbound-writer
                    helper, the outbound-reader helper.
  - `commands.py` — the `click` registration that lets bench find
                    `friday chat` as a subcommand.
"""
