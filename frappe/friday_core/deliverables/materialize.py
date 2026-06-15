# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Artifact materialization (Design 73, Slice 5).

Turns an agent's task output — which otherwise lives only as text in
``Task.result`` — into real, downloadable files attached to the task:

  - ``deliverable-<task>.md``   — the source-of-truth Markdown
  - ``deliverable-<task>.pdf``  — a client-facing render (skipped gracefully
                                  if wkhtmltopdf isn't available)

When a project completes, ``assemble_project_package`` concatenates every
task's deliverable into one package attached to the Project.

Wiring (best-effort, enqueued after commit so rendering never blocks a save):
  - Task -> Completed     -> on_task_completed  -> materialize_task_deliverable
  - Project -> Completed  -> on_project_completed -> assemble_project_package

Idempotent: re-running a task replaces its prior ``deliverable-*`` files.
A task with no success content (a gate, an error, an empty result) produces
no artifact — we never fabricate a deliverable.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import escape_html

_logger = frappe.logger("friday.deliverables")

_PREFIX = "deliverable-"


# ---------------------------------------------------------------------------
# Hook entry points (enqueued after commit by the workflow / project hooks)
# ---------------------------------------------------------------------------


def on_task_completed(task_name: str) -> None:
	"""After-commit job: materialize a completed task's deliverable."""
	_guard(lambda: materialize_task_deliverable(task_name))


def on_project_completed(project_name: str) -> None:
	"""After-commit job: assemble the project's deliverable package."""
	_guard(lambda: assemble_project_package(project_name))


def on_project_doc_update(doc, method=None) -> None:
	"""doc_events hook: assemble the package when a project reaches Completed."""
	if doc.get("status") == "Completed":
		frappe.enqueue(
			"frappe.friday_core.deliverables.materialize.on_project_completed",
			queue="short",
			enqueue_after_commit=True,
			now=bool(frappe.flags.in_test),
			project_name=doc.name,
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def materialize_task_deliverable(task_name: str) -> "dict | None":
	"""Write a completed task's output as attached md + pdf files.

	Returns a dict of created File names, or None if the task has no
	materializable content (gate / error / empty).
	"""
	task = frappe.get_doc("Task", task_name)
	content = _extract_markdown(task.get("result"))
	if not content:
		return None

	title = task.get("title") or task.name
	slug = _slug(task_name)
	body = _wrap_markdown(title, task.get("project"), task_name, content)

	_clear_prior(task_name, "Task")
	created = {"md": _attach(f"{_PREFIX}{slug}.md", body.encode("utf-8"), "Task", task_name)}
	pdf = _render_pdf(title, content)
	if pdf:
		created["pdf"] = _attach(f"{_PREFIX}{slug}.pdf", pdf, "Task", task_name)
	return created


def assemble_project_package(project_name: str) -> "dict | None":
	"""Concatenate every task's deliverable into one package on the Project."""
	tasks = frappe.get_all(
		"Task", filters={"project": project_name}, fields=["name", "title"], order_by="creation asc"
	)
	sections = []
	for t in tasks:
		content = _extract_markdown(frappe.db.get_value("Task", t["name"], "result"))
		if content:
			sections.append(f"## {t['title'] or t['name']}\n\n{content}")
	if not sections:
		return None

	project_title = frappe.db.get_value("Project", project_name, "project_name") or project_name
	body = f"# {project_title} — Deliverable Package\n\n" + "\n\n---\n\n".join(sections)
	slug = _slug(project_name)

	_clear_prior(project_name, "Project")
	created = {"md": _attach(f"{_PREFIX}{slug}.md", body.encode("utf-8"), "Project", project_name)}
	pdf = _render_pdf(f"{project_title} — Deliverable Package", body)
	if pdf:
		created["pdf"] = _attach(f"{_PREFIX}{slug}.pdf", pdf, "Project", project_name)
	return created


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_markdown(raw) -> "str | None":
	"""Pull the deliverable Markdown out of a Task.result value.

	Agentic success: ``{"status": "success", "summary": "<markdown>"}``.
	A non-success envelope (error), a gate (empty), or blank -> None (we never
	fabricate a deliverable). A plain-text result is returned as-is.
	"""
	if not raw:
		return None
	if isinstance(raw, dict):
		data = raw
	else:
		try:
			data = json.loads(raw)
		except Exception:
			text = str(raw).strip()
			return text or None
	if isinstance(data, dict):
		if data.get("status") and data.get("status") != "success":
			return None
		summary = (data.get("summary") or "").strip()
		return summary or None
	return None


def _wrap_markdown(title: str, project: "str | None", task_name: str, content: str) -> str:
	meta = f"*Project: {project or '—'} · Task: {task_name}*"
	return f"# {title}\n\n{meta}\n\n---\n\n{content}\n"


def _render_pdf(title: str, markdown_content: str) -> "bytes | None":
	"""Render markdown to a PDF. Returns None if rendering is unavailable.

	Uses Frappe's wkhtmltopdf wrapper; if that binary isn't installed the
	deliverable still ships as Markdown (best-effort, never raises).
	"""
	try:
		from frappe.utils import md_to_html
		from frappe.utils.pdf import get_pdf

		html = (
			"<div style='font-family: sans-serif; line-height: 1.5; padding: 24px;'>"
			f"<h1>{escape_html(title)}</h1>"
			f"{md_to_html(markdown_content)}"
			"</div>"
		)
		return get_pdf(html)
	except Exception:
		_logger.warning("PDF render unavailable for %s — shipping Markdown only", title, exc_info=True)
		return None


def _attach(file_name: str, content: bytes, dt: str, dn: str) -> str:
	from frappe.utils.file_manager import save_file

	f = save_file(file_name, content, dt, dn, is_private=1)
	return f.name


def _clear_prior(dn: str, dt: str) -> None:
	"""Remove this doc's prior ``deliverable-*`` files so re-runs don't pile up.

	Only touches files we created (the ``deliverable-`` prefix) — never a
	user-uploaded attachment.
	"""
	prior = frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": dt,
			"attached_to_name": dn,
			"file_name": ["like", f"{_PREFIX}%"],
		},
		pluck="name",
	)
	for name in prior:
		try:
			frappe.delete_doc("File", name, force=True, ignore_permissions=True)
		except Exception:
			pass


def _slug(name: str) -> str:
	return "".join(c if c.isalnum() else "-" for c in str(name)).strip("-").lower()[:60]


def _guard(fn) -> None:
	"""Run a materialization side-effect best-effort: savepoint-guarded, never raises."""
	try:
		frappe.db.savepoint("friday_deliverable")
		fn()
	except Exception:
		try:
			frappe.db.rollback(save_point="friday_deliverable")
		except Exception:
			pass
		_logger.warning("deliverable materialization failed (swallowed)", exc_info=True)
