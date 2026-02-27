#!/usr/bin/env node

/**
 * check-doc-freshness.mjs
 *
 * Lightweight pre-commit warning tool that checks whether README sections
 * are staged alongside their tracked source files.
 *
 * Reads `.doc-freshness.yaml` from the repo root and compares staged files
 * against declared source patterns. Always exits 0 (warning-only).
 *
 * Usage:
 *   node build/scripts/check-doc-freshness.mjs
 */

import { execSync } from "node:child_process";
import { readFileSync, existsSync } from "node:fs";
import { resolve} from "node:path";

// ---------------------------------------------------------------------------
// Minimal YAML parser (handles the flat structure of .doc-freshness.yaml
// without requiring js-yaml). Falls back to js-yaml if available.
// ---------------------------------------------------------------------------

/**
 * Try to parse YAML using js-yaml (available transitively via node_modules).
 * If unavailable, fall back to a minimal hand-rolled parser.
 */
async function parseYaml(content) {
  try {
    const yaml = await import("js-yaml");
    return yaml.default?.load
      ? yaml.default.load(content)
      : yaml.load(content);
  } catch {
    // js-yaml not available — fall back to minimal parser
  }
  return minimalYamlParse(content);
}

/**
 * Minimal YAML parser sufficient for .doc-freshness.yaml structure.
 * Handles nested mappings and sequences with string values only.
 */
function minimalYamlParse(content) {
  const lines = content.split("\n");
  const root = {};
  let currentDoc = null;
  let currentSection = null;
  let inSources = false;

  for (const raw of lines) {
    const line = raw.replace(/\r$/, "");
    if (line.trim() === "" || line.trim().startsWith("#")) continue;

    // Top-level key: value
    const topMatch = line.match(/^(\w+):\s*(.+)?$/);
    if (topMatch) {
      const [, key, val] = topMatch;
      if (val && val.trim()) {
        root[key] = isNaN(val.trim()) ? val.trim() : Number(val.trim());
      } else {
        root[key] = [];
      }
      currentDoc = null;
      currentSection = null;
      inSources = false;
      continue;
    }

    // Document list item: - path: X
    const docMatch = line.match(/^\s+-\s+path:\s*(.+)$/);
    if (docMatch) {
      currentDoc = { path: docMatch[1].trim(), sections: [] };
      if (Array.isArray(root.documents)) {
        root.documents.push(currentDoc);
      }
      currentSection = null;
      inSources = false;
      continue;
    }

    // Section list item: - anchor: X
    const sectionMatch = line.match(/^\s+-\s+anchor:\s*"?([^"]+)"?$/);
    if (sectionMatch && currentDoc) {
      currentSection = {
        anchor: sectionMatch[1].trim(),
        label: "",
        sources: [],
      };
      currentDoc.sections.push(currentSection);
      inSources = false;
      continue;
    }

    // Label
    const labelMatch = line.match(/^\s+label:\s*"?([^"]+)"?$/);
    if (labelMatch && currentSection) {
      currentSection.label = labelMatch[1].trim();
      continue;
    }

    // Sources key
    if (line.match(/^\s+sources:\s*$/)) {
      inSources = true;
      continue;
    }

    // Source entry
    const sourceMatch = line.match(/^\s+-\s+(.+)$/);
    if (sourceMatch && inSources && currentSection) {
      currentSection.sources.push(sourceMatch[1].trim());
      continue;
    }
  }

  return root;
}

// ---------------------------------------------------------------------------
// Glob matching (minimal, supports * and ** and ? patterns)
// ---------------------------------------------------------------------------

/**
 * Convert a simple glob pattern to a RegExp.
 * Supports: *, **, ?
 */
function globToRegex(pattern) {
  let re = "";
  let i = 0;
  while (i < pattern.length) {
    const c = pattern[i];
    if (c === "*") {
      if (pattern[i + 1] === "*") {
        // **/ matches any number of directories
        if (pattern[i + 2] === "/") {
          re += "(?:.+/)?";
          i += 3;
        } else {
          re += ".*";
          i += 2;
        }
      } else {
        re += "[^/]*";
        i++;
      }
    } else if (c === "?") {
      re += "[^/]";
      i++;
    } else if (c === ".") {
      re += "\\.";
      i++;
    } else {
      re += c;
      i++;
    }
  }
  return new RegExp("^" + re + "$");
}

/**
 * Test whether a relative file path matches a glob pattern.
 */
function matchesGlob(filePath, pattern) {
  return globToRegex(pattern).test(filePath);
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  const repoRoot = execSync("git rev-parse --show-toplevel", {
    encoding: "utf8",
  }).trim();

  const manifestPath = resolve(repoRoot, ".doc-freshness.yaml");
  if (!existsSync(manifestPath)) {
    console.log("ℹ️  No .doc-freshness.yaml found — skipping freshness check.");
    process.exit(0);
  }

  const content = readFileSync(manifestPath, "utf8");
  const manifest = await parseYaml(content);

  if (!manifest || !Array.isArray(manifest.documents)) {
    console.log("ℹ️  .doc-freshness.yaml has no documents — skipping.");
    process.exit(0);
  }

  // Get staged files (relative to repo root)
  let stagedFiles;
  try {
    const raw = execSync("git diff --cached --name-only", {
      encoding: "utf8",
      cwd: repoRoot,
    }).trim();
    stagedFiles = raw ? raw.split("\n").map((f) => f.trim()) : [];
  } catch {
    // Not in a git repo or no staged files
    stagedFiles = [];
  }

  if (stagedFiles.length === 0) {
    // Nothing staged — nothing to warn about
    process.exit(0);
  }

  const stagedSet = new Set(stagedFiles);

  let warnings = 0;

  for (const doc of manifest.documents) {
    const docPath = doc.path;
    const docIsStaged = stagedSet.has(docPath);

    for (const section of doc.sections || []) {
      // Check if any source in this section is staged
      const matchedSources = [];

      for (const sourcePattern of section.sources || []) {
        for (const stagedFile of stagedFiles) {
          if (matchesGlob(stagedFile, sourcePattern)) {
            matchedSources.push(stagedFile);
          }
        }
      }

      if (matchedSources.length > 0 && !docIsStaged) {
        warnings++;
        const label = section.label || section.anchor;
        console.log(
          `⚠️  ${docPath} §${label} may be stale — source file(s) staged but README is not:`,
        );
        for (const src of matchedSources) {
          console.log(`     • ${src}`);
        }
      }
    }
  }

  if (warnings > 0) {
    console.log(
      `\n📝 ${warnings} section(s) may need a README update. Stage the README(s) to silence these warnings.`,
    );
  }

  // Always exit 0 — this is a warning-only check
  process.exit(0);
}

main().catch((err) => {
  console.error("doc-freshness check failed:", err.message);
  process.exit(0); // Never block commits
});
