/**
 * Config tree parser and in-place editor for config.yaml.
 *
 * TypeScript port of server/backend/config_tree.py.
 * Parses config.yaml into a structured tree with metadata (comments, types,
 * nesting) for dynamic UI generation.  Supports in-place editing that
 * preserves comments and formatting.
 */

import YAML from 'yaml';
import type { ConfigField, ConfigSection, ConfigSubsection, ServerConfigTree } from '../api/types';

// ---------------------------------------------------------------------------
// Type detection
// ---------------------------------------------------------------------------

function detectType(value: unknown): ConfigField['type'] {
  if (value === null || value === undefined) return 'string';
  if (typeof value === 'boolean') return 'boolean';
  if (typeof value === 'number') return Number.isInteger(value) ? 'integer' : 'float';
  if (Array.isArray(value)) return 'list';
  if (typeof value === 'object') return 'object';
  return 'string';
}

function humaniseKey(key: string): string {
  return key.replace(/[_-]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

// ---------------------------------------------------------------------------
// Comment collection
// ---------------------------------------------------------------------------

function collectPrecedingComments(lines: string[], yamlLineIdx: number): string {
  const comments: string[] = [];
  let i = yamlLineIdx - 1;
  while (i >= 0) {
    const stripped = lines[i].trim();
    if (stripped.startsWith('#')) {
      const text = stripped.replace(/^#+\s*/, '').trim();
      if (text && !/^[-= ]+$/.test(text)) {
        comments.push(text);
      }
    } else if (stripped === '') {
      // blank line — keep walking
    } else {
      break;
    }
    i -= 1;
  }
  comments.reverse();
  return comments.join(' ');
}

function collectInlineComment(line: string): string {
  const parts = line.split('#');
  if (parts.length >= 2) {
    const candidate = parts[parts.length - 1].trim();
    if (candidate) return candidate;
  }
  return '';
}

// ---------------------------------------------------------------------------
// Find a YAML key at a given indentation level
// ---------------------------------------------------------------------------

function findKeyLine(
  lines: string[],
  key: string,
  indent: number = 0,
  after: number = 0,
): number | null {
  const prefix = ' '.repeat(indent);
  const re = new RegExp(`^${escapeRegExp(prefix)}${escapeRegExp(key)}\\s*:`);
  for (let idx = after; idx < lines.length; idx++) {
    if (re.test(lines[idx])) return idx;
  }
  return null;
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// ---------------------------------------------------------------------------
// Parser — reads YAML + comments into a ServerConfigTree
// ---------------------------------------------------------------------------

/**
 * Parse raw YAML text into a structured {@link ServerConfigTree}.
 *
 * This replicates `parse_config_tree()` from `server/backend/config_tree.py`.
 */
export function parseConfigTree(yamlText: string): ServerConfigTree {
  const lines = yamlText.split('\n');
  const parsed: Record<string, unknown> = (YAML.parse(yamlText) as Record<string, unknown>) ?? {};

  const sections: ConfigSection[] = [];

  for (const [sectionKey, sectionVal] of Object.entries(parsed)) {
    if (typeof sectionVal !== 'object' || sectionVal === null || Array.isArray(sectionVal)) {
      continue;
    }

    const sectionDict = sectionVal as Record<string, unknown>;
    const sectionLineIdx = findKeyLine(lines, sectionKey, 0);
    const sectionComment =
      sectionLineIdx !== null ? collectPrecedingComments(lines, sectionLineIdx) : '';

    const fields: ConfigField[] = [];
    const subsections: ConfigSubsection[] = [];

    for (const [fieldKey, fieldVal] of Object.entries(sectionDict)) {
      if (typeof fieldVal === 'object' && fieldVal !== null && !Array.isArray(fieldVal)) {
        // Nested subsection (e.g. remote_server.tls)
        const subDict = fieldVal as Record<string, unknown>;
        const subLineIdx = findKeyLine(lines, fieldKey, 4, sectionLineIdx ?? 0);
        let subComment = subLineIdx !== null ? collectPrecedingComments(lines, subLineIdx) : '';

        const subFields: ConfigField[] = [];
        for (const [subKey, subVal] of Object.entries(subDict)) {
          if (typeof subVal === 'object' && subVal !== null && !Array.isArray(subVal)) {
            continue; // skip deeper nesting
          }
          const subFieldLine = findKeyLine(lines, subKey, 8, subLineIdx ?? 0);
          let subFieldComment =
            subFieldLine !== null ? collectPrecedingComments(lines, subFieldLine) : '';
          if (!subFieldComment && subFieldLine !== null) {
            subFieldComment = collectInlineComment(lines[subFieldLine]);
          }
          subFields.push({
            key: subKey,
            path: `${sectionKey}.${fieldKey}.${subKey}`,
            value: subVal,
            type: detectType(subVal),
            comment: subFieldComment,
          });
        }

        if (!subComment && subLineIdx !== null) {
          subComment = collectInlineComment(lines[subLineIdx]);
        }

        subsections.push({
          key: fieldKey,
          title: humaniseKey(fieldKey),
          comment: subComment,
          fields: subFields,
        });
      } else {
        const fieldLineIdx = findKeyLine(lines, fieldKey, 4, sectionLineIdx ?? 0);
        let fieldComment =
          fieldLineIdx !== null ? collectPrecedingComments(lines, fieldLineIdx) : '';
        if (!fieldComment && fieldLineIdx !== null) {
          fieldComment = collectInlineComment(lines[fieldLineIdx]);
        }
        fields.push({
          key: fieldKey,
          path: `${sectionKey}.${fieldKey}`,
          value: fieldVal,
          type: detectType(fieldVal),
          comment: fieldComment,
        });
      }
    }

    sections.push({
      key: sectionKey,
      title: humaniseKey(sectionKey),
      comment: sectionComment,
      fields,
      subsections,
    });
  }

  return { sections };
}

// ---------------------------------------------------------------------------
// In-place editor — update values while preserving comments and formatting
// ---------------------------------------------------------------------------

/** Serialise a JS value to inline YAML string. */
function yamlSerialiseValue(value: unknown): string {
  if (value === null || value === undefined) return 'null';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') return String(value);
  if (typeof value === 'string') {
    if (
      ['true', 'false', 'null', 'yes', 'no', 'on', 'off', ''].includes(value) ||
      value !== value.trim() ||
      /[:{}[\]!&*?,#|>@`"']/.test(value) ||
      /^[\d.eE+-]+$/.test(value)
    ) {
      const escaped = value.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
      return `"${escaped}"`;
    }
    return value;
  }
  if (Array.isArray(value)) {
    const inner = value.map((v) => yamlSerialiseValue(v)).join(', ');
    return `[${inner}]`;
  }
  // Fallback: JSON
  return JSON.stringify(value);
}

/**
 * Apply a single update to a line array, modifying it in-place and returning
 * the (possibly resized) array.
 */
function applySingleUpdate(lines: string[], keys: string[], newValue: unknown): string[] {
  if (keys.length === 0) throw new Error('Empty key path');

  let currentAfter = 0;
  let indentLevel = 0;
  let targetLineIdx: number | null = null;

  for (let i = 0; i < keys.length; i++) {
    const indent = indentLevel * 4;
    targetLineIdx = findKeyLine(lines, keys[i], indent, currentAfter);
    if (targetLineIdx === null) {
      throw new Error(`Key '${keys[i]}' not found at indent ${indent} (path: ${keys.join('.')})`);
    }
    if (i < keys.length - 1) {
      currentAfter = targetLineIdx + 1;
      indentLevel += 1;
    }
  }

  if (targetLineIdx === null) throw new Error('Unreachable');

  const line = lines[targetLineIdx];
  const lastKey = keys[keys.length - 1];
  const indentStr = ' '.repeat((keys.length - 1) * 4);

  // Check for block scalar (| or >)
  const blockRe = new RegExp(`^${escapeRegExp(indentStr)}${escapeRegExp(lastKey)}\\s*:\\s*[|>]`);
  if (blockRe.test(line)) {
    const serialised = yamlSerialiseValue(newValue);
    const result = [...lines];
    result[targetLineIdx] = `${indentStr}${lastKey}: ${serialised}`;
    const blockIndent = indentStr.length + 4;
    let idx = targetLineIdx + 1;
    while (idx < result.length) {
      const cur = result[idx];
      const stripped = cur.trim();
      if (
        stripped === '' ||
        (cur.length > cur.trimStart().length && cur.length - cur.trimStart().length >= blockIndent)
      ) {
        result.splice(idx, 1);
      } else {
        break;
      }
    }
    return result;
  }

  // Standard single-line value replacement
  const pattern = new RegExp(
    `^(${escapeRegExp(indentStr)}${escapeRegExp(lastKey)}\\s*:\\s*)(.*?)(\\s*#.*)?$`,
  );
  const m = pattern.exec(line);
  if (!m) {
    throw new Error(`Could not parse line for key '${lastKey}': ${JSON.stringify(line)}`);
  }

  const prefix = m[1];
  const inlineComment = m[3] ?? '';
  const serialised = yamlSerialiseValue(newValue);

  const result = [...lines];
  result[targetLineIdx] = `${prefix}${serialised}${inlineComment}`;
  return result;
}

/**
 * Apply multiple updates to raw YAML text, preserving comments and formatting.
 *
 * Returns the updated YAML text.
 */
export function applyConfigUpdates(yamlText: string, updates: Record<string, unknown>): string {
  let lines = yamlText.split('\n');

  for (const [dottedPath, newValue] of Object.entries(updates)) {
    const keys = dottedPath.split('.');
    lines = applySingleUpdate(lines, keys, newValue);
  }

  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// Local override merging
// ---------------------------------------------------------------------------

/**
 * Build a flat map of dotted paths → values from a parsed YAML object.
 * Only includes leaf values (not dict nodes).
 */
export function flattenYamlToOverrides(
  parsed: Record<string, unknown>,
  prefix = '',
): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(parsed)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
      Object.assign(result, flattenYamlToOverrides(value as Record<string, unknown>, path));
    } else {
      result[path] = value;
    }
  }
  return result;
}

/**
 * Build a sparse YAML string containing only the given overrides.
 *
 * Groups by top-level section so the output looks like:
 * ```yaml
 * section:
 *     key: value
 * ```
 */
export function buildSparseYaml(overrides: Record<string, unknown>): string {
  if (Object.keys(overrides).length === 0) return '';

  // Group by section path structure
  const grouped: Record<string, Record<string, unknown>> = {};
  for (const [dottedPath, value] of Object.entries(overrides)) {
    const keys = dottedPath.split('.');
    const topKey = keys[0];
    if (!grouped[topKey]) grouped[topKey] = {};

    if (keys.length === 2) {
      grouped[topKey][keys[1]] = value;
    } else if (keys.length === 3) {
      // subsection: section.subsection.key
      if (!grouped[topKey][keys[1]]) grouped[topKey][keys[1]] = {};
      (grouped[topKey][keys[1]] as Record<string, unknown>)[keys[2]] = value;
    }
  }

  // Serialise to YAML text with 4-space indent
  return YAML.stringify(grouped, { indent: 4 }).trimEnd() + '\n';
}

/**
 * Merge flat dotted-path overrides into an existing YAML string (or an empty
 * document), returning the merged YAML text.
 *
 * Unlike `buildSparseYaml`, this function preserves every key that was already
 * in `existingYaml` so that successive saves don't silently discard settings
 * written in previous sessions.
 */
export function mergeConfigUpdates(
  existingYaml: string | null,
  updates: Record<string, unknown>,
): string {
  // Start from whatever is already on disk.
  let merged: Record<string, unknown> = {};
  if (existingYaml) {
    try {
      const parsed = YAML.parse(existingYaml) as Record<string, unknown> | null;
      if (parsed && typeof parsed === 'object') {
        merged = parsed;
      }
    } catch {
      // Malformed existing YAML — start with an empty base.
    }
  }

  // Apply the flat dotted-path updates on top, creating nested objects as needed.
  for (const [dottedPath, value] of Object.entries(updates)) {
    const keys = dottedPath.split('.');
    let obj = merged;
    for (let i = 0; i < keys.length - 1; i++) {
      if (typeof obj[keys[i]] !== 'object' || obj[keys[i]] === null) {
        obj[keys[i]] = {};
      }
      obj = obj[keys[i]] as Record<string, unknown>;
    }
    obj[keys[keys.length - 1]] = value;
  }

  if (Object.keys(merged).length === 0) return '';
  return YAML.stringify(merged, { indent: 4 }).trimEnd() + '\n';
}
