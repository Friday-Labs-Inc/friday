# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""The RandomPack project-chat surface (surfaces/randompack_project_chat.py).

DB-free. Pins the propose-only contract locked with RandomPack: Friday PROPOSES a gate
action as a structured event, RP renders the confirm card, the HUMAN tap executes. The
validation matrix here is the defence-in-depth — a hallucinated or out-of-context
proposal must never reach RP's confirm card.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from frappe.friday_core.surfaces import randompack_project_chat as pc

_GATE1 = {
	"open_gate": {"which": "Gate 1", "directions": [{"label": "A"}, {"label": "B"}, {"label": "C"}]}
}
_GATE2 = {"open_gate": {"which": "Gate 2", "directions": None}}
_NO_GATE = {"open_gate": {"which": None}}


def _act(**kw):
	base = {"kind": "gate_decision", "confidence": 0.9}
	base.update(kw)
	return base


class TestValidateAction(unittest.TestCase):
	"""The RP contract's validation rules, enforced exactly."""

	# -- the happy paths -----------------------------------------------------

	def test_gate1_direction_selected_valid(self):
		out = pc.validate_action(_act(gate="Gate 1", decision="Direction Selected", direction="B"), _GATE1)
		self.assertEqual(out["type"], "action")
		self.assertEqual(out["gate"], "Gate 1")
		self.assertEqual(out["decision"], "Direction Selected")
		self.assertEqual(out["direction"], "B")

	def test_gate2_approved_valid(self):
		out = pc.validate_action(_act(gate="Gate 2", decision="Approved"), _GATE2)
		self.assertEqual(out["decision"], "Approved")
		self.assertNotIn("direction", out)

	def test_gate2_refinement_with_note(self):
		out = pc.validate_action(
			_act(gate="Gate 2", decision="Refinement Requested", note="logo too loud"), _GATE2
		)
		self.assertEqual(out["decision"], "Refinement Requested")
		self.assertEqual(out["note"], "logo too loud")

	# -- the drops (defence-in-depth) ----------------------------------------

	def test_no_open_gate_drops_everything(self):
		self.assertIsNone(pc.validate_action(_act(gate="Gate 1", decision="Direction Selected", direction="A"), _NO_GATE))

	def test_wrong_gate_is_dropped(self):
		# The hallucination killer: a Gate 2 action while Gate 1 is open.
		self.assertIsNone(pc.validate_action(_act(gate="Gate 2", decision="Approved"), _GATE1))

	def test_gate1_requires_a_direction(self):
		self.assertIsNone(pc.validate_action(_act(gate="Gate 1", decision="Direction Selected"), _GATE1))

	def test_gate1_direction_must_be_an_offered_label(self):
		self.assertIsNone(
			pc.validate_action(_act(gate="Gate 1", decision="Direction Selected", direction="D"), _GATE1)
		)

	def test_gate1_rejects_gate2_decisions(self):
		self.assertIsNone(pc.validate_action(_act(gate="Gate 1", decision="Approved"), _GATE1))

	def test_gate2_never_carries_a_direction(self):
		out = pc.validate_action(_act(gate="Gate 2", decision="Approved", direction="B"), _GATE2)
		self.assertIsNotNone(out)
		self.assertNotIn("direction", out)  # stripped, not passed through

	def test_unknown_kind_is_dropped(self):
		self.assertIsNone(pc.validate_action(_act(kind="mystery", gate="Gate 2", decision="Approved"), _GATE2))

	def test_garbage_shapes_never_raise(self):
		for bad in (None, "x", 42, [], {}):
			self.assertIsNone(pc.validate_action(bad, _GATE2))
		self.assertIsNone(pc.validate_action(_act(gate="Gate 2", decision="Approved"), None))

	def test_confidence_clamped(self):
		out = pc.validate_action(_act(gate="Gate 2", decision="Approved", confidence=7), _GATE2)
		self.assertEqual(out["confidence"], 1.0)
		out = pc.validate_action(_act(gate="Gate 2", decision="Approved", confidence="nope"), _GATE2)
		self.assertEqual(out["confidence"], 0.0)


class TestParseAction(unittest.TestCase):
	def test_strict_json(self):
		out = pc._parse_action('{"action": {"kind": "gate_decision", "gate": "Gate 2", "decision": "Approved"}}')
		self.assertEqual(out["decision"], "Approved")

	def test_null_action_and_garbage(self):
		self.assertIsNone(pc._parse_action('{"action": null}'))
		self.assertIsNone(pc._parse_action("not json"))
		self.assertIsNone(pc._parse_action(""))

	def test_fenced_json(self):
		out = pc._parse_action('```json\n{"action": {"kind": "gate_decision"}}\n```')
		self.assertEqual(out["kind"], "gate_decision")


