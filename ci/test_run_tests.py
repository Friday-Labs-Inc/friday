"""Unit test for the gate's parser. Run: python -m unittest ci/test_run_tests.py"""

import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("run_tests", Path(__file__).with_name("run_tests.py"))
rt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rt)


class TestParser(unittest.TestCase):
	def red(self, line):
		m = rt.RED_LINE.match(line)
		return rt.module_of(m.group(1)) if m else None

	def test_unittest_format(self):
		self.assertEqual(self.red("FAIL: test_b (a.tests.test_x.T.test_b)"), "a.tests.test_x")

	def test_frappe_padded_format(self):
		self.assertEqual(self.red(" ERROR  test_a (a.b.tests.test_y.TestY.test_a)"), "a.b.tests.test_y")

	def test_ansi_coloured_label(self):
		self.assertEqual(self.red("\x1b[31m FAIL \x1b[0m test_c (a.tests.test_z.T.test_c)"), "a.tests.test_z")

	def test_setupclass_error_maps_to_its_module(self):
		self.assertEqual(self.red("ERROR: setUpClass (a.tests.test_chat_flow.TestChat)"), "a.tests.test_chat_flow")

	def test_import_failure_is_not_a_known_module(self):
		self.assertEqual(self.red("ERROR: test_a (unittest.loader._FailedTest.test_a)"), "unittest.loader")

	def test_traceback_lines_do_not_match(self):
		self.assertIsNone(self.red("  File \"x.py\", line 3, in test_a (a.b.C.test_a)"))

	def test_ran_line(self):
		self.assertEqual(rt.RAN_LINE.match("Ran 1251 tests in 13.2s").group(1), "1251")
		self.assertEqual(rt.RAN_LINE.match("Ran 1 test in 0.1s").group(1), "1")


if __name__ == "__main__":
	unittest.main()
