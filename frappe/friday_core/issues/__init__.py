# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
The agent issue tracker — the "system watching itself" half of the generic
Issue tracker (doc 53).

Callers (e.g. `tasks/runner.py`) use:

    from frappe.friday_core import issues
    issues.raise_failure_issue(task_name, error_type="SandboxTimeout")

The Issue DocType itself is generic (humans file tickets too, `source =
"Human-raised"`); this package only holds the *agent-raised* automation.
"""

from frappe.friday_core.issues.raise_issue import (
	TASK_DOCTYPE,
	raise_dependency_wait_issue,
	raise_failure_issue,
	unfinished_dependencies,
)

__all__ = [
	"TASK_DOCTYPE",
	"raise_dependency_wait_issue",
	"raise_failure_issue",
	"unfinished_dependencies",
]
