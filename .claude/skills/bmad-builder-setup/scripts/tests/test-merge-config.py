#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["pyyaml"]
# ///
"""Unit tests for merge-config.py."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add parent directory to path so we can import the module
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml

from importlib.util import spec_from_file_location, module_from_spec

# Import merge_config module
_spec = spec_from_file_location(
    "merge_config",
    str(Path(__file__).parent.parent / "merge-config.py"),
)
merge_config_mod = module_from_spec(_spec)
_spec.loader.exec_module(merge_config_mod)

extract_module_metadata = merge_config_mod.extract_module_metadata
extract_user_settings = merge_config_mod.extract_user_settings
merge_config = merge_config_mod.merge_config
load_legacy_values = merge_config_mod.load_legacy_values
apply_legacy_defaults = merge_config_mod.apply_legacy_defaults
cleanup_legacy_configs = merge_config_mod.cleanup_legacy_configs
apply_result_templates = merge_config_mod.apply_result_templates


SAMPLE_MODULE_YAML = {
    "code": "bmb",
    "name": "BMad Builder",
    "description": "Standard Skill Compliant Factory",
    "default_selected": False,
    "bmad_builder_output_folder": {
        "prompt": "Where should skills be saved?",
        "default": "_bmad-output/skills",
        "result": "{project-root}/{value}",
    },
    "bmad_builder_reports": {
        "prompt": "Output for reports?",
        "default": "_bmad-output/reports",
        "result": "{project-root}/{value}",
    },
}

SAMPLE_MODULE_YAML_WITH_VERSION = {
    **SAMPLE_MODULE_YAML,
    "module_version": "1.0.0",
}

SAMPLE_MODULE_YAML_WITH_USER_SETTING = {
    **SAMPLE_MODULE_YAML,
    "some_pref": {
        "prompt": "Your preference?",
        "default": "default_val",
        "user_setting": True,
    },
}


class TestExtractModuleMetadata(unittest.TestCase):
    def test_extracts_metadata_fields(self):
        result = extract_module_metadata(SAMPLE_MODULE_YAML)
        self.assertEqual(result["name"], "BMad Builder")
        self.assertEqual(result["description"], "Standard Skill Compliant Factory")
        self.assertFalse(result["default_selected"])

    def test_excludes_variable_definitions(self):
        result = extract_module_metadata(SAMPLE_MODULE_YAML)
        self.assertNotIn("bmad_builder_output_folder", result)
        self.assertNotIn("bmad_builder_reports", result)
        self.assertNotIn("code", result)

    def test_version_present(self):
        result = extract_module_metadata(SAMPLE_MODULE_YAML_WITH_VERSION)
        self.assertEqual(result["version"], "1.0.0")

    def test_version_absent_is_none(self):
        result = extract_module_metadata(SAMPLE_MODULE_YAML)
        self.assertIn("version", result)
        self.assertIsNone(result["version"])

    def test_field_order(self):
        result = extract_module_metadata(SAMPLE_MODULE_YAML_WITH_VERSION)
        keys = list(result.keys())
        self.assertEqual(keys, ["name", "description", "version", "default_selected"])


class TestExtractUserSettings(unittest.TestCase):
    def test_core_user_keys(self):
        answers = {
            "core": {
                "user_name": "Brian",
                "communication_language": "English",
                "document_output_language": "English",
                "output_folder": "_bmad-output",
            },
        }
        result = extract_user_settings(SAMPLE_MODULE_YAML, answers)
        self.assertEqual(result["user_name"], "Brian")
        self.assertEqual(result["communication_language"], "English")
        self.assertNotIn("document_output_language", result)
        self.assertNotIn("output_folder", result)

    def test_module_user_setting_true(self):
        answers = {
            "core": {"user_name": "Brian"},
            "module": {"some_pref": "custom_val"},
        }
        result = extract_user_settings(SAMPLE_MODULE_YAML_WITH_USER_SETTING, answers)
        self.assertEqual(result["user_name"], "Brian")
        self.assertEqual(result["some_pref"], "custom_val")

    def test_no_core_answers(self):
        answers = {"module": {"some_pref": "val"}}
        result = extract_user_settings(SAMPLE_MODULE_YAML_WITH_USER_SETTING, answers)
        self.assertNotIn("user_name", result)
        self.assertEqual(result["some_pref"], "val")

    def test_no_user_settings_in_module(self):
        answers = {
            "core": {"user_name": "Brian"},
            "module": {"bmad_builder_output_folder": "path"},
        }
        result = extract_user_settings(SAMPLE_MODULE_YAML, answers)
        self.assertEqual(result, {"user_name": "Brian"})

    def test_empty_answers(self):
        result = extract_user_settings(SAMPLE_MODULE_YAML, {})
        self.assertEqual(result, {})


class TestApplyResultTemplates(unittest.TestCase):
    def test_applies_template(self):
        answers = {"bmad_builder_output_folder": "skills"}
        result = apply_result_templates(SAMPLE_MODULE_YAML, answers)
        self.assertEqual(result["bmad_builder_output_folder"], "{project-root}/skills")

    def test_applies_multiple_templates(self):
        answers = {
            "bmad_builder_output_folder": "skills",
            "bmad_builder_reports": "skills/reports",
        }
        result = apply_result_templates(SAMPLE_MODULE_YAML, answers)
        self.assertEqual(result["bmad_builder_output_folder"], "{project-root}/skills")
        self.assertEqual(result["bmad_builder_reports"], "{project-root}/skills/reports")

    def test_skips_when_no_template(self):
        """Variables without a result field are stored as-is."""
        yaml_no_result = {
            "code": "test",
            "my_var": {"prompt": "Enter value", "default": "foo"},
        }
        answers = {"my_var": "bar"}
        result = apply_result_templates(yaml_no_result, answers)
        self.assertEqual(result["my_var"], "bar")

    def test_skips_when_value_already_has_project_root(self):
        """Prevent double-prefixing if value already contains {project-root}."""
        answers = {"bmad_builder_output_folder": "{project-root}/skills"}
        result = apply_result_templates(SAMPLE_MODULE_YAML, answers)
        self.assertEqual(result["bmad_builder_output_folder"], "{project-root}/skills")

    def test_empty_answers(self):
        result = apply_result_templates(SAMPLE_MODULE_YAML, {})
        self.assertEqual(result, {})

    def test_unknown_key_passed_through(self):
        """Keys not in module.yaml are passed through unchanged."""
        answers = {"unknown_key": "some_value"}
        result = apply_result_templates(SAMPLE_MODULE_YAML, answers)
        self.assertEqual(result["unknown_key"], "some_value")


class TestMergeConfig(unittest.TestCase):
    def test_fresh_install_with_core_and_module(self):
        answers = {
            "core": {
                "user_name": "Brian",
                "communication_language": "English",
                "document_output_language": "English",
                "output_folder": "_bmad-output",
            },
            "module": {
                "bmad_builder_output_folder": "_bmad-output/skills",
            },
        }
        result = merge_config({}, SAMPLE_MODULE_YAML, answers)

        # User-only keys must NOT appear in config.yaml
        self.assertNotIn("user_name", result)
        self.assertNotIn("communication_language", result)
        # Shared core keys do appear
        self.assertEqual(result["document_output_language"], "English")
        self.assertEqual(result["output_folder"], "_bmad-output")
        self.assertEqual(result["bmb"]["name"], "BMad Builder")
        self.assertEqual(result["bmb"]["bmad_builder_output_folder"], "{project-root}/_bmad-output/skills")

    def test_update_strips_user_keys_preserves_shared(self):
        existing = {
            "user_name": "Brian",
            "communication_language": "English",
            "document_output_language": "English",
            "other_module": {"name": "Other"},
        }
        answers = {
            "module": {
                "bmad_builder_output_folder": "_bmad-output/skills",
            },
        }
        result = merge_config(existing, SAMPLE_MODULE_YAML, answers)

        # User-only keys stripped from config
        self.assertNotIn("user_name", result)
        self.assertNotIn("communication_language", result)
        # Shared core preserved at root
        self.assertEqual(result["document_output_language"], "English")
        # Other module preserved
        self.assertIn("other_module", result)
        # New module added
        self.assertIn("bmb", result)

    def test_anti_zombie_removes_existing_module(self):
        existing = {
            "user_name": "Brian",
            "bmb": {
                "name": "BMad Builder",
                "old_variable": "should_be_removed",
                "bmad_builder_output_folder": "old/path",
            },
        }
        answers = {
            "module": {
                "bmad_builder_output_folder": "new/path",
            },
        }
        result = merge_config(existing, SAMPLE_MODULE_YAML, answers)

        # Old variable is gone
        self.assertNotIn("old_variable", result["bmb"])
        # New value is present
        self.assertEqual(result["bmb"]["bmad_builder_output_folder"], "{project-root}/new/path")
        # Metadata is fresh from module.yaml
        self.assertEqual(result["bmb"]["name"], "BMad Builder")

    def test_user_keys_never_written_to_config(self):
        existing = {
            "user_name": "OldName",
            "communication_language": "Spanish",
            "document_output_language": "French",
        }
        answers = {
            "core": {"user_name": "NewName", "communication_language": "English"},
            "module": {},
        }
        result = merge_config(existing, SAMPLE_MODULE_YAML, answers)

        # User-only keys stripped even if they were in existing config
        self.assertNotIn("user_name", result)
        self.assertNotIn("communication_language", result)
        # Shared core preserved
        self.assertEqual(result["document_output_language"], "French")

    def test_no_core_answers_still_strips_user_keys(self):
        existing = {
            "user_name": "Brian",
            "output_folder": "/out",
        }
        answers = {
            "module": {"bmad_builder_output_folder": "path"},
        }
        result = merge_config(existing, SAMPLE_MODULE_YAML, answers)

        # User-only keys stripped even without core answers
        self.assertNotIn("user_name", result)
        # Shared core unchanged
        self.assertEqual(result["output_folder"], "/out")

    def test_module_metadata_always_from_yaml(self):
        """Module metadata comes from module.yaml, not answers."""
        answers = {
            "module": {"bmad_builder_output_folder": "path"},
        }
        result = merge_config({}, SAMPLE_MODULE_YAML, answers)

        self.assertEqual(result["bmb"]["name"], "BMad Builder")
        self.assertEqual(result["bmb"]["description"], "Standard Skill Compliant Factory")
        self.assertFalse(result["bmb"]["default_selected"])

    def test_legacy_core_section_migrated_user_keys_stripped(self):
        """Old config with core: nested section — user keys stripped after migration."""
        existing = {
            "core": {
                "user_name": "Brian",
                "communication_language": "English",
                "document_output_language": "English",
                "output_folder": "/out",
            },
            "bmb": {"name": "BMad Builder"},
        }
        answers = {
            "module": {"bmad_builder_output_folder": "path"},
        }
        result = merge_config(existing, SAMPLE_MODULE_YAML, answers)

        # User-only keys stripped after migration
        self.assertNotIn("user_name", result)
        self.assertNotIn("communication_language", result)
        # Shared core values hoisted to root
        self.assertEqual(result["document_output_language"], "English")
        self.assertEqual(result["output_folder"], "/out")
        # Legacy core key removed
        self.assertNotIn("core", result)
        # Module still works
        self.assertIn("bmb", result)

    def test_legacy_core_user_keys_stripped_after_migration(self):
        """Legacy core: values get migrated, user keys stripped, shared keys kept."""
        existing = {
            "core": {"user_name": "OldName", "output_folder": "/old"},
        }
        answers = {
            "core": {"user_name": "NewName", "output_folder": "/new"},
            "module": {},
        }
        result = merge_config(existing, SAMPLE_MODULE_YAML, answers)

        # User-only key not in config even after migration + override
        self.assertNotIn("user_name", result)
        self.assertNotIn("core", result)
        # Shared core key written
        self.assertEqual(result["output_folder"], "/new")


class TestEndToEnd(unittest.TestCase):
    def test_write_and_read_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "_bmad", "config.yaml")

            # Write answers
            answers = {
                "core": {
                    "user_name": "Brian",
                    "communication_language": "English",
                    "document_output_language": "English",
                    "output_folder": "_bmad-output",
                },
                "module": {"bmad_builder_output_folder": "_bmad-output/skills"},
            }

            # Run merge
            result = merge_config({}, SAMPLE_MODULE_YAML, answers)
            merge_config_mod.write_config(result, config_path)

            # Read back
            with open(config_path, "r") as f:
                written = yaml.safe_load(f)

            # User-only keys not written to config.yaml
            self.assertNotIn("user_name", written)
            self.assertNotIn("communication_language", written)
            # Shared core keys written
            self.assertEqual(written["document_output_language"], "English")
            self.assertEqual(written["output_folder"], "_bmad-output")
            self.assertEqual(written["bmb"]["bmad_builder_output_folder"], "{project-root}/_bmad-output/skills")

    def test_update_round_trip(self):
        """Simulate install, then re-install with different values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "config.yaml")

            # First install
            answers1 = {
                "core": {"output_folder": "/out"},
                "module": {"bmad_builder_output_folder": "old/path"},
            }
            result1 = merge_config({}, SAMPLE_MODULE_YAML, answers1)
            merge_config_mod.write_config(result1, config_path)

            # Second install (update)
            existing = merge_config_mod.load_yaml_file(config_path)
            answers2 = {
                "module": {"bmad_builder_output_folder": "new/path"},
            }
            result2 = merge_config(existing, SAMPLE_MODULE_YAML, answers2)
            merge_config_mod.write_config(result2, config_path)

            # Verify
            with open(config_path, "r") as f:
                final = yaml.safe_load(f)

            self.assertEqual(final["output_folder"], "/out")
            self.assertNotIn("user_name", final)
            self.assertEqual(final["bmb"]["bmad_builder_output_folder"], "{project-root}/new/path")


