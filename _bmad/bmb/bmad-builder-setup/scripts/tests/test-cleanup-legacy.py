#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Unit tests for cleanup-legacy.py."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add parent directory to path so we can import the module
sys.path.insert(0, str(Path(__file__).parent.parent))

from importlib.util import spec_from_file_location, module_from_spec

# Import cleanup_legacy module
_spec = spec_from_file_location(
    "cleanup_legacy",
    str(Path(__file__).parent.parent / "cleanup-legacy.py"),
)
cleanup_legacy_mod = module_from_spec(_spec)
_spec.loader.exec_module(cleanup_legacy_mod)

find_skill_dirs = cleanup_legacy_mod.find_skill_dirs
verify_skills_installed = cleanup_legacy_mod.verify_skills_installed
count_files = cleanup_legacy_mod.count_files
cleanup_directories = cleanup_legacy_mod.cleanup_directories


def _make_skill_dir(base, *path_parts):
    """Create a skill directory with a SKILL.md file."""
    skill_dir = os.path.join(base, *path_parts)
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: test-skill\n---\n# Test\n")
    return skill_dir


def _make_file(base, *path_parts, content="placeholder"):
    """Create a file at the given path."""
    file_path = os.path.join(base, *path_parts)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w") as f:
        f.write(content)
    return file_path


