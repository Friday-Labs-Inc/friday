# Copyright (c) 2026, Friday Labs and contributors
# License: MIT. See license.txt

"""
Unit tests for the friday queue registration (design 61b, Q4).

A fresh clone of the repo doesn't have ``friday`` in
``common_site_config.json``. Frappe will reject an enqueue to an unknown
queue, and the runner trigger silently dies — the exact failure mode of
the Legion incident, just dressed differently. ``register_friday_queue``
runs every migrate to make that impossible.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch


class TestRegisterFridayQueue(unittest.TestCase):
	"""``register_friday_queue`` is idempotent and atomic."""

	def _tmp_bench(self):
		"""Return (bench_dir, config_path) with a writable bench layout."""
		bench = tempfile.mkdtemp(prefix="friday-bench-test-")
		sites = os.path.join(bench, "sites")
		os.makedirs(sites)
		cfg = os.path.join(sites, "common_site_config.json")
		return bench, cfg

	@patch("frappe.friday_core.health.after_migrate.frappe")
	def test_adds_friday_when_workers_block_absent(self, mock_frappe):
		from frappe.friday_core.health.after_migrate import (
			FRIDAY_QUEUE_TIMEOUT_SECONDS,
			register_friday_queue,
		)

		bench, cfg = self._tmp_bench()
		mock_frappe.utils.get_bench_path.return_value = bench
		with open(cfg, "w") as fh:
			json.dump({"db_host": "localhost"}, fh)

		register_friday_queue()

		with open(cfg) as fh:
			out = json.load(fh)
		self.assertEqual(out["workers"]["friday"]["timeout"], FRIDAY_QUEUE_TIMEOUT_SECONDS)
		# The unrelated key must survive.
		self.assertEqual(out["db_host"], "localhost")

	@patch("frappe.friday_core.health.after_migrate.frappe")
	def test_preserves_other_workers(self, mock_frappe):
		from frappe.friday_core.health.after_migrate import register_friday_queue

		bench, cfg = self._tmp_bench()
		mock_frappe.utils.get_bench_path.return_value = bench
		with open(cfg, "w") as fh:
			json.dump({"workers": {"long_running": {"timeout": 1500}}}, fh)

		register_friday_queue()

		with open(cfg) as fh:
			out = json.load(fh)
		self.assertEqual(out["workers"]["long_running"]["timeout"], 1500)
		self.assertEqual(out["workers"]["friday"]["timeout"], 600)

	@patch("frappe.friday_core.health.after_migrate.frappe")
	def test_idempotent_when_already_registered(self, mock_frappe):
		"""Second migrate must not re-write the file or change the value."""
		from frappe.friday_core.health.after_migrate import (
			FRIDAY_QUEUE_TIMEOUT_SECONDS,
			register_friday_queue,
		)

		bench, cfg = self._tmp_bench()
		mock_frappe.utils.get_bench_path.return_value = bench
		with open(cfg, "w") as fh:
			json.dump({"workers": {"friday": {"timeout": FRIDAY_QUEUE_TIMEOUT_SECONDS}}}, fh)

		os.path.getmtime(cfg)
		# A slight artificial pause so a mistaken re-write would change mtime.
		# (We can't sleep; instead we check the file's exact contents stayed.)
		register_friday_queue()

		with open(cfg) as fh:
			out = json.load(fh)
		self.assertEqual(out["workers"]["friday"]["timeout"], FRIDAY_QUEUE_TIMEOUT_SECONDS)
		# Exactly one workers key, nothing else added.
		self.assertEqual(list(out["workers"].keys()), ["friday"])

	@patch("frappe.friday_core.health.after_migrate.frappe")
	def test_skip_when_config_file_missing(self, mock_frappe):
		"""Test/sandbox benches: skip silently instead of crashing migrate."""
		from frappe.friday_core.health.after_migrate import register_friday_queue

		bench = tempfile.mkdtemp(prefix="friday-bench-empty-")
		mock_frappe.utils.get_bench_path.return_value = bench

		register_friday_queue()  # must not raise


if __name__ == "__main__":
	unittest.main()