class TestLoadLegacyValues(unittest.TestCase):
    def _make_legacy_dir(self, tmpdir, core_data=None, module_code=None, module_data=None):
        """Create legacy directory structure for testing."""
        legacy_dir = os.path.join(tmpdir, "_bmad")
        if core_data is not None:
            core_dir = os.path.join(legacy_dir, "core")
            os.makedirs(core_dir, exist_ok=True)
            with open(os.path.join(core_dir, "config.yaml"), "w") as f:
                yaml.dump(core_data, f)
        if module_code and module_data is not None:
            mod_dir = os.path.join(legacy_dir, module_code)
            os.makedirs(mod_dir, exist_ok=True)
            with open(os.path.join(mod_dir, "config.yaml"), "w") as f:
                yaml.dump(module_data, f)
        return legacy_dir

    def test_reads_core_keys_from_core_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_dir = self._make_legacy_dir(tmpdir, core_data={
                "user_name": "Brian",
                "communication_language": "English",
                "document_output_language": "English",
                "output_folder": "/out",
            })
            core, mod, files = load_legacy_values(legacy_dir, "bmb", SAMPLE_MODULE_YAML)
            self.assertEqual(core["user_name"], "Brian")
            self.assertEqual(core["communication_language"], "English")
            self.assertEqual(len(files), 1)
            self.assertEqual(mod, {})

    def test_reads_module_keys_matching_yaml_variables(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_dir = self._make_legacy_dir(
                tmpdir,
                module_code="bmb",
                module_data={
                    "bmad_builder_output_folder": "custom/path",
                    "bmad_builder_reports": "custom/reports",
                    "user_name": "Brian",  # core key duplicated
                    "unknown_key": "ignored",  # not in module.yaml
                },
            )
            core, mod, files = load_legacy_values(legacy_dir, "bmb", SAMPLE_MODULE_YAML)
            self.assertEqual(mod["bmad_builder_output_folder"], "custom/path")
            self.assertEqual(mod["bmad_builder_reports"], "custom/reports")
            self.assertNotIn("unknown_key", mod)
            # Core key from module config used as fallback
            self.assertEqual(core["user_name"], "Brian")
            self.assertEqual(len(files), 1)

    def test_core_config_takes_priority_over_module_for_core_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_dir = self._make_legacy_dir(
                tmpdir,
                core_data={"user_name": "FromCore"},
                module_code="bmb",
                module_data={"user_name": "FromModule"},
            )
            core, mod, files = load_legacy_values(legacy_dir, "bmb", SAMPLE_MODULE_YAML)
            self.assertEqual(core["user_name"], "FromCore")
            self.assertEqual(len(files), 2)

    def test_no_legacy_files_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_dir = os.path.join(tmpdir, "_bmad")
            os.makedirs(legacy_dir)
            core, mod, files = load_legacy_values(legacy_dir, "bmb", SAMPLE_MODULE_YAML)
            self.assertEqual(core, {})
            self.assertEqual(mod, {})
            self.assertEqual(files, [])

    def test_ignores_other_module_directories(self):
        """Only reads core and the specified module_code — not other modules."""
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_dir = self._make_legacy_dir(
                tmpdir,
                module_code="bmb",
                module_data={"bmad_builder_output_folder": "bmb/path"},
            )
            # Create another module directory that should be ignored
            other_dir = os.path.join(legacy_dir, "cis")
            os.makedirs(other_dir)
            with open(os.path.join(other_dir, "config.yaml"), "w") as f:
                yaml.dump({"visual_tools": "advanced"}, f)

            core, mod, files = load_legacy_values(legacy_dir, "bmb", SAMPLE_MODULE_YAML)
            self.assertNotIn("visual_tools", mod)
            self.assertEqual(len(files), 1)  # only bmb, not cis


class TestApplyLegacyDefaults(unittest.TestCase):
    def test_legacy_fills_missing_core(self):
        answers = {"module": {"bmad_builder_output_folder": "path"}}
        result = apply_legacy_defaults(
            answers,
            legacy_core={"user_name": "Brian", "communication_language": "English"},
            legacy_module={},
        )
        self.assertEqual(result["core"]["user_name"], "Brian")
        self.assertEqual(result["module"]["bmad_builder_output_folder"], "path")

    def test_answers_override_legacy(self):
        answers = {
            "core": {"user_name": "NewName"},
            "module": {"bmad_builder_output_folder": "new/path"},
        }
        result = apply_legacy_defaults(
            answers,
            legacy_core={"user_name": "OldName"},
            legacy_module={"bmad_builder_output_folder": "old/path"},
        )
        self.assertEqual(result["core"]["user_name"], "NewName")
        self.assertEqual(result["module"]["bmad_builder_output_folder"], "new/path")

    def test_legacy_fills_missing_module_keys(self):
        answers = {"module": {}}
        result = apply_legacy_defaults(
            answers,
            legacy_core={},
            legacy_module={"bmad_builder_output_folder": "legacy/path"},
        )
        self.assertEqual(result["module"]["bmad_builder_output_folder"], "legacy/path")

    def test_empty_legacy_is_noop(self):
        answers = {"core": {"user_name": "Brian"}, "module": {"key": "val"}}
        result = apply_legacy_defaults(answers, {}, {})
        self.assertEqual(result, answers)


class TestCleanupLegacyConfigs(unittest.TestCase):
    def test_deletes_module_and_core_configs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_dir = os.path.join(tmpdir, "_bmad")
            for subdir in ("core", "bmb"):
                d = os.path.join(legacy_dir, subdir)
                os.makedirs(d)
                with open(os.path.join(d, "config.yaml"), "w") as f:
                    f.write("key: val\n")

            deleted = cleanup_legacy_configs(legacy_dir, "bmb")
            self.assertEqual(len(deleted), 2)
            self.assertFalse(os.path.exists(os.path.join(legacy_dir, "core", "config.yaml")))
            self.assertFalse(os.path.exists(os.path.join(legacy_dir, "bmb", "config.yaml")))
            # Directories still exist
            self.assertTrue(os.path.isdir(os.path.join(legacy_dir, "core")))
            self.assertTrue(os.path.isdir(os.path.join(legacy_dir, "bmb")))

    def test_leaves_other_module_configs_alone(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_dir = os.path.join(tmpdir, "_bmad")
            for subdir in ("bmb", "cis"):
                d = os.path.join(legacy_dir, subdir)
                os.makedirs(d)
                with open(os.path.join(d, "config.yaml"), "w") as f:
                    f.write("key: val\n")

            deleted = cleanup_legacy_configs(legacy_dir, "bmb")
            self.assertEqual(len(deleted), 1)  # only bmb, not cis
            self.assertTrue(os.path.exists(os.path.join(legacy_dir, "cis", "config.yaml")))

    def test_no_legacy_files_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            deleted = cleanup_legacy_configs(tmpdir, "bmb")
            self.assertEqual(deleted, [])


class TestLegacyEndToEnd(unittest.TestCase):
    def test_full_legacy_migration(self):
        """Simulate installing a module with legacy configs present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "_bmad", "config.yaml")
            legacy_dir = os.path.join(tmpdir, "_bmad")

            # Create legacy core config
            core_dir = os.path.join(legacy_dir, "core")
            os.makedirs(core_dir)
            with open(os.path.join(core_dir, "config.yaml"), "w") as f:
                yaml.dump({
                    "user_name": "LegacyUser",
                    "communication_language": "Spanish",
                    "document_output_language": "French",
                    "output_folder": "/legacy/out",
                }, f)

            # Create legacy module config
            mod_dir = os.path.join(legacy_dir, "bmb")
            os.makedirs(mod_dir)
            with open(os.path.join(mod_dir, "config.yaml"), "w") as f:
                yaml.dump({
                    "bmad_builder_output_folder": "legacy/skills",
                    "bmad_builder_reports": "legacy/reports",
                    "user_name": "LegacyUser",  # duplicated core key
                }, f)

            # Answers from the user (only partially filled — user accepted some defaults)
            answers = {
                "core": {"user_name": "NewUser"},
                "module": {"bmad_builder_output_folder": "new/skills"},
            }

            # Load and apply legacy
            legacy_core, legacy_module, _ = load_legacy_values(
                legacy_dir, "bmb", SAMPLE_MODULE_YAML
            )
            answers = apply_legacy_defaults(answers, legacy_core, legacy_module)

            # Core: NewUser overrides legacy, but legacy Spanish fills in communication_language
            self.assertEqual(answers["core"]["user_name"], "NewUser")
            self.assertEqual(answers["core"]["communication_language"], "Spanish")

            # Module: new/skills overrides, but legacy/reports fills in
            self.assertEqual(answers["module"]["bmad_builder_output_folder"], "new/skills")
            self.assertEqual(answers["module"]["bmad_builder_reports"], "legacy/reports")

            # Merge
            result = merge_config({}, SAMPLE_MODULE_YAML, answers)
            merge_config_mod.write_config(result, config_path)

            # Cleanup
            deleted = cleanup_legacy_configs(legacy_dir, "bmb")
            self.assertEqual(len(deleted), 2)
            self.assertFalse(os.path.exists(os.path.join(core_dir, "config.yaml")))
            self.assertFalse(os.path.exists(os.path.join(mod_dir, "config.yaml")))

            # Verify final config — user-only keys NOT in config.yaml
            with open(config_path, "r") as f:
                final = yaml.safe_load(f)
            self.assertNotIn("user_name", final)
            self.assertNotIn("communication_language", final)
            # Shared core keys present
            self.assertEqual(final["document_output_language"], "French")
            self.assertEqual(final["output_folder"], "/legacy/out")
            self.assertEqual(final["bmb"]["bmad_builder_output_folder"], "{project-root}/new/skills")
            self.assertEqual(final["bmb"]["bmad_builder_reports"], "{project-root}/legacy/reports")


if __name__ == "__main__":
    unittest.main()
