# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

"""
Typed signals raised out of the agent runner.

`TurnInterrupted` is the one that matters for Design 85: when an operator `/stop`s
a turn, `run_turn` RAISES this instead of returning a sentinel string. That makes
interruption impossible to confuse with a real reply — the two call paths handle
it explicitly:

  - the chat pipeline (`gateway/service`) writes a clean "(interrupted by
    operator)" outbound, and
  - the Task path (`tasks/runner`) marks a delegated child Cancelled, never
    Completed.

Before Design 85 the runner returned the string and the Task path treated any
return as success — so a cascaded interrupt would have falsely marked delegated
tasks done. The typed exception closes that hole.
"""

from __future__ import annotations


class TurnInterrupted(Exception):
	"""Raised by `run_turn` when an operator interrupt was honored mid-turn.

	The message is the operator-facing reply (e.g. "(interrupted by operator)").
	"""
