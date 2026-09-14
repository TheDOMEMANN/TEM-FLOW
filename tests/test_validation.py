from __future__ import annotations

import unittest

from temflow.validation import run_packaged_validation


class PackagedValidationTests(unittest.TestCase):
    def test_installed_package_validation_gates_pass(self):
        messages: list[str] = []
        self.assertEqual(run_packaged_validation(emit=messages.append), 0)
        self.assertTrue(messages[-1].startswith("PASS: all 8"))


if __name__ == "__main__":
    unittest.main()