class TestAdvisorPrompt(unittest.TestCase):
	def test_renders_project_state(self):
		p = pc.build_system_prompt(
			{
				"project_title": "Halcyon — Essentials",
				"company": "Halcyon",
				"day": 6,
				"total_days": 10,
				"phase": "Buildout",
				"open_gate": {"which": "Gate 2"},
				"deliverables": [{"name": "03 — Brand System (draft).pdf"}],
				"decisions_so_far": [{"gate": "Gate 1", "decision": "Direction Selected", "direction": "B"}],
				"brief": {"personality": ["Bold", "Warm"], "differentiator": "roast to order"},
			}
		)
		self.assertIn("Halcyon — Essentials", p)
		self.assertIn("Day 6 of 10", p)
		self.assertIn("Buildout", p)
		self.assertIn("OPEN GATE: Gate 2", p)
		self.assertIn("Brand System", p)
		self.assertIn("Gate 1: Direction Selected (B)", p)
		self.assertIn("Bold, Warm", p)

	def test_gate1_lists_the_direction_labels(self):
		p = pc.build_system_prompt(_GATE1)
		self.assertIn("OPEN GATE: Gate 1", p)
		self.assertIn("A, B, C", p)

	def test_never_invent_directions_rule_is_always_present(self):
		for ctx in (None, _GATE1, _GATE2, _NO_GATE):
			p = pc.build_system_prompt(ctx)
			self.assertIn("NEVER invent", p)

	def test_propose_only_authority_is_always_present(self):
		for ctx in (None, _GATE1, _GATE2):
			p = pc.build_system_prompt(ctx)
			self.assertIn("AUTHORITY: you have NONE", p)

	def test_anti_refusal_is_always_present(self):
		self.assertIn("NEVER refuse", pc.build_system_prompt(_GATE2))

	def test_no_open_gate_says_discuss_only(self):
		self.assertIn("No gate is open", pc.build_system_prompt(_NO_GATE))


class TestActionPass(unittest.TestCase):
	def test_no_open_gate_skips_the_model_call(self):
		provider = MagicMock()
		events, usage = pc._make_action_pass(_NO_GATE)([], "msg", "reply", provider)
		provider.chat.assert_not_called()
		self.assertEqual((events, usage), ([], {}))

	def test_valid_decision_emits_one_action_with_usage(self):
		provider = MagicMock()
		provider.chat.return_value = {
			"content": '{"action": {"kind": "gate_decision", "gate": "Gate 1", '
			'"decision": "Direction Selected", "direction": "B", "confidence": 0.92}}',
			"usage": {"total_tokens": 40},
		}
		events, usage = pc._make_action_pass(_GATE1)([], "lock direction B", "great choice", provider)
		self.assertEqual(len(events), 1)
		self.assertEqual(events[0]["type"], "action")
		self.assertEqual(events[0]["direction"], "B")
		self.assertEqual(usage, {"total_tokens": 40})

	def test_invalid_proposal_is_dropped_but_usage_kept(self):
		provider = MagicMock()
		provider.chat.return_value = {
			"content": '{"action": {"kind": "gate_decision", "gate": "Gate 2", "decision": "Approved"}}',
			"usage": {"total_tokens": 22},
		}
		events, usage = pc._make_action_pass(_GATE1)([], "hmm", "reply", provider)
		self.assertEqual(events, [])  # wrong-gate proposal dropped
		self.assertEqual(usage, {"total_tokens": 22})  # the call still cost tokens — audited

	def test_provider_failure_yields_nothing(self):
		provider = MagicMock()
		provider.chat.side_effect = RuntimeError("model down")
		events, usage = pc._make_action_pass(_GATE2)([], "approve", "reply", provider)
		self.assertEqual((events, usage), ([], {}))


class TestEndpointIsRoutable(unittest.TestCase):
	"""The #161 lesson: a whitelisted endpoint must be registered with Frappe routing."""

	def test_chat_send_is_whitelisted_guest_post(self):
		import frappe

		self.assertIn(pc.chat_send, frappe.whitelisted)
		self.assertIn(pc.chat_send, frappe.guest_methods)
		self.assertIn("POST", frappe.allowed_http_methods_for_whitelisted_func[pc.chat_send])


if __name__ == "__main__":
	unittest.main()
