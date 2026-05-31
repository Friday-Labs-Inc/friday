# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Bench command registration for the Friday CLI surfaces.

PLAIN ENGLISH
=============

Frappe's bench CLI is built with click. Each Frappe app contributes
subcommands by exposing a `commands` list at the app-root module's
`commands` submodule — Frappe's `utils/bench_helper.py:get_app_commands`
does `importlib.import_module(f"{app}.commands")` and reads the
`commands` attribute. So bench's standard pickup point for the Frappe
app is `frappe/commands/__init__.py`, not `hooks.py`.

Because friday_core lives inside the Frappe fork (we chose "Option C —
keep everything inside frappe/friday_core/" — see project memory), our
friday command group is appended to Frappe's `get_commands()` aggregator
at `frappe/commands/__init__.py`. The edit there imports `commands` from
this module and adds it to the existing tuple.

We expose a single click Group named `friday` so all Friday subcommands
are namespaced — `bench --site X friday chat`,
`bench --site X friday <future-subcommand>`. No collisions with stock
Frappe command names.

WHY click AND NOT argparse / typer
==================================

Because Frappe ships click and its own command loader expects click
groups. Bringing in another argument parser would mean either
re-implementing the bench glue or wrapping click anyway — neither buys
anything. See `frappe/commands/__init__.py` for the loader.
"""

from __future__ import annotations

import click

# Use Frappe's `pass_context` style so the command runs inside a Frappe
# site context (the wrapping `bench --site <name>` invocation sets that
# up before our command body runs).
from frappe.commands import pass_context

from frappe.friday_core.cli.chat import run_repl


@click.command("chat")
@click.option(
	"--profile",
	required=True,
	help="Agent Profile name to chat with (must exist on the site).",
)
@pass_context
def chat(context, profile):
	"""Open an interactive chat session with an Agent Profile.

	Example:

	    bench --site friday.localhost friday chat --profile "My Agent"
	"""
	import frappe

	for site in context.sites:
		try:
			frappe.init(site=site)
			frappe.connect()
			run_repl(profile)
		finally:
			frappe.destroy()


@click.group("friday")
def friday():
	"""Friday agent framework — interactive and administrative commands."""
	pass


friday.add_command(chat)

# Frappe's command loader reads this `commands` symbol from the module
# named in `hooks.py`. Each item is a click Command or Group; we expose
# the top-level `friday` group, and bench wires it under the `bench`
# CLI automatically.
commands = [friday]
