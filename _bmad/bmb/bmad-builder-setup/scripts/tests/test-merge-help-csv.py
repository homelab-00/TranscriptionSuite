#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Unit tests for merge-help-csv.py."""

import csv
import os
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path

# Import merge_help_csv module
from importlib.util import spec_from_file_location, module_from_spec

_spec = spec_from_file_location(
    "merge_help_csv",
    str(Path(__file__).parent.parent / "merge-help-csv.py"),
)
merge_help_csv_mod = module_from_spec(_spec)
_spec.loader.exec_module(merge_help_csv_mod)

extract_module_codes = merge_help_csv_mod.extract_module_codes
filter_rows = merge_help_csv_mod.filter_rows
read_csv_rows = merge_help_csv_mod.read_csv_rows
write_csv = merge_help_csv_mod.write_csv
cleanup_legacy_csvs = merge_help_csv_mod.cleanup_legacy_csvs
HEADER = merge_help_csv_mod.HEADER


SAMPLE_ROWS = [
    ["bmb", "", "bmad-bmb-module-init", "Install Module", "IM", "install", "", "Install BMad Builder.", "anytime", "", "", "false", "", "config", ""],
    ["bmb", "", "bmad-agent-builder", "Build Agent", "BA", "build-process", "", "Create an agent.", "anytime", "", "", "false", "output_folder", "agent skill", ""],
]


class TestExtractModuleCodes(unittest.TestCase):
    def test_extracts_codes(self):
        codes = extract_module_codes(SAMPLE_ROWS)
        self.assertEqual(codes, {"bmb"})

    def test_multiple_codes(self):
        rows = SAMPLE_ROWS + [
            ["cis", "", "cis-skill", "CIS Skill", "CS", "run", "", "A skill.", "anytime", "", "", "false", "", "", ""],
        ]
        codes = extract_module_codes(rows)
        self.assertEqual(codes, {"bmb", "cis"})

    def test_empty_rows(self):
        codes = extract_module_codes([])
        self.assertEqual(codes, set())


class TestFilterRows(unittest.TestCase):
    def test_removes_matching_rows(self):
        result = filter_rows(SAMPLE_ROWS, "bmb")
        self.assertEqual(len(result), 0)

    def test_preserves_non_matching_rows(self):
        mixed_rows = SAMPLE_ROWS + [
            ["cis", "", "cis-skill", "CIS Skill", "CS", "run", "", "A skill.", "anytime", "", "", "false", "", "", ""],
        ]
        result = filter_rows(mixed_rows, "bmb")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], "cis")

    def test_no_match_preserves_all(self):
        result = filter_rows(SAMPLE_ROWS, "xyz")
        self.assertEqual(len(result), 2)


class TestReadWriteCSV(unittest.TestCase):
    def test_nonexistent_file_returns_empty(self):
        header, rows = read_csv_rows("/nonexistent/path/file.csv")
        self.assertEqual(header, [])
        self.assertEqual(rows, [])

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.csv")
            write_csv(path, HEADER, SAMPLE_ROWS)

            header, rows = read_csv_rows(path)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0][0], "bmb")
            self.assertEqual(rows[0][2], "bmad-bmb-module-init")

    def test_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "sub", "dir", "test.csv")
            write_csv(path, HEADER, SAMPLE_ROWS)
            self.assertTrue(os.path.exists(path))


