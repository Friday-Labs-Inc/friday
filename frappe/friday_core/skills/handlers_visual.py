# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Visual-generation skills — `generate-image` via the MiniMax image model.

PLAIN ENGLISH
=============
This gives a visual agent (the Creative Director today; Graphic/Web designers
later) the ability to produce ACTUAL images, not just describe them. The agent
calls `generate-image` with a prompt; we call MiniMax's image API, download the
result, and save it as a Frappe File attached to the work-item (so it shows in
the brief's attachment sidebar and can be shared). The agent gets back the file
URL to reference in its reply.

HOW IT FITS
===========
- It is a generic, domain-agnostic skill — any visual agent can use it.
- It fetches its own credentials via the agent's LLM Provider (first-party
  handlers don't receive the dispatcher's credentials dict), and only works
  with a MiniMax provider (the image endpoint is MiniMax-specific).
- MiniMax image generation is synchronous (one POST, no polling) and returns
  URLs that expire in 24h — so we download immediately and persist the bytes.
- It never raises for an expected failure (bad prompt, no balance, policy
  block): it returns a dict whose `result` string explains what happened, so
  the agent can adapt — the dispatcher contract.
"""

from __future__ import annotations

import re

import frappe
import requests
from frappe.friday_core.agent_runner.dispatcher import register_skill_handler

GENERATE_IMAGE = "generate-image"

_IMAGE_PATH = "/v1/image_generation"
_DEFAULT_MODEL = "image-01"
_GEN_TIMEOUT = 120
_DOWNLOAD_TIMEOUT = 60
# MiniMax image hosts are region-coupled with the API key; pick by the
# provider's configured base_url (the China host carries the extra 'i').
_HOST_INTL = "https://api.minimax.io"
_HOST_CN = "https://api.minimaxi.com"


def generate_image(skill_name: str, parameters: dict) -> dict:
	"""Generate image(s) from a text prompt and save them as Frappe Files.

	Params: prompt (required), aspect_ratio (default "1:1"), n (1-9, default 1),
	attach_to_doctype + attach_to_name (optional; default = the current work
	item). Returns {"result": <human summary>, "image_urls": [<file urls>]}.
	"""
	params = parameters or {}
	prompt = (params.get("prompt") or "").strip()
	if not prompt:
		return {"result": "generate-image needs a non-empty 'prompt' describing the image."}
	aspect_ratio = params.get("aspect_ratio") or "1:1"
	try:
		count = max(1, min(9, int(params.get("n") or 1)))
	except (TypeError, ValueError):
		count = 1

	ctx = frappe.flags.get("friday_dispatch_context") or {}
	agent_profile = ctx.get("agent_profile")
	if not agent_profile:
		return {"result": "generate-image must be called by an agent (no profile in context)."}

	api_key, host, err = _minimax_credentials(agent_profile)
	if err:
		return {"result": err}

	try:
		resp = requests.post(
			host + _IMAGE_PATH,
			headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
			json={
				"model": _DEFAULT_MODEL,
				"prompt": prompt,
				"aspect_ratio": aspect_ratio,
				"n": count,
				"response_format": "url",
			},
			timeout=_GEN_TIMEOUT,
		)
		payload = resp.json()
	except Exception as exc:  # network / JSON / timeout — recoverable, report it
		return {"result": f"Image generation request failed: {type(exc).__name__}: {exc}"}

	base_resp = payload.get("base_resp") or {}
	status = base_resp.get("status_code")
	if status not in (0, None):
		return {
			"result": f"MiniMax image generation error {status}: {base_resp.get('status_msg') or ''}".strip()
		}
	urls = (payload.get("data") or {}).get("image_urls") or []
	if not urls:
		return {"result": "Image generation returned no images."}

	dt, dn = _attach_target(params, ctx)
	saved = _download_and_save(urls, prompt, dt, dn)
	if not saved:
		return {"result": "Images were generated but could not be downloaded (URLs may have expired)."}

	where = f" (attached to {dt} {dn})" if (dt and dn) else ""
	return {
		"result": f"Generated {len(saved)} image(s){where}: " + ", ".join(saved),
		"image_urls": saved,
	}


def _minimax_credentials(agent_profile: str):
	"""Return (api_key, host, error). Resolves the agent's LLM Provider; only
	MiniMax providers support image generation."""
	from frappe.friday_core.llm.provider import _get_api_key, _resolve_provider_row

	try:
		row = _resolve_provider_row(agent_profile)
	except Exception as exc:
		return None, None, f"Cannot resolve an LLM provider for image generation: {exc}"
	if not row:
		return None, None, "No active LLM provider is configured for image generation."
	if (row.get("provider_type") or "") != "minimax":
		return None, None, (
			"generate-image supports MiniMax providers only; this agent's provider is "
			f"{row.get('provider_type')!r}."
		)
	api_key = _get_api_key(row)
	if not api_key:
		return None, None, "The MiniMax provider has no API key configured."
	base_url = (row.get("base_url") or "").lower()
	host = _HOST_CN if "minimaxi" in base_url else _HOST_INTL
	return api_key, host, None


def _attach_target(params: dict, ctx: dict):
	"""Where to attach the saved files: an explicit target, else the current
	work-item (derived from the executing Task), else nowhere (unattached)."""
	dt = params.get("attach_to_doctype")
	dn = params.get("attach_to_name")
	if dt and dn:
		return dt, dn
	session = ctx.get("session_id") or ""
	if session.startswith("task::"):
		task_name = session.removeprefix("task::")
		wi = frappe.db.get_value(
			"Task", task_name, ["work_item_doctype", "work_item_name"], as_dict=True
		)
		if wi and wi.work_item_doctype and wi.work_item_name:
			return wi.work_item_doctype, wi.work_item_name
	return None, None


def _download_and_save(urls, prompt: str, dt, dn) -> list[str]:
	"""Download each image URL and persist the raw bytes as a Frappe File.
	Returns the saved file URLs. Bytes are passed through untouched."""
	from frappe.utils.file_manager import save_file

	slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")[:24] or "image"
	saved: list[str] = []
	for index, url in enumerate(urls):
		try:
			image_bytes = requests.get(url, timeout=_DOWNLOAD_TIMEOUT).content
		except Exception:
			break  # URL expired or unreachable — keep whatever already saved
		ext = _image_ext(image_bytes)  # MiniMax returns JPEG; sniff to be exact
		file_doc = save_file(f"{slug}-{index + 1}{ext}", image_bytes, dt or None, dn or None, is_private=0)
		saved.append(file_doc.file_url)
	return saved


def _image_ext(data: bytes) -> str:
	"""Pick a file extension from the image's magic bytes (don't trust the URL)."""
	if data[:3] == b"\xff\xd8\xff":
		return ".jpg"
	if data[:8] == b"\x89PNG\r\n\x1a\n":
		return ".png"
	if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
		return ".webp"
	return ".jpg"  # MiniMax image-01 default


register_skill_handler(GENERATE_IMAGE, generate_image)
