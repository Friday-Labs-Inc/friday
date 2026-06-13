# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Friday sandbox module.

Every skill execution runs inside an isolated Docker container with:
- Non-root user (UID 65532)
- Read-only rootfs, tmpfs scratch at /tmp
- CPU + memory cgroup limits
- Network: friday-execution-net (bridge, Frappe API host only)
- Scoped credentials via env var

Phase 1: cold-spawn per execution.
Phase 1.5: warm container pool.
"""

from frappe.friday_core.sandbox.runner import SandboxResult, execute

__all__ = ["SandboxResult", "execute"]