class TestEndToEnd(unittest.TestCase):
    def _write_source(self, tmpdir, rows):
        path = os.path.join(tmpdir, "source.csv")
        write_csv(path, HEADER, rows)
        return path

    def _write_target(self, tmpdir, rows):
        path = os.path.join(tmpdir, "target.csv")
        write_csv(path, HEADER, rows)
        return path

    def test_fresh_install_no_existing_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = self._write_source(tmpdir, SAMPLE_ROWS)
            target_path = os.path.join(tmpdir, "target.csv")

            # Target doesn't exist
            self.assertFalse(os.path.exists(target_path))

            # Simulate merge
            _, source_rows = read_csv_rows(source_path)
            source_codes = extract_module_codes(source_rows)
            write_csv(target_path, HEADER, source_rows)

            _, result_rows = read_csv_rows(target_path)
            self.assertEqual(len(result_rows), 2)

    def test_merge_into_existing_with_other_module(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            other_rows = [
                ["cis", "", "cis-skill", "CIS Skill", "CS", "run", "", "A skill.", "anytime", "", "", "false", "", "", ""],
            ]
            target_path = self._write_target(tmpdir, other_rows)
            source_path = self._write_source(tmpdir, SAMPLE_ROWS)

            # Read both
            _, target_rows = read_csv_rows(target_path)
            _, source_rows = read_csv_rows(source_path)
            source_codes = extract_module_codes(source_rows)

            # Anti-zombie filter + append
            filtered = target_rows
            for code in source_codes:
                filtered = filter_rows(filtered, code)
            merged = filtered + source_rows

            write_csv(target_path, HEADER, merged)

            _, result_rows = read_csv_rows(target_path)
            self.assertEqual(len(result_rows), 3)  # 1 cis + 2 bmb

    def test_anti_zombie_replaces_stale_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Existing target has old bmb entries + cis entry
            old_bmb_rows = [
                ["bmb", "", "old-skill", "Old Skill", "OS", "run", "", "Old.", "anytime", "", "", "false", "", "", ""],
                ["bmb", "", "another-old", "Another", "AO", "run", "", "Old too.", "anytime", "", "", "false", "", "", ""],
            ]
            cis_rows = [
                ["cis", "", "cis-skill", "CIS Skill", "CS", "run", "", "A skill.", "anytime", "", "", "false", "", "", ""],
            ]
            target_path = self._write_target(tmpdir, old_bmb_rows + cis_rows)
            source_path = self._write_source(tmpdir, SAMPLE_ROWS)

            # Read both
            _, target_rows = read_csv_rows(target_path)
            _, source_rows = read_csv_rows(source_path)
            source_codes = extract_module_codes(source_rows)

            # Anti-zombie filter + append
            filtered = target_rows
            for code in source_codes:
                filtered = filter_rows(filtered, code)
            merged = filtered + source_rows

            write_csv(target_path, HEADER, merged)

            _, result_rows = read_csv_rows(target_path)
            # Should have 1 cis + 2 new bmb = 3 (old bmb removed)
            self.assertEqual(len(result_rows), 3)
            module_codes = [r[0] for r in result_rows]
            self.assertEqual(module_codes.count("bmb"), 2)
            self.assertEqual(module_codes.count("cis"), 1)
            # Old skills should be gone
            skill_names = [r[2] for r in result_rows]
            self.assertNotIn("old-skill", skill_names)
            self.assertNotIn("another-old", skill_names)


class TestCleanupLegacyCsvs(unittest.TestCase):
    def test_deletes_module_and_core_csvs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_dir = os.path.join(tmpdir, "_bmad")
            for subdir in ("core", "bmb"):
                d = os.path.join(legacy_dir, subdir)
                os.makedirs(d)
                with open(os.path.join(d, "module-help.csv"), "w") as f:
                    f.write("header\nrow\n")

            deleted = cleanup_legacy_csvs(legacy_dir, "bmb")
            self.assertEqual(len(deleted), 2)
            self.assertFalse(os.path.exists(os.path.join(legacy_dir, "core", "module-help.csv")))
            self.assertFalse(os.path.exists(os.path.join(legacy_dir, "bmb", "module-help.csv")))
            # Directories still exist
            self.assertTrue(os.path.isdir(os.path.join(legacy_dir, "core")))
            self.assertTrue(os.path.isdir(os.path.join(legacy_dir, "bmb")))

    def test_leaves_other_module_csvs_alone(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_dir = os.path.join(tmpdir, "_bmad")
            for subdir in ("bmb", "cis"):
                d = os.path.join(legacy_dir, subdir)
                os.makedirs(d)
                with open(os.path.join(d, "module-help.csv"), "w") as f:
                    f.write("header\nrow\n")

            deleted = cleanup_legacy_csvs(legacy_dir, "bmb")
            self.assertEqual(len(deleted), 1)  # only bmb, not cis
            self.assertTrue(os.path.exists(os.path.join(legacy_dir, "cis", "module-help.csv")))

    def test_no_legacy_files_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            deleted = cleanup_legacy_csvs(tmpdir, "bmb")
            self.assertEqual(deleted, [])

    def test_handles_only_core_no_module(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_dir = os.path.join(tmpdir, "_bmad")
            core_dir = os.path.join(legacy_dir, "core")
            os.makedirs(core_dir)
            with open(os.path.join(core_dir, "module-help.csv"), "w") as f:
                f.write("header\nrow\n")

            deleted = cleanup_legacy_csvs(legacy_dir, "bmb")
            self.assertEqual(len(deleted), 1)
            self.assertFalse(os.path.exists(os.path.join(core_dir, "module-help.csv")))


if __name__ == "__main__":
    unittest.main()
