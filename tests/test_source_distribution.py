"""Protect complete source archives and result-comparison failure detection."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class SourceDistributionTests(unittest.TestCase):
    def test_source_archive_has_theory_and_editing_controls(self):
        paths = {p.relative_to(ROOT).as_posix() for p in module('package_release').release_files()}
        for name in ['FORMULATION/STRUCTURAL_FORMULATION.md', 'STRUCTURAL_REVISION.json',
                     'EDITABLE_SOURCE_START_HERE.html', 'Launch editable source.cmd',
                     'Check editable source.cmd', 'desktop_launcher.py', 'desktop_server.py',
                     'tools/check.py', 'tools/source_cli.py', 'tools/source_workspace.ps1',
                     'analysis/structural/baseline/measurement_design.py']:
            self.assertIn(name, paths)
        self.assertFalse(any(p.startswith(('runtime/', 'user_data/', 'build/')) for p in paths))

    def test_comparison_detects_changed_mathematical_result(self):
        self.assertTrue(module('compare_saved_results').compare({'widths': [0., 40.]}, {'widths': [0., 41.]}))

    def test_comparison_permits_only_declared_timing_and_environment_metadata(self):
        c = module('compare_saved_results').compare
        self.assertFalse(c({'seconds': 1., 'width': 40., 'python': '3.12'}, {'seconds': 2., 'width': 40., 'python': '3.13'}))
        self.assertTrue(c({'width': 40.}, {'width': 40., 'extra_constraint': True}))

    def test_csv_and_json_guides_are_identical_in_installed_data(self):
        for name in ['STRUCTURAL_INPUT_GUIDE.md', 'AGGREGATE_RECORD_EXAMPLE.csv', 'AGGREGATE_RECORD_TEMPLATE.csv',
                     'INPUT_GUIDE_FOR_ORDINARY_USERS.md', 'TEMFLOW_DATED_RECORD_EXAMPLE.csv', 'TEMFLOW_DATED_RECORD_INPUT_TEMPLATE.csv']:
            self.assertEqual((ROOT / 'docs' / name).read_bytes(), (ROOT / 'src/temflow/data' / name).read_bytes(), name)


if __name__ == '__main__':
    unittest.main()
