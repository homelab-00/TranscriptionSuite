"""Tests for server.config_tree — pure logic, no ML dependencies.

Covers:
- ``_detect_type`` for all Python value types
- ``_humanise_key`` snake_case / kebab-case → Title Case
- ``_collect_preceding_comments`` and ``_collect_inline_comment``
- ``parse_config_tree`` full parse on a small config file
- ``apply_config_updates`` in-place editing preserves comments
- ``_yaml_serialise_value`` for scalars, booleans, lists, None
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from server.config_tree import (
    _collect_inline_comment,
    _collect_preceding_comments,
    _detect_type,
    _find_key_line,
    _humanise_key,
    _yaml_serialise_value,
    apply_config_updates,
    parse_config_tree,
)

# ── _detect_type ──────────────────────────────────────────────────────────


class TestDetectType:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, "string"),
            (True, "boolean"),
            (False, "boolean"),
            (42, "integer"),
            (3.14, "float"),
            ([1, 2], "list"),
            ({"a": 1}, "object"),
            ("hello", "string"),
        ],
    )
    def test_type_detection(self, value, expected):
        assert _detect_type(value) == expected

    def test_bool_before_int(self):
        """bool is a subclass of int in Python — ensure bool is detected first."""
        assert _detect_type(True) == "boolean"


# ── _humanise_key ─────────────────────────────────────────────────────────


class TestHumaniseKey:
    @pytest.mark.parametrize(
        "key, expected",
        [
            ("simple", "Simple"),
            ("snake_case", "Snake Case"),
            ("kebab-case", "Kebab Case"),
            ("multi_word_key", "Multi Word Key"),
            ("already_Capitalized", "Already Capitalized"),
        ],
    )
    def test_humanise(self, key, expected):
        assert _humanise_key(key) == expected


# ── Comment extraction ───────────────────────────────────────────────────


class TestCommentExtraction:
    def test_preceding_comments(self):
        lines = [
            "# This is the description",
            "# of the field below",
            "key: value",
        ]

        result = _collect_preceding_comments(lines, 2)

        assert result == "This is the description of the field below"

    def test_preceding_comments_skip_blanks(self):
        lines = [
            "# Comment",
            "",
            "key: value",
        ]

        result = _collect_preceding_comments(lines, 2)

        assert result == "Comment"

    def test_preceding_comments_stop_at_non_comment(self):
        lines = [
            "other: val",
            "# Only this",
            "key: value",
        ]

        result = _collect_preceding_comments(lines, 2)

        assert result == "Only this"

    def test_no_preceding_comments(self):
        lines = ["key: value"]

        result = _collect_preceding_comments(lines, 0)

        assert result == ""

    def test_inline_comment(self):
        assert _collect_inline_comment("key: value  # my note") == "my note"

    def test_no_inline_comment(self):
        assert _collect_inline_comment("key: value") == ""


# ── _find_key_line ───────────────────────────────────────────────────────


class TestFindKeyLine:
    def test_finds_top_level_key(self):
        lines = ["top_key:", "  nested: val"]

        assert _find_key_line(lines, "top_key", indent=0) == 0

    def test_finds_nested_key(self):
        lines = ["section:", "    field: val"]

        assert _find_key_line(lines, "field", indent=4) == 1

    def test_returns_none_when_not_found(self):
        lines = ["other: val"]

        assert _find_key_line(lines, "missing", indent=0) is None

    def test_after_parameter(self):
        lines = ["a:", "b:", "a:"]

        assert _find_key_line(lines, "a", indent=0, after=1) == 2


# ── _yaml_serialise_value ────────────────────────────────────────────────


class TestYamlSerialiseValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, "null"),
            (True, "true"),
            (False, "false"),
            (42, "42"),
            (3.14, "3.14"),
        ],
    )
    def test_scalars(self, value, expected):
        assert _yaml_serialise_value(value) == expected

    def test_plain_string(self):
        assert _yaml_serialise_value("hello") == "hello"

    def test_string_needing_quoting(self):
        result = _yaml_serialise_value("true")

        assert result == '"true"'

    def test_empty_string_quoted(self):
        result = _yaml_serialise_value("")

        assert result == '""'

    def test_list_inline(self):
        result = _yaml_serialise_value([1, "a", True])

        assert result == "[1, a, true]"


# ── parse_config_tree ────────────────────────────────────────────────────


class TestParseConfigTree:
    @pytest.fixture()
    def sample_config(self, tmp_path: Path) -> Path:
        config = tmp_path / "config.yaml"
        config.write_text(
            """\
