# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for LLM usage + cost recording (llm/usage.py).

Mock-based — no DB. Pins: Hermes' cost formula (tokens/1M × per-million rate,
input and output priced separately), the no-rates → no-estimate rule, the
LLM Usage Log insert shape, the never-raises guarantee, and the runner wiring
(one record_usage call per provider.chat call).
"""

import unittest
from unittest.mock import MagicMock, patch

from frappe.friday_core.llm.usage import estimate_cost, record_usage

_U = "frappe.friday_core.llm.usage"


def _provider(name="minimax", input_rate=None, output_rate=None):
	p = MagicMock()
	p.PROVIDER_NAME = name
	p.input_cost_per_million = input_rate
	p.output_cost_per_million = output_rate
	return p


class TestEstimateCost(unittest.TestCase):
	def test_hermes_formula_input_plus_output(self):
		# 1M input @ $5/M + 0.5M output @ $25/M = 5 + 12.5 = 17.5
		self.assertAlmostEqual(estimate_cost(1_000_000, 500_000, 5.0, 25.0), 17.5)

	def test_no_rates_means_none_not_zero(self):
		# "Not configured" must stay distinct from "free".
		self.assertIsNone(estimate_cost(1000, 1000, None, None))
		self.assertIsNone(estimate_cost(1000, 1000, 0, 0))

	def test_one_sided_rate_prices_that_side_only(self):
		self.assertAlmostEqual(estimate_cost(1_000_000, 1_000_000, 5.0, None), 5.0)
		self.assertAlmostEqual(estimate_cost(1_000_000, 1_000_000, None, 25.0), 25.0)

	def test_zero_tokens_with_rates_is_zero_cost(self):
		self.assertEqual(estimate_cost(0, 0, 5.0, 25.0), 0.0)


class TestRecordUsage(unittest.TestCase):
	@patch(f"{_U}.frappe")
	def test_inserts_row_with_tokens_and_cost(self, mock_frappe):
		doc = MagicMock()
		doc.name = "ULOG-1"
		mock_frappe.get_doc.return_value = doc

		result = record_usage(
			profile_name="Friday",
			session_id="sess-1",
			provider=_provider(input_rate=5.0, output_rate=25.0),
			model="MiniMax-M2",
			usage={"prompt_tokens": 1_000_000, "completion_tokens": 500_000, "total_tokens": 1_500_000},
		)

		self.assertEqual(result, "ULOG-1")
		payload = mock_frappe.get_doc.call_args[0][0]
		self.assertEqual(payload["doctype"], "LLM Usage Log")
		self.assertEqual(payload["session_id"], "sess-1")
		self.assertEqual(payload["agent_profile"], "Friday")
		self.assertEqual(payload["provider"], "minimax")
		self.assertEqual(payload["model"], "MiniMax-M2")
		self.assertEqual(payload["prompt_tokens"], 1_000_000)
		self.assertEqual(payload["completion_tokens"], 500_000)
		self.assertEqual(payload["total_tokens"], 1_500_000)
		self.assertAlmostEqual(payload["estimated_cost"], 17.5)
		doc.insert.assert_called_once_with(ignore_permissions=True)

	@patch(f"{_U}.frappe")
	def test_total_derived_when_provider_omits_it(self, mock_frappe):
		doc = MagicMock()
		mock_frappe.get_doc.return_value = doc
		record_usage(
			profile_name="P",
			session_id="s",
			provider=_provider(),
			model="m",
			usage={"prompt_tokens": 10, "completion_tokens": 5},
		)
		self.assertEqual(mock_frappe.get_doc.call_args[0][0]["total_tokens"], 15)

	@patch(f"{_U}.frappe")
	def test_no_rates_records_tokens_with_null_cost(self, mock_frappe):
		doc = MagicMock()
		mock_frappe.get_doc.return_value = doc
		record_usage(
			profile_name="P",
			session_id="s",
			provider=_provider(),
			model="m",
			usage={"prompt_tokens": 10, "completion_tokens": 5},
		)
		self.assertIsNone(mock_frappe.get_doc.call_args[0][0]["estimated_cost"])

	@patch(f"{_U}.frappe")
	def test_never_raises_even_when_insert_and_logging_fail(self, mock_frappe):
		mock_frappe.get_doc.side_effect = RuntimeError("table missing")
		mock_frappe.logger.side_effect = RuntimeError("logging broken too")
		result = record_usage(
			profile_name="P",
			session_id="s",
			provider=_provider(),
			model="m",
			usage={},
		)
		self.assertIsNone(result)  # swallowed — the turn must continue


class TestRunnerWiring(unittest.TestCase):
	def test_runner_records_usage_once_per_chat_call(self):
		from frappe.friday_core.tests.test_react_loop import _provider as _chat_provider
		from frappe.friday_core.tests.test_react_loop import _resp, _run

		prov = _chat_provider(_resp(content="Hello!"))
		prov.get_default_model.return_value = "MiniMax-M2"
		with patch("frappe.friday_core.agent_runner.runner.record_usage") as mock_record:
			result, _, _ = _run(prov, dispatch_results=[])
		self.assertEqual(result, "Hello!")
		mock_record.assert_called_once()
		kwargs = mock_record.call_args.kwargs
		self.assertEqual(kwargs["profile_name"], "P")
		self.assertEqual(kwargs["session_id"], "S")
		self.assertEqual(kwargs["usage"], {"total_tokens": 7})


if __name__ == "__main__":
	unittest.main()
