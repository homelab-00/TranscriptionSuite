"""
Config tree parser and in-place editor for config.yaml.

Parses config.yaml into a structured tree with metadata (comments, types,
nesting) for dynamic UI generation. Supports in-place editing that preserves
comments and formatting.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


def _detect_type(value: Any) -> str:
    """Map a Python value to a simple type string for the frontend."""
    if value is None:
        return "string"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return "string"


def _humanise_key(key: str) -> str:
    """Turn a snake_case YAML key into a human-readable title."""
    return key.replace("_", " ").replace("-", " ").title()


# ---------------------------------------------------------------------------
# Parser – reads YAML + comments into a tree
# ---------------------------------------------------------------------------


def _collect_preceding_comments(lines: list[str], yaml_line_idx: int) -> str:
    """Walk backwards from *yaml_line_idx* and collect comment lines."""
    comments: list[str] = []
    i = yaml_line_idx - 1
    while i >= 0:
        stripped = lines[i].strip()
        if stripped.startswith("#"):
            # Strip leading '#', optional space, and decoration lines
            text = stripped.lstrip("#").strip()
            if text and not all(c in "-= " for c in text):
                comments.append(text)
        elif stripped == "":
            # blank line – keep walking but don't collect
            pass
        else:
            break
        i -= 1
    comments.reverse()
    return " ".join(comments) if comments else ""


def _collect_inline_comment(line: str) -> str:
    """Extract an inline comment from a YAML line (e.g. ``key: val  # note``)."""
    # Avoid matching '#' inside quoted strings – simple heuristic: split on
    # the *last* unquoted '#'.
    parts = line.split("#")
    if len(parts) >= 2:
        candidate = parts[-1].strip()
        if candidate:
            return candidate
    return ""


def parse_config_tree(config_path: Path) -> dict[str, Any]:
    """
    Parse *config_path* into a structured JSON-ready tree.

    Returns::

        {
            "sections": [
                {
                    "key": "longform_recording",
                    "title": "Longform Recording",
                    "comment": "Settings for live recording mode ...",
                    "fields": [
                        {
                            "key": "language",
                            "path": "longform_recording.language",
                            "value": null,
                            "type": "string",
                            "comment": "Language code for transcription ..."
                        },
                        ...
                    ],
                    "subsections": [ ... ]
                },
                ...
            ]
        }
    """
    raw_text = config_path.read_text(encoding="utf-8")
    lines = raw_text.splitlines()
    parsed: dict[str, Any] = yaml.safe_load(raw_text) or {}

    sections: list[dict[str, Any]] = []

    for section_key, section_val in parsed.items():
        if not isinstance(section_val, dict):
            # Top-level scalar (unlikely but handle gracefully)
            continue

        # Find the line number of the section key in the raw file
        section_line_idx = _find_key_line(lines, section_key, indent=0)
        section_comment = (
            _collect_preceding_comments(lines, section_line_idx)
            if section_line_idx is not None
            else ""
        )

        fields: list[dict[str, Any]] = []
        subsections: list[dict[str, Any]] = []

        for field_key, field_val in section_val.items():
            if isinstance(field_val, dict):
                # Nested subsection (e.g. remote_server.tls)
                sub_line_idx = _find_key_line(
                    lines, field_key, indent=4, after=section_line_idx or 0
                )
                sub_comment = (
                    _collect_preceding_comments(lines, sub_line_idx)
                    if sub_line_idx is not None
                    else ""
                )
                sub_fields: list[dict[str, Any]] = []
                for sub_key, sub_val in field_val.items():
                    if isinstance(sub_val, dict):
                        # Skip deeper nesting for now
                        continue
                    sub_field_line = _find_key_line(
                        lines, sub_key, indent=8, after=sub_line_idx or 0
                    )
                    sub_field_comment = (
                        _collect_preceding_comments(lines, sub_field_line)
                        if sub_field_line is not None
                        else ""
                    )
                    if not sub_field_comment and sub_field_line is not None:
                        sub_field_comment = _collect_inline_comment(lines[sub_field_line])
                    sub_fields.append(
                        {
                            "key": sub_key,
                            "path": f"{section_key}.{field_key}.{sub_key}",
                            "value": sub_val,
                            "type": _detect_type(sub_val),
                            "comment": sub_field_comment,
                        }
                    )
                subsections.append(
                    {
                        "key": field_key,
                        "title": _humanise_key(field_key),
                        "comment": sub_comment,
                        "fields": sub_fields,
                    }
                )
            else:
                field_line_idx = _find_key_line(
                    lines, field_key, indent=4, after=section_line_idx or 0
                )
                field_comment = (
                    _collect_preceding_comments(lines, field_line_idx)
                    if field_line_idx is not None
                    else ""
                )
                if not field_comment and field_line_idx is not None:
                    field_comment = _collect_inline_comment(lines[field_line_idx])
                fields.append(
                    {
                        "key": field_key,
                        "path": f"{section_key}.{field_key}",
                        "value": field_val,
                        "type": _detect_type(field_val),
                        "comment": field_comment,
                    }
                )

        sections.append(
            {
                "key": section_key,
                "title": _humanise_key(section_key),
                "comment": section_comment,
                "fields": fields,
                "subsections": subsections,
            }
        )

    return {"sections": sections}


def _find_key_line(
    lines: list[str],
    key: str,
    indent: int = 0,
    after: int = 0,
) -> int | None:
    """Find the first line that defines *key* at the given indentation level."""
    prefix = " " * indent
    pattern = re.compile(rf"^{prefix}{re.escape(key)}\s*:")
    for idx in range(after, len(lines)):
        if pattern.match(lines[idx]):
            return idx
    return None


# ---------------------------------------------------------------------------
# In-place editor – update values while preserving comments and formatting
# ---------------------------------------------------------------------------


def apply_config_updates(
    config_path: Path,
    updates: dict[str, Any],
) -> dict[str, str]:
    """
    Apply *updates* to *config_path* in-place, preserving comments/formatting.

    *updates* is a dict mapping dotted key paths to new values, e.g.::

        {"longform_recording.language": "en", "diarization.parallel": true}

    Returns a dict of ``{path: "ok" | "error: ..."}`` for each update.
    """
    raw_text = config_path.read_text(encoding="utf-8")
    lines = raw_text.splitlines(keepends=True)
    results: dict[str, str] = {}

    for dotted_path, new_value in updates.items():
        keys = dotted_path.split(".")
        try:
            lines = _apply_single_update(lines, keys, new_value)
            results[dotted_path] = "ok"
        except Exception as exc:
            logger.warning("Failed to update %s: %s", dotted_path, exc)
            results[dotted_path] = f"error: {exc}"

    config_path.write_text("".join(lines), encoding="utf-8")

    # Also update the in-memory ServerConfig so the running server sees changes
    _sync_in_memory_config(config_path, updates)

    return results


def _sync_in_memory_config(config_path: Path, updates: dict[str, Any]) -> None:
    """Update the singleton ServerConfig in-memory dict after file writes."""
    try:
        from server.config import get_config

        cfg = get_config()
        for dotted_path, new_value in updates.items():
            keys = dotted_path.split(".")
            cfg.set(*keys, value=new_value)
    except Exception as exc:
        logger.debug("Could not sync in-memory config: %s", exc)


def _yaml_serialise_value(value: Any) -> str:
    """Serialise a Python value to inline YAML string."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        # Quote strings that could be misinterpreted by YAML
        if (
            value in ("true", "false", "null", "yes", "no", "on", "off", "")
            or value != value.strip()
            or any(c in value for c in ":{}[]!&*?,#|>@`\"'")
            or re.match(r"^[\d.eE+-]+$", value)
        ):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        return value
    if isinstance(value, list):
        # Inline flow-style list
        inner = ", ".join(_yaml_serialise_value(v) for v in value)
        return f"[{inner}]"
    # Fallback: use yaml.dump for complex types
    return yaml.dump(value, default_flow_style=True).strip()


def _apply_single_update(
    lines: list[str],
    keys: list[str],
    new_value: Any,
) -> list[str]:
    """
    Find the YAML line for *keys* and replace its value in *lines*.

    Supports 1-, 2-, and 3-level key paths.
    """
    if not keys:
        raise ValueError("Empty key path")

    # Walk through the key path, finding each level's line
    current_after = 0
    indent_level = 0
    target_line_idx: int | None = None

    for i, key in enumerate(keys):
        indent = indent_level * 4
        target_line_idx = _find_key_line(lines, key, indent=indent, after=current_after)
        if target_line_idx is None:
            raise KeyError(f"Key '{key}' not found at indent {indent} (path: {'.'.join(keys)})")
        if i < len(keys) - 1:
            # Move search window past this line for the next level
            current_after = target_line_idx + 1
            indent_level += 1

    assert target_line_idx is not None
    line = lines[target_line_idx]

    # Handle multi-line string values (block scalars with |)
    # For multi-line values, we need to detect and handle the block scalar
    last_key = keys[-1]
    indent_str = " " * (len(keys) - 1) * 4

    # Check if the current value is a block scalar (| or >)
    block_match = re.match(
        rf"^({re.escape(indent_str)}{re.escape(last_key)}\s*:\s*)[|>]",
        line,
    )
    if block_match:
        # Remove the block scalar and its continuation lines
        new_lines = list(lines)
        serialised = _yaml_serialise_value(new_value)
        new_lines[target_line_idx] = f"{indent_str}{last_key}: {serialised}\n"
        # Remove continuation lines (indented more than the key)
        block_indent = len(indent_str) + 4
        idx = target_line_idx + 1
        while idx < len(new_lines):
            stripped = new_lines[idx]
            if stripped.strip() == "" or (
                len(stripped) > len(stripped.lstrip())
                and len(stripped) - len(stripped.lstrip()) >= block_indent
            ):
                new_lines.pop(idx)
            else:
                break
        return new_lines

    # Standard single-line value replacement
    # Match: indent + key + colon + optional_space + value + optional_inline_comment
    pattern = re.compile(
        rf"^({re.escape(indent_str)}{re.escape(last_key)}\s*:\s*)(.*?)(\s*#.*)?\n?$"
    )
    m = pattern.match(line)
    if not m:
        raise ValueError(f"Could not parse line for key '{last_key}': {line!r}")

    prefix = m.group(1)
    inline_comment = m.group(3) or ""
    serialised = _yaml_serialise_value(new_value)

    new_line = f"{prefix}{serialised}{inline_comment}\n"
    new_lines = list(lines)
    new_lines[target_line_idx] = new_line
    return new_lines
