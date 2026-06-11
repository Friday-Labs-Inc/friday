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


@click.command("setup")
@click.option(
	"--provider-type",
	default="minimax",
	type=click.Choice(["minimax", "openai", "anthropic"]),
	help="Which model API to configure.",
)
@click.option("--model", "default_model", default=None, help="Default model id (defaults per provider).")
@click.option("--provider-name", default="Default Provider", help="Name for the LLM Provider record.")
@click.option("--profile", "profile_name", default="Friday", help="Name for the Agent Profile to create.")
@click.option(
	"--api-key",
	default=None,
	help="API key. PREFER the FRIDAY_API_KEY env var or the hidden prompt so the key stays out of shell history.",
)
@click.option("--base-url", default=None, help="Override the provider base URL.")
@click.option("--system-prompt", default=None, help="The agent's system prompt.")
@pass_context
def setup(context, provider_type, default_model, provider_name, profile_name, api_key, base_url, system_prompt):
	"""Configure a model provider + agent profile in one step (the `hermes setup` twin).

	Creates an LLM Provider (key stored ENCRYPTED) and an Agent Profile, then
	tells you how to chat with it.

	    bench --site friday.localhost friday setup            # interactive
	    FRIDAY_API_KEY=sk-... bench --site friday.localhost friday setup --provider-type minimax
	"""
	import os

	import frappe

	from frappe.friday_core.cli.setup import DEFAULT_MODELS, run_setup

	# Key precedence: --api-key > FRIDAY_API_KEY env > hidden prompt. Never logged.
	key = api_key or os.environ.get("FRIDAY_API_KEY")
	model = default_model or DEFAULT_MODELS.get(provider_type)

	for site in context.sites:
		try:
			frappe.init(site=site)
			frappe.connect()
			if not key:
				key = click.prompt(f"{provider_type} API key", hide_input=True)
			result = run_setup(
				provider_name=provider_name,
				provider_type=provider_type,
				api_key=key,
				default_model=model,
				profile_name=profile_name,
				base_url=base_url,
				system_prompt=system_prompt,
			)
			click.echo(f"✓ LLM Provider '{result['provider']}' ({provider_type}, {result['model']}) configured.")
			click.echo(f"✓ Agent Profile '{result['profile']}' is Active.")
			click.echo(f"\nTalk to it:\n  bench --site {site} friday chat --profile \"{result['profile']}\"")
		finally:
			frappe.destroy()


@click.command("setup-raven")
@click.option("--profile", default="Friday", help="Agent Profile the Raven bot answers as.")
@click.option(
	"--install",
	is_flag=True,
	help="If Raven is missing, run `bench get-app raven` + `install-app` + `migrate` first.",
)
@pass_context
def setup_raven(context, profile, install):
	"""Provision the Raven chat surface: bot, War Room channel, platform wiring.

	Raven stays a separate upstream app (design 58 Q1 — never bundled);
	this command automates its install (--install) and seeds everything
	Friday needs on top of it. Idempotent.

	Example:

	    bench --site friday.localhost friday setup-raven --install
	"""
	import subprocess

	import frappe
	from frappe.utils import get_bench_path

	for site in context.sites:
		frappe.init(site=site)
		frappe.connect()
		try:
			raven_installed = "raven" in frappe.get_installed_apps()
			if not raven_installed:
				if not install:
					click.echo(
						"Raven is not installed on this site. Either re-run with "
						"--install, or run manually:\n"
						"  bench get-app https://github.com/The-Commit-Company/raven\n"
						f"  bench --site {site} install-app raven"
					)
					raise SystemExit(1)
				bench_path = get_bench_path()
				frappe.destroy()  # release the DB connection before bench subcommands
				click.echo("Installing Raven (get-app → install-app → migrate)…")
				subprocess.run(
					["bench", "get-app", "https://github.com/The-Commit-Company/raven", "--skip-assets"],
					cwd=bench_path,
					check=False,  # already-cloned is fine
				)
				subprocess.run(["bench", "--site", site, "install-app", "raven"], cwd=bench_path, check=False)
				# migrate finishes the doctype sync even if install-app tripped
				# (observed on Postgres); it is idempotent and cheap.
				subprocess.run(["bench", "--site", site, "migrate"], cwd=bench_path, check=True)
				click.echo("Note: run `bench build --app raven` once for the chat UI assets.")
				frappe.init(site=site)
				frappe.connect()

			from frappe.friday_core.surfaces.bootstrap_raven import provision

			summary = provision(profile)
			click.echo(
				f"\n✓ Raven surface ready. Open Raven and DM the "
				f"'{summary['bot']}' bot, or @mention it in a channel."
			)
		finally:
			frappe.destroy()


@click.group("friday")
def friday():
	"""Friday agent framework — interactive and administrative commands."""
	pass


friday.add_command(chat)
friday.add_command(setup)
friday.add_command(setup_raven)

# Frappe's command loader reads this `commands` symbol from the module
# named in `hooks.py`. Each item is a click Command or Group; we expose
# the top-level `friday` group, and bench wires it under the `bench`
# CLI automatically.
commands = [friday]
