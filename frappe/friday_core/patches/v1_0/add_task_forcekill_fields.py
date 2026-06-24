# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""Add the 3 force_kill fields to existing Task rows (design 83b).

The fields are added by the model sync (they appear in task.json's
``fields`` list) which ``bench migrate`` runs as part of the
``[post_model_sync]`` phase. This patch is the explicit, auditable
companion that records the migration in the patch history.

The patch is **idempotent** and **side-effect free** at the row level —
the fields default to NULL and we do NOT write to existing rows
(``workflow_state`` stays whatever it was). The audit lives in the
schema sync that ran before this patch.

If a future patch needs to backfill anything, do it in a SEPARATE
patch; never conflate schema + data in the same step (the
``feedback_migrate-gate-before-pr`` rule).
"""

import frappe


def execute():
	# Schema-only migration. The fields exist after model sync; this
	# patch is a no-op marker so the rollout is searchable in the patch
	# log. Do NOT touch existing Task rows here.
	_ = frappe.db.sql("SELECT 1")