class TestFindSkillDirs(unittest.TestCase):
    def test_finds_dirs_with_skill_md(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _make_skill_dir(tmpdir, "skills", "bmad-agent-builder")
            _make_skill_dir(tmpdir, "skills", "bmad-workflow-builder")
            result = find_skill_dirs(tmpdir)
            self.assertEqual(result, ["bmad-agent-builder", "bmad-workflow-builder"])

    def test_ignores_dirs_without_skill_md(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _make_skill_dir(tmpdir, "skills", "real-skill")
            os.makedirs(os.path.join(tmpdir, "skills", "not-a-skill"))
            _make_file(tmpdir, "skills", "not-a-skill", "README.md")
            result = find_skill_dirs(tmpdir)
            self.assertEqual(result, ["real-skill"])

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = find_skill_dirs(tmpdir)
            self.assertEqual(result, [])

    def test_nonexistent_directory(self):
        result = find_skill_dirs("/nonexistent/path")
        self.assertEqual(result, [])

    def test_finds_nested_skills_in_phase_subdirs(self):
        """Skills nested in phase directories like bmm/1-analysis/bmad-agent-analyst/."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _make_skill_dir(tmpdir, "1-analysis", "bmad-agent-analyst")
            _make_skill_dir(tmpdir, "2-plan", "bmad-agent-pm")
            _make_skill_dir(tmpdir, "4-impl", "bmad-agent-dev")
            result = find_skill_dirs(tmpdir)
            self.assertEqual(
                result, ["bmad-agent-analyst", "bmad-agent-dev", "bmad-agent-pm"]
            )

    def test_deduplicates_skill_names(self):
        """If the same skill name appears in multiple locations, only listed once."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _make_skill_dir(tmpdir, "a", "my-skill")
            _make_skill_dir(tmpdir, "b", "my-skill")
            result = find_skill_dirs(tmpdir)
            self.assertEqual(result, ["my-skill"])


class TestVerifySkillsInstalled(unittest.TestCase):
    def test_all_skills_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bmad_dir = os.path.join(tmpdir, "_bmad")
            skills_dir = os.path.join(tmpdir, "skills")

            # Legacy: bmb has two skills
            _make_skill_dir(bmad_dir, "bmb", "skills", "skill-a")
            _make_skill_dir(bmad_dir, "bmb", "skills", "skill-b")

            # Installed: both exist
            os.makedirs(os.path.join(skills_dir, "skill-a"))
            os.makedirs(os.path.join(skills_dir, "skill-b"))

            result = verify_skills_installed(bmad_dir, ["bmb"], skills_dir)
            self.assertEqual(result, ["skill-a", "skill-b"])

    def test_missing_skill_exits_1(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bmad_dir = os.path.join(tmpdir, "_bmad")
            skills_dir = os.path.join(tmpdir, "skills")

            _make_skill_dir(bmad_dir, "bmb", "skills", "skill-a")
            _make_skill_dir(bmad_dir, "bmb", "skills", "skill-missing")

            # Only skill-a installed
            os.makedirs(os.path.join(skills_dir, "skill-a"))

            with self.assertRaises(SystemExit) as ctx:
                verify_skills_installed(bmad_dir, ["bmb"], skills_dir)
            self.assertEqual(ctx.exception.code, 1)

    def test_empty_legacy_dir_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bmad_dir = os.path.join(tmpdir, "_bmad")
            skills_dir = os.path.join(tmpdir, "skills")
            os.makedirs(bmad_dir)
            os.makedirs(skills_dir)

            result = verify_skills_installed(bmad_dir, ["bmb"], skills_dir)
            self.assertEqual(result, [])

    def test_nonexistent_legacy_dir_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bmad_dir = os.path.join(tmpdir, "_bmad")
            skills_dir = os.path.join(tmpdir, "skills")
            os.makedirs(skills_dir)
            # bmad_dir doesn't exist — should not error

            result = verify_skills_installed(bmad_dir, ["bmb"], skills_dir)
            self.assertEqual(result, [])

    def test_dir_without_skills_skipped(self):
        """Directories like _config/ that have no SKILL.md are not verified."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bmad_dir = os.path.join(tmpdir, "_bmad")
            skills_dir = os.path.join(tmpdir, "skills")

            # _config has files but no SKILL.md
            _make_file(bmad_dir, "_config", "manifest.yaml", content="version: 1")
            _make_file(bmad_dir, "_config", "help.csv", content="a,b,c")
            os.makedirs(skills_dir)

            result = verify_skills_installed(bmad_dir, ["_config"], skills_dir)
            self.assertEqual(result, [])

    def test_verifies_across_multiple_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bmad_dir = os.path.join(tmpdir, "_bmad")
            skills_dir = os.path.join(tmpdir, "skills")

            _make_skill_dir(bmad_dir, "bmb", "skills", "skill-a")
            _make_skill_dir(bmad_dir, "core", "skills", "skill-b")

            os.makedirs(os.path.join(skills_dir, "skill-a"))
            os.makedirs(os.path.join(skills_dir, "skill-b"))

            result = verify_skills_installed(
                bmad_dir, ["bmb", "core"], skills_dir
            )
            self.assertEqual(result, ["skill-a", "skill-b"])


class TestCountFiles(unittest.TestCase):
    def test_counts_files_recursively(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _make_file(tmpdir, "a.txt")
            _make_file(tmpdir, "sub", "b.txt")
            _make_file(tmpdir, "sub", "deep", "c.txt")
            self.assertEqual(count_files(Path(tmpdir)), 3)

    def test_empty_dir_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertEqual(count_files(Path(tmpdir)), 0)


class TestCleanupDirectories(unittest.TestCase):
    def test_removes_single_module_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bmad_dir = os.path.join(tmpdir, "_bmad")
            os.makedirs(os.path.join(bmad_dir, "bmb", "skills"))
            _make_file(bmad_dir, "bmb", "skills", "SKILL.md")

            removed, not_found, count = cleanup_directories(bmad_dir, ["bmb"])
            self.assertEqual(removed, ["bmb"])
            self.assertEqual(not_found, [])
            self.assertGreater(count, 0)
            self.assertFalse(os.path.exists(os.path.join(bmad_dir, "bmb")))

    def test_removes_module_core_and_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bmad_dir = os.path.join(tmpdir, "_bmad")
            for dirname in ("bmb", "core", "_config"):
                _make_file(bmad_dir, dirname, "some-file.txt")

            removed, not_found, count = cleanup_directories(
                bmad_dir, ["bmb", "core", "_config"]
            )
            self.assertEqual(sorted(removed), ["_config", "bmb", "core"])
            self.assertEqual(not_found, [])
            for dirname in ("bmb", "core", "_config"):
                self.assertFalse(os.path.exists(os.path.join(bmad_dir, dirname)))

    def test_nonexistent_dir_in_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bmad_dir = os.path.join(tmpdir, "_bmad")
            os.makedirs(bmad_dir)

            removed, not_found, count = cleanup_directories(bmad_dir, ["bmb"])
            self.assertEqual(removed, [])
            self.assertEqual(not_found, ["bmb"])
            self.assertEqual(count, 0)

    def test_preserves_other_module_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bmad_dir = os.path.join(tmpdir, "_bmad")
            for dirname in ("bmb", "bmm", "tea"):
                _make_file(bmad_dir, dirname, "file.txt")

            removed, not_found, count = cleanup_directories(bmad_dir, ["bmb"])
            self.assertEqual(removed, ["bmb"])
            self.assertTrue(os.path.isdir(os.path.join(bmad_dir, "bmm")))
            self.assertTrue(os.path.isdir(os.path.join(bmad_dir, "tea")))

    def test_preserves_root_config_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bmad_dir = os.path.join(tmpdir, "_bmad")
            _make_file(bmad_dir, "config.yaml", content="key: val")
            _make_file(bmad_dir, "config.user.yaml", content="user: test")
            _make_file(bmad_dir, "module-help.csv", content="a,b,c")
            _make_file(bmad_dir, "bmb", "stuff.txt")

            cleanup_directories(bmad_dir, ["bmb"])

            self.assertTrue(os.path.exists(os.path.join(bmad_dir, "config.yaml")))
            self.assertTrue(
                os.path.exists(os.path.join(bmad_dir, "config.user.yaml"))
            )
            self.assertTrue(
                os.path.exists(os.path.join(bmad_dir, "module-help.csv"))
            )

    def test_removes_hidden_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bmad_dir = os.path.join(tmpdir, "_bmad")
            _make_file(bmad_dir, "bmb", ".DS_Store")
            _make_file(bmad_dir, "bmb", "skills", ".hidden")

            removed, not_found, count = cleanup_directories(bmad_dir, ["bmb"])
            self.assertEqual(removed, ["bmb"])
            self.assertEqual(count, 2)
            self.assertFalse(os.path.exists(os.path.join(bmad_dir, "bmb")))

    def test_idempotent_rerun(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bmad_dir = os.path.join(tmpdir, "_bmad")
            _make_file(bmad_dir, "bmb", "file.txt")

            # First run
            removed1, not_found1, _ = cleanup_directories(bmad_dir, ["bmb"])
            self.assertEqual(removed1, ["bmb"])
            self.assertEqual(not_found1, [])

            # Second run — idempotent
            removed2, not_found2, count2 = cleanup_directories(bmad_dir, ["bmb"])
            self.assertEqual(removed2, [])
            self.assertEqual(not_found2, ["bmb"])
            self.assertEqual(count2, 0)


class TestSafetyCheck(unittest.TestCase):
    def test_no_skills_dir_skips_check(self):
        """When --skills-dir is not provided, no verification happens."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bmad_dir = os.path.join(tmpdir, "_bmad")
            _make_skill_dir(bmad_dir, "bmb", "skills", "some-skill")

            # No skills_dir — cleanup should proceed without verification
            removed, not_found, count = cleanup_directories(bmad_dir, ["bmb"])
            self.assertEqual(removed, ["bmb"])

    def test_missing_skill_blocks_removal(self):
        """When --skills-dir is provided and a skill is missing, exit 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bmad_dir = os.path.join(tmpdir, "_bmad")
            skills_dir = os.path.join(tmpdir, "skills")

            _make_skill_dir(bmad_dir, "bmb", "skills", "installed-skill")
            _make_skill_dir(bmad_dir, "bmb", "skills", "missing-skill")

            os.makedirs(os.path.join(skills_dir, "installed-skill"))
            # missing-skill not created in skills_dir

            with self.assertRaises(SystemExit) as ctx:
                verify_skills_installed(bmad_dir, ["bmb"], skills_dir)
            self.assertEqual(ctx.exception.code, 1)

            # Directory should NOT have been removed (verification failed before cleanup)
            self.assertTrue(os.path.isdir(os.path.join(bmad_dir, "bmb")))

    def test_dir_without_skills_not_checked(self):
        """Directories like _config that have no SKILL.md pass verification."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bmad_dir = os.path.join(tmpdir, "_bmad")
            skills_dir = os.path.join(tmpdir, "skills")

            _make_file(bmad_dir, "_config", "manifest.yaml")
            os.makedirs(skills_dir)

            # Should not raise — _config has no skills to verify
            result = verify_skills_installed(bmad_dir, ["_config"], skills_dir)
            self.assertEqual(result, [])


class TestEndToEnd(unittest.TestCase):
    def test_full_cleanup_with_verification(self):
        """Simulate complete cleanup flow with safety check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bmad_dir = os.path.join(tmpdir, "_bmad")
            skills_dir = os.path.join(tmpdir, "skills")

            # Create legacy structure
            _make_skill_dir(bmad_dir, "bmb", "skills", "bmad-agent-builder")
            _make_skill_dir(bmad_dir, "bmb", "skills", "bmad-builder-setup")
            _make_file(bmad_dir, "bmb", "skills", "bmad-agent-builder", "assets", "template.md")
            _make_skill_dir(bmad_dir, "core", "skills", "bmad-brainstorming")
            _make_file(bmad_dir, "_config", "manifest.yaml")
            _make_file(bmad_dir, "_config", "bmad-help.csv")

            # Create root config files that must survive
            _make_file(bmad_dir, "config.yaml", content="document_output_language: English")
            _make_file(bmad_dir, "config.user.yaml", content="user_name: Test")
            _make_file(bmad_dir, "module-help.csv", content="module,name\nbmb,builder")

            # Create other module dirs that must survive
            _make_file(bmad_dir, "bmm", "config.yaml")
            _make_file(bmad_dir, "tea", "config.yaml")

            # Create installed skills
            os.makedirs(os.path.join(skills_dir, "bmad-agent-builder"))
            os.makedirs(os.path.join(skills_dir, "bmad-builder-setup"))
            os.makedirs(os.path.join(skills_dir, "bmad-brainstorming"))

            # Verify
            verified = verify_skills_installed(
                bmad_dir, ["bmb", "core", "_config"], skills_dir
            )
            self.assertIn("bmad-agent-builder", verified)
            self.assertIn("bmad-builder-setup", verified)
            self.assertIn("bmad-brainstorming", verified)

            # Cleanup
            removed, not_found, file_count = cleanup_directories(
                bmad_dir, ["bmb", "core", "_config"]
            )
            self.assertEqual(sorted(removed), ["_config", "bmb", "core"])
            self.assertEqual(not_found, [])
            self.assertGreater(file_count, 0)

            # Verify final state
            self.assertFalse(os.path.exists(os.path.join(bmad_dir, "bmb")))
            self.assertFalse(os.path.exists(os.path.join(bmad_dir, "core")))
            self.assertFalse(os.path.exists(os.path.join(bmad_dir, "_config")))

            # Root config files survived
            self.assertTrue(os.path.exists(os.path.join(bmad_dir, "config.yaml")))
            self.assertTrue(os.path.exists(os.path.join(bmad_dir, "config.user.yaml")))
            self.assertTrue(os.path.exists(os.path.join(bmad_dir, "module-help.csv")))

            # Other modules survived
            self.assertTrue(os.path.isdir(os.path.join(bmad_dir, "bmm")))
            self.assertTrue(os.path.isdir(os.path.join(bmad_dir, "tea")))

    def test_simulate_post_merge_scripts(self):
        """Simulate the full flow: merge scripts run first (delete config files),
        then cleanup removes directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bmad_dir = os.path.join(tmpdir, "_bmad")

            # Legacy state: config files already deleted by merge scripts
            # but directories and skill content remain
            _make_skill_dir(bmad_dir, "bmb", "skills", "bmad-agent-builder")
            _make_file(bmad_dir, "bmb", "skills", "bmad-agent-builder", "refs", "doc.md")
            _make_file(bmad_dir, "bmb", ".DS_Store")
            # config.yaml already deleted by merge-config.py
            # module-help.csv already deleted by merge-help-csv.py

            _make_skill_dir(bmad_dir, "core", "skills", "bmad-help")
            # core/config.yaml already deleted
            # core/module-help.csv already deleted

            # Root files from merge scripts
            _make_file(bmad_dir, "config.yaml", content="bmb:\n  name: BMad Builder")
            _make_file(bmad_dir, "config.user.yaml", content="user_name: Test")
            _make_file(bmad_dir, "module-help.csv", content="module,name")

            # Cleanup directories
            removed, not_found, file_count = cleanup_directories(
                bmad_dir, ["bmb", "core"]
            )
            self.assertEqual(sorted(removed), ["bmb", "core"])
            self.assertGreater(file_count, 0)

            # Final state: only root config files
            remaining = os.listdir(bmad_dir)
            self.assertEqual(
                sorted(remaining),
                ["config.user.yaml", "config.yaml", "module-help.csv"],
            )


if __name__ == "__main__":
    unittest.main()
