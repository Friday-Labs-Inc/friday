# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
The Studio Workspace endpoints (design 96, Pillar 3 — "The Bench").

PLAIN ENGLISH
=============
The human Creative Director's work queue used to be invisible: the only signal
was a Raven war-room post, and acting meant finding the right Brand Brief form
and knowing which workflow button to press. These three endpoints power the
`/app/studio` Desk page that fixes that:

  - ``studio_snapshot``  — every Brand Brief waiting on the CD (the two CD_ROLE
                            states from the design-95 machine), as queue cards:
                            brand name, state, days waiting, package/round counts.
  - ``package_preview``  — the thing to review: every production-package version
                            on the brief's project rendered md→html, newest first,
                            so refine rounds can be compared side by side.
  - ``studio_action``    — the one-click verbs: Creative Ready / Approve
                            Production / Request Refinement. Refinement REQUIRES
                            notes; they are written to the project as
                            ``cd-refinement-notes-r<N>.md`` BEFORE the transition
                            fires, so the production agent finds them the moment
                            its phase starts. The notes are also the design-95
                            apprenticeship training signal.

Transitions run through ``frappe.model.workflow.apply_workflow`` as the
signed-in user, so the workflow's own role gate (`Brand Creative Director`)
is the enforcement — these endpoints add no parallel permission scheme.

Compare with Hermes: no equivalent — Hermes has no human-in-the-loop craft
station; its dashboard is operator telemetry. The Bench is a reviewer surface,
which is exactly the design-95 divergence (human CD creates, AI produces).
"""

from __future__ import annotations

import frappe
from frappe import _

# The two states owned by the human CD (domains/randompack_brand.py STATES).
CD_STATES = ("CD Creative", "CD Internal Gate")

# Which workflow actions the Bench offers per state. Kept in lockstep with
# domains/randompack_brand.py TRANSITIONS — the workflow itself re-validates,
# so a drift here fails loudly rather than silently allowing anything.
STATE_ACTIONS: dict[str, tuple[str, ...]] = {
	"CD Creative": ("Creative Ready",),
	"CD Internal Gate": ("Approve Production", "Request Refinement"),
}

_PACKAGE_PATTERN = "production-package%"
_NOTES_PATTERN = "cd-refinement-notes-r%"
_PREVIEW_LIMIT = 5


@frappe.whitelist()
def studio_snapshot() -> dict:
	"""The Bench queue: every Brand Brief waiting on the human CD.

	Fail-loud envelope (the console_snapshot contract): an error returns an
	``error`` string, never a silent empty queue.
	"""
	_require_brief_read()
	try:
		return {"generated_at": frappe.utils.now(), "queue": _queue()}
	except Exception as exc:
		frappe.log_error(title="friday.studio studio_snapshot failed")
		return {
			"generated_at": frappe.utils.now(),
			"error": f"{type(exc).__name__}: {str(exc)[:300]}",
			"queue": [],
		}


@frappe.whitelist()
def package_preview(brief: str) -> dict:
	"""Every production-package version on the brief's project, rendered
	md→html, newest first — the CD's review material, refine rounds side
	by side."""
	_require_brief_read()
	from frappe.utils import md_to_html

	project = frappe.db.get_value("Brand Brief", brief, "project")
	if not project:
		return {"brief": brief, "versions": []}

	files = frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": "Project",
			"attached_to_name": project,
			"file_name": ["like", _PACKAGE_PATTERN],
		},
		fields=["name", "file_name", "creation"],
		order_by="creation desc",
		limit=_PREVIEW_LIMIT,
	)
	versions = []
	for row in files:
		try:
			content = frappe.get_doc("File", row["name"]).get_content()
			if isinstance(content, bytes):
				content = content.decode("utf-8", errors="replace")
			html = str(md_to_html(content))
		except Exception:
			html = f"<p><em>{_('Could not render')} {frappe.utils.escape_html(row['file_name'])}</em></p>"
		versions.append({"file_name": row["file_name"], "creation": str(row["creation"]), "html": html})
	return {"brief": brief, "versions": versions}


@frappe.whitelist()
def studio_action(brief: str, action: str, notes: str | None = None) -> dict:
	"""Fire a Bench action on a Brand Brief as the signed-in CD.

	Request Refinement requires notes: they are saved to the project as
	``cd-refinement-notes-r<N>.md`` BEFORE the workflow transition, so the
	production phase (which starts on the transition) can read the
	correction. The workflow's role gate is the permission check.
	"""
	doc = frappe.get_doc("Brand Brief", brief)
	allowed = STATE_ACTIONS.get(doc.workflow_state) or ()
	if action not in allowed:
		frappe.throw(_("'{0}' is not a Bench action for state '{1}'.").format(action, doc.workflow_state))

	notes_file = None
	if action == "Request Refinement":
		if not (notes or "").strip():
			frappe.throw(
				_(
					"Refinement needs notes — they are the correction the "
					"production agent will apply (and learn from)."
				)
			)
		notes_file = _save_refinement_notes(doc, notes)

	from frappe.model.workflow import apply_workflow

	updated = apply_workflow(doc, action)
	return {
		"brief": brief,
		"new_state": updated.workflow_state,
		"notes_file": notes_file,
	}


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _require_brief_read() -> None:
	"""The read endpoints expose internal production content; the same read
	permission that guards the Brand Brief form guards them."""
	if not frappe.has_permission("Brand Brief", "read"):
		frappe.throw(_("Not permitted to read Brand Briefs."), frappe.PermissionError)


def _queue() -> list[dict]:
	briefs = frappe.get_all(
		"Brand Brief",
		filters={"workflow_state": ["in", list(CD_STATES)]},
		fields=["name", "business_name", "workflow_state", "modified", "project"],
		order_by="modified asc",  # longest-waiting first
	)
	for row in briefs:
		row["days_waiting"] = frappe.utils.date_diff(
			frappe.utils.nowdate(), frappe.utils.getdate(row["modified"])
		)
		row["package_count"] = _project_file_count(row.get("project"), _PACKAGE_PATTERN)
		row["refine_round"] = _project_file_count(row.get("project"), _NOTES_PATTERN)
		row["actions"] = list(STATE_ACTIONS.get(row["workflow_state"]) or ())
	return briefs


def _project_file_count(project: str | None, pattern: str) -> int:
	if not project:
		return 0
	return frappe.db.count(
		"File",
		{
			"attached_to_doctype": "Project",
			"attached_to_name": project,
			"file_name": ["like", pattern],
		},
	)


def _save_refinement_notes(doc, notes: str) -> str:
	"""Write the CD's correction to the project as the next-round notes file.

	Private and unflagged (is_customer_facing stays 0), so the slice-2 leak
	guard keeps it internal — exactly the file the E2E created by hand.
	Returns the human file name (e.g. ``cd-refinement-notes-r2.md``).
	"""
	if not doc.project:
		frappe.throw(_("Brand Brief {0} has no linked project to attach notes to.").format(doc.name))

	round_no = _project_file_count(doc.project, _NOTES_PATTERN) + 1
	file_name = f"cd-refinement-notes-r{round_no}.md"
	content = f"# CD Refinement Notes — Round {round_no}\n\n{notes.strip()}\n"

	from frappe.utils.file_manager import save_file

	save_file(file_name, content.encode("utf-8"), "Project", doc.project, is_private=1)
	return file_name
