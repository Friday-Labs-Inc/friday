# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Bundled skill handlers — shipped inside the Docker runtime image.

Phase 1: all Phase 1 skills are Python modules registered here.
Authentication: none (the container's env vars contain scoped credentials).

Dependencies (installed in Docker image):
- requests==2.32.3  — HTTP calls to Frappe REST API

Each handler receives:
    parameters: dict  — the LLM-passed arguments

Each handler returns:
    dict — the skill's structured output (serialised into the result JSON)
"""

from collections.abc import Callable
from typing import TypeVar

D = TypeVar("D")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_HANDLERS: dict[str, Callable[[dict], dict]] = {}


def register(skill_name: str) -> Callable:
	"""
	Decorator to register a skill handler.

	Usage:
	    @register("create_note")
	    def handle_create_note(parameters: dict) -> dict:
	        ...
	"""

	def decorator(fn: Callable) -> Callable:
		_HANDLERS[skill_name] = fn
		return fn

	return decorator


def get(skill_name: str) -> Callable | None:
	return _HANDLERS.get(skill_name)


# ---------------------------------------------------------------------------
# Phase 1 skill handlers
# ---------------------------------------------------------------------------


@register("create_note")
def handle_create_note(parameters: dict) -> dict:
	"""
	Create a Note document via the Frappe REST API.

	The container uses FRIDAY_API_KEY (env) to authenticate
	against the Frappe REST API at FRIDAY_FRAPPE_BASE (env).
	"""
	import os

	import requests

	frappe_base = os.environ.get("FRIDAY_FRAPPE_BASE", "http://frappe:8000")
	api_key = os.environ.get("FRIDAY_API_KEY", "")

	title = parameters.get("title")
	content = parameters.get("content", "")

	if not title:
		raise ValueError("title is required")

	resp = requests.post(
		f"{frappe_base}/api/resource/Note",
		headers={
			"Authorization": f"token {api_key}",
			"Content-Type": "application/json",
		},
		json={
			"doctype": "Note",
			"title": title,
			"content": content,
		},
		timeout=30,
	)
	resp.raise_for_status()
	doc = resp.json().get("data", {})
	return {"name": doc.get("name"), "title": doc.get("title")}


__all__ = ["get", "register"]
