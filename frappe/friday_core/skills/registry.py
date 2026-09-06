# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Skill handler registry — the kernel seam apps use to contribute skills.

PLAIN ENGLISH
=============
A skill handler is the Python function that runs when the agent calls a skill.
The kernel keeps ONE registry (``_SKILL_HANDLERS``); any app adds handlers by
listing the modules that register them in its ``hooks.py``::

    friday_skill_handlers = ["design_studio.skills.handlers_brand"]

Those modules are imported lazily, once per site, the first time a handler is
looked up (``get_skill_handler``). Importing a module runs its
``register_skill_handler(...)`` calls. Nothing here grants a skill — the Skill
row, the permission matrix and the approval gate still decide what may run;
the registry only says which code implements a skill name.

This module has no imports from the rest of friday_core on purpose: handler
modules import ``register_skill_handler`` from here (or via the dispatcher's
re-export) without creating an import cycle.
"""

from __future__ import annotations

import importlib

import frappe

HOOK = "friday_skill_handlers"

# skill_name -> handler(skill_name, parameters) -> {"result": str, ...}
_SKILL_HANDLERS: dict[str, callable] = {}

# Sites whose hook-declared handler modules have been imported in this process.
_loaded_sites: set[str] = set()


def register_skill_handler(skill_name: str, handler: callable) -> None:
	"""Register a skill handler. Raises ValueError if a handler already exists for this skill.

	Usage:
	    register_skill_handler("create_note", some_function)
	"""
	if skill_name in _SKILL_HANDLERS:
		raise ValueError(
			f"A handler for {skill_name!r} is already registered: {_SKILL_HANDLERS[skill_name]!r}"
		)
	_SKILL_HANDLERS[skill_name] = handler


def load_handler_modules() -> None:
	"""Import every module declared in the ``friday_skill_handlers`` hook (once per site).

	A module that fails to import is logged and skipped — one broken app must not
	take every other skill down with it. Safe to call repeatedly.
	"""
	site = getattr(frappe.local, "site", None)
	if not site or site in _loaded_sites:
		return
	for path in frappe.get_hooks(HOOK) or []:
		try:
			importlib.import_module(path)
		except Exception:
			frappe.log_error(title=f"friday skill handler module failed to import: {path}")
	_loaded_sites.add(site)


def get_skill_handler(skill_name: str):
	"""The handler registered for ``skill_name``, or None. Loads hook modules first."""
	load_handler_modules()
	return _SKILL_HANDLERS.get(skill_name)