# Settings for recording mode
longform_recording:
    # Language code
    language: null
    # Number of workers
    num_workers: 4
    enabled: true

# Server settings
remote_server:
    host: 0.0.0.0
    port: 8000
    tls:
        enabled: false
        cert_path: /etc/ssl/cert.pem
""",
            encoding="utf-8",
        )
        return config

    def test_parses_sections(self, sample_config: Path):
        tree = parse_config_tree(sample_config)

        keys = [s["key"] for s in tree["sections"]]
        assert "longform_recording" in keys
        assert "remote_server" in keys

    def test_section_title_humanised(self, sample_config: Path):
        tree = parse_config_tree(sample_config)
        lr = next(s for s in tree["sections"] if s["key"] == "longform_recording")

        assert lr["title"] == "Longform Recording"

    def test_section_comment_extracted(self, sample_config: Path):
        tree = parse_config_tree(sample_config)
        lr = next(s for s in tree["sections"] if s["key"] == "longform_recording")

        assert "recording" in lr["comment"].lower()

    def test_field_types_detected(self, sample_config: Path):
        tree = parse_config_tree(sample_config)
        lr = next(s for s in tree["sections"] if s["key"] == "longform_recording")
        fields = {f["key"]: f for f in lr["fields"]}

        assert fields["language"]["type"] == "string"  # null → string
        assert fields["num_workers"]["type"] == "integer"
        assert fields["enabled"]["type"] == "boolean"

    def test_subsection_parsed(self, sample_config: Path):
        tree = parse_config_tree(sample_config)
        rs = next(s for s in tree["sections"] if s["key"] == "remote_server")

        assert len(rs["subsections"]) == 1
        assert rs["subsections"][0]["key"] == "tls"

    def test_field_path_dotted(self, sample_config: Path):
        tree = parse_config_tree(sample_config)
        lr = next(s for s in tree["sections"] if s["key"] == "longform_recording")
        lang = next(f for f in lr["fields"] if f["key"] == "language")

        assert lang["path"] == "longform_recording.language"


# ── apply_config_updates ─────────────────────────────────────────────────


class TestApplyConfigUpdates:
    @pytest.fixture()
    def editable_config(self, tmp_path: Path) -> Path:
        config = tmp_path / "config.yaml"
        config.write_text(
            """\
# Top-level comment
longform_recording:
    language: null  # override language
    num_workers: 4
    enabled: true
""",
            encoding="utf-8",
        )
        return config

    @patch("server.config_tree._sync_in_memory_config")
    def test_updates_value_in_place(self, mock_sync, editable_config: Path):
        results = apply_config_updates(editable_config, {"longform_recording.language": "en"})

        assert results["longform_recording.language"] == "ok"
        updated = yaml.safe_load(editable_config.read_text())
        assert updated["longform_recording"]["language"] == "en"

    @patch("server.config_tree._sync_in_memory_config")
    def test_preserves_comments(self, mock_sync, editable_config: Path):
        apply_config_updates(editable_config, {"longform_recording.language": "de"})

        raw = editable_config.read_text()
        assert "# Top-level comment" in raw
        assert "# override language" in raw

    @patch("server.config_tree._sync_in_memory_config")
    def test_boolean_update(self, mock_sync, editable_config: Path):
        apply_config_updates(editable_config, {"longform_recording.enabled": False})

        updated = yaml.safe_load(editable_config.read_text())
        assert updated["longform_recording"]["enabled"] is False

    @patch("server.config_tree._sync_in_memory_config")
    def test_missing_key_returns_error(self, mock_sync, editable_config: Path):
        results = apply_config_updates(editable_config, {"longform_recording.nonexistent": "x"})

        assert results["longform_recording.nonexistent"].startswith("error:")

    @patch("server.config_tree._sync_in_memory_config")
    def test_multiple_updates(self, mock_sync, editable_config: Path):
        results = apply_config_updates(
            editable_config,
            {
                "longform_recording.language": "fr",
                "longform_recording.num_workers": 8,
            },
        )

        assert all(v == "ok" for v in results.values())
        updated = yaml.safe_load(editable_config.read_text())
        assert updated["longform_recording"]["language"] == "fr"
        assert updated["longform_recording"]["num_workers"] == 8
