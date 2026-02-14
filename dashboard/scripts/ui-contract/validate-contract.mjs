#!/usr/bin/env node
import fs from 'node:fs/promises';
import path from 'node:path';
import Ajv2020 from 'ajv/dist/2020.js';
import YAML from 'yaml';
import {
  BASELINE_PATH,
  CONTRACT_PATH,
  PROJECT_ROOT,
  SCHEMA_PATH,
  extractFacts,
  extractSemverParts,
  setDiff,
  sha256,
  writeJson,
} from './shared.mjs';

function deepEqual(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function asObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function trimMultiline(value) {
  return String(value || '').replace(/\r\n/g, '\n').trim();
}

async function loadContract(contractPath) {
  const raw = await fs.readFile(contractPath, 'utf8');
  const parsed = YAML.parse(raw);
  return { raw, parsed };
}

async function loadSchema(schemaPath) {
  const raw = await fs.readFile(schemaPath, 'utf8');
  return JSON.parse(raw);
}

function normalizeContractForComparison(contract) {
  const foundation = asObject(contract.foundation);
  const tokens = asObject(foundation.tokens);
  const motion = asObject(tokens.motion);

  return {
    tailwind: {
      dark_mode: foundation.tailwind?.dark_mode ?? null,
      font_family_sans: asArray(foundation.tailwind?.font_family_sans),
      accent_scale: asObject(foundation.tailwind?.accent_scale),
      glass_scale: asObject(foundation.tailwind?.glass_scale),
      backdrop_blur_scale: asObject(foundation.tailwind?.backdrop_blur_scale),
    },
    global_css: {
      body: trimMultiline(contract.global_behaviors?.css_blocks?.body),
      selection: trimMultiline(contract.global_behaviors?.css_blocks?.selection),
      moz_selection: trimMultiline(contract.global_behaviors?.css_blocks?.moz_selection),
      selectable_text: trimMultiline(contract.global_behaviors?.css_blocks?.selectable_text),
      custom_scrollbar_root: trimMultiline(contract.global_behaviors?.css_blocks?.custom_scrollbar_root),
      custom_scrollbar_track: trimMultiline(contract.global_behaviors?.css_blocks?.custom_scrollbar_track),
      custom_scrollbar_thumb: trimMultiline(contract.global_behaviors?.css_blocks?.custom_scrollbar_thumb),
      custom_scrollbar_thumb_hover: trimMultiline(contract.global_behaviors?.css_blocks?.custom_scrollbar_thumb_hover),
      custom_scrollbar_corner: trimMultiline(contract.global_behaviors?.css_blocks?.custom_scrollbar_corner),
    },
    utility_allowlist: {
      exact_classes: asArray(contract.utility_allowlist?.exact_classes),
      arbitrary_classes: asArray(contract.utility_allowlist?.arbitrary_classes),
    },
    tokens: {
      colors_literal_palette: asArray(tokens.colors?.literal_palette),
      blur_backdrop: asArray(tokens.blur_levels?.backdrop),
      blur_filter: asArray(tokens.blur_levels?.filter),
      shadow_classes: asArray(tokens.shadow_levels?.classes),
      motion_duration_ms: asArray(motion.duration_ms),
      motion_easings: asArray(motion.easings),
      motion_keyframes: asArray(motion.keyframes),
      motion_animation_classes: asArray(motion.animation_classes),
      motion_animation_strings: asArray(motion.animation_strings),
      radii_classes: asArray(tokens.radii?.classes),
      z_index_classes: asArray(tokens.z_index_levels?.classes),
      spacing_arbitrary: asArray(tokens.spacing_and_size_constraints?.arbitrary_classes),
      status_allowed: asArray(tokens.status_states?.allowed),
    },
    inline_style: {
      allowed_properties: asArray(contract.inline_style_allowlist?.allowed_properties),
      allowed_literals: asArray(contract.inline_style_allowlist?.allowed_literals),
      keyframes: asArray(contract.inline_style_allowlist?.keyframes),
      animation_strings: asArray(contract.inline_style_allowlist?.animation_strings),
      cubic_beziers: asArray(contract.inline_style_allowlist?.cubic_beziers),
    },
    components: {
      names: Object.keys(asObject(contract.component_contracts)).sort((a, b) => a.localeCompare(b)),
      contracts: asObject(contract.component_contracts),
    },
  };
}

function normalizeFactsForComparison(facts) {
  return {
    tailwind: {
      dark_mode: facts.tailwind?.dark_mode ?? null,
      font_family_sans: asArray(facts.tailwind?.extend?.fontFamily?.sans),
      accent_scale: asObject(facts.tailwind?.extend?.colors?.accent),
      glass_scale: asObject(facts.tailwind?.extend?.colors?.glass),
      backdrop_blur_scale: asObject(facts.tailwind?.extend?.backdropBlur),
    },
    global_css: {
      body: trimMultiline(facts.global_css?.body),
      selection: trimMultiline(facts.global_css?.selection),
      moz_selection: trimMultiline(facts.global_css?.moz_selection),
      selectable_text: trimMultiline(facts.global_css?.selectable_text),
      custom_scrollbar_root: trimMultiline(facts.global_css?.custom_scrollbar?.root),
      custom_scrollbar_track: trimMultiline(facts.global_css?.custom_scrollbar?.track),
      custom_scrollbar_thumb: trimMultiline(facts.global_css?.custom_scrollbar?.thumb),
      custom_scrollbar_thumb_hover: trimMultiline(facts.global_css?.custom_scrollbar?.thumb_hover),
      custom_scrollbar_corner: trimMultiline(facts.global_css?.custom_scrollbar?.corner),
    },
    utility_allowlist: {
      exact_classes: asArray(facts.utilities?.exact_classes),
      arbitrary_classes: asArray(facts.utilities?.arbitrary_classes),
    },
    tokens: {
      colors_literal_palette: asArray(facts.tokens?.colors?.literal_palette),
      blur_backdrop: asArray(facts.tokens?.blur_levels?.backdrop),
      blur_filter: asArray(facts.tokens?.blur_levels?.filter),
      shadow_classes: asArray(facts.tokens?.shadow_levels?.classes),
      motion_duration_ms: asArray(facts.tokens?.motion?.duration_ms),
      motion_easings: asArray(facts.tokens?.motion?.easings),
      motion_keyframes: asArray(facts.tokens?.motion?.keyframes),
      motion_animation_classes: asArray(facts.tokens?.motion?.animation_classes),
      motion_animation_strings: asArray(facts.tokens?.motion?.animation_strings),
      radii_classes: asArray(facts.tokens?.radii?.classes),
      z_index_classes: asArray(facts.tokens?.z_index_levels?.classes),
      spacing_arbitrary: asArray(facts.tokens?.spacing_and_size_constraints?.arbitrary_classes),
      status_allowed: asArray(facts.tokens?.status_states?.allowed),
    },
    inline_style: {
      allowed_properties: asArray(facts.inline_style?.allowed_properties),
      allowed_literals: asArray(facts.inline_style?.allowed_literals),
      keyframes: asArray(facts.inline_style?.keyframes),
      animation_strings: asArray(facts.inline_style?.animation_strings),
      cubic_beziers: asArray(facts.inline_style?.cubic_beziers),
    },
    components: {
      names: asArray(facts.components?.names),
      files: asObject(facts.components?.files),
    },
  };
}

function buildSemanticDiff(contract, facts) {
  const contractView = normalizeContractForComparison(contract);
  const factsView = normalizeFactsForComparison(facts);

  const setComparisons = {
    utility_exact_classes: setDiff(contractView.utility_allowlist.exact_classes, factsView.utility_allowlist.exact_classes),
    utility_arbitrary_classes: setDiff(contractView.utility_allowlist.arbitrary_classes, factsView.utility_allowlist.arbitrary_classes),
    token_colors_literal_palette: setDiff(contractView.tokens.colors_literal_palette, factsView.tokens.colors_literal_palette),
    token_blur_backdrop: setDiff(contractView.tokens.blur_backdrop, factsView.tokens.blur_backdrop),
    token_blur_filter: setDiff(contractView.tokens.blur_filter, factsView.tokens.blur_filter),
    token_shadow_classes: setDiff(contractView.tokens.shadow_classes, factsView.tokens.shadow_classes),
    token_motion_duration_ms: setDiff(contractView.tokens.motion_duration_ms.map(String), factsView.tokens.motion_duration_ms.map(String)),
    token_motion_easings: setDiff(contractView.tokens.motion_easings, factsView.tokens.motion_easings),
    token_motion_keyframes: setDiff(contractView.tokens.motion_keyframes, factsView.tokens.motion_keyframes),
    token_motion_animation_classes: setDiff(contractView.tokens.motion_animation_classes, factsView.tokens.motion_animation_classes),
    token_motion_animation_strings: setDiff(contractView.tokens.motion_animation_strings, factsView.tokens.motion_animation_strings),
    token_radii_classes: setDiff(contractView.tokens.radii_classes, factsView.tokens.radii_classes),
    token_z_index_classes: setDiff(contractView.tokens.z_index_classes, factsView.tokens.z_index_classes),
    token_spacing_arbitrary: setDiff(contractView.tokens.spacing_arbitrary, factsView.tokens.spacing_arbitrary),
    token_status_allowed: setDiff(contractView.tokens.status_allowed, factsView.tokens.status_allowed),
    inline_allowed_properties: setDiff(contractView.inline_style.allowed_properties, factsView.inline_style.allowed_properties),
    inline_allowed_literals: setDiff(contractView.inline_style.allowed_literals, factsView.inline_style.allowed_literals),
    inline_keyframes: setDiff(contractView.inline_style.keyframes, factsView.inline_style.keyframes),
    inline_animation_strings: setDiff(contractView.inline_style.animation_strings, factsView.inline_style.animation_strings),
    inline_cubic_beziers: setDiff(contractView.inline_style.cubic_beziers, factsView.inline_style.cubic_beziers),
    component_coverage: setDiff(contractView.components.names, factsView.components.names),
  };

  const tailwindComparisons = {
    dark_mode: {
      contract: contractView.tailwind.dark_mode,
      extracted: factsView.tailwind.dark_mode,
      equal: contractView.tailwind.dark_mode === factsView.tailwind.dark_mode,
    },
    font_family_sans: {
      contract: contractView.tailwind.font_family_sans,
      extracted: factsView.tailwind.font_family_sans,
      equal: deepEqual(contractView.tailwind.font_family_sans, factsView.tailwind.font_family_sans),
    },
    accent_scale: {
      contract: contractView.tailwind.accent_scale,
      extracted: factsView.tailwind.accent_scale,
      equal: deepEqual(contractView.tailwind.accent_scale, factsView.tailwind.accent_scale),
    },
    glass_scale: {
      contract: contractView.tailwind.glass_scale,
      extracted: factsView.tailwind.glass_scale,
      equal: deepEqual(contractView.tailwind.glass_scale, factsView.tailwind.glass_scale),
    },
    backdrop_blur_scale: {
      contract: contractView.tailwind.backdrop_blur_scale,
      extracted: factsView.tailwind.backdrop_blur_scale,
      equal: deepEqual(contractView.tailwind.backdrop_blur_scale, factsView.tailwind.backdrop_blur_scale),
    },
  };

  const globalCssComparisons = {
    body: {
      contract: contractView.global_css.body,
      extracted: factsView.global_css.body,
      equal: contractView.global_css.body === factsView.global_css.body,
    },
    selection: {
      contract: contractView.global_css.selection,
      extracted: factsView.global_css.selection,
      equal: contractView.global_css.selection === factsView.global_css.selection,
    },
    moz_selection: {
      contract: contractView.global_css.moz_selection,
      extracted: factsView.global_css.moz_selection,
      equal: contractView.global_css.moz_selection === factsView.global_css.moz_selection,
    },
    selectable_text: {
      contract: contractView.global_css.selectable_text,
      extracted: factsView.global_css.selectable_text,
      equal: contractView.global_css.selectable_text === factsView.global_css.selectable_text,
    },
    custom_scrollbar_root: {
      contract: contractView.global_css.custom_scrollbar_root,
      extracted: factsView.global_css.custom_scrollbar_root,
      equal: contractView.global_css.custom_scrollbar_root === factsView.global_css.custom_scrollbar_root,
    },
    custom_scrollbar_track: {
      contract: contractView.global_css.custom_scrollbar_track,
      extracted: factsView.global_css.custom_scrollbar_track,
      equal: contractView.global_css.custom_scrollbar_track === factsView.global_css.custom_scrollbar_track,
    },
    custom_scrollbar_thumb: {
      contract: contractView.global_css.custom_scrollbar_thumb,
      extracted: factsView.global_css.custom_scrollbar_thumb,
      equal: contractView.global_css.custom_scrollbar_thumb === factsView.global_css.custom_scrollbar_thumb,
    },
    custom_scrollbar_thumb_hover: {
      contract: contractView.global_css.custom_scrollbar_thumb_hover,
      extracted: factsView.global_css.custom_scrollbar_thumb_hover,
      equal: contractView.global_css.custom_scrollbar_thumb_hover === factsView.global_css.custom_scrollbar_thumb_hover,
    },
    custom_scrollbar_corner: {
      contract: contractView.global_css.custom_scrollbar_corner,
      extracted: factsView.global_css.custom_scrollbar_corner,
      equal: contractView.global_css.custom_scrollbar_corner === factsView.global_css.custom_scrollbar_corner,
    },
  };

  const componentFileMismatches = [];
  for (const componentName of factsView.components.names) {
    const contractEntry = contractView.components.contracts[componentName];
    if (!contractEntry) {
      continue;
    }
    const expectedFile = factsView.components.files[componentName];
    const contractFile = contractEntry.file;
    if (expectedFile && contractFile !== expectedFile) {
      componentFileMismatches.push({
        component: componentName,
        expected_file: expectedFile,
        contract_file: contractFile,
      });
    }
  }

  return {
    set_comparisons: setComparisons,
    tailwind: tailwindComparisons,
    global_css: globalCssComparisons,
    component_file_mismatches: componentFileMismatches,
  };
}

function collectSemanticIssues(diff) {
  const issues = [];

  for (const [key, comparison] of Object.entries(diff.set_comparisons)) {
    if (comparison.missing_in_contract.length > 0 || comparison.stale_in_contract.length > 0) {
      issues.push({
        code: 'set_mismatch',
        severity: 'error',
        path: key,
        message: `Closed-set mismatch for ${key}.`,
        details: comparison,
      });
    }
  }

  for (const [key, comparison] of Object.entries(diff.tailwind)) {
    if (!comparison.equal) {
      issues.push({
        code: 'tailwind_mismatch',
        severity: 'error',
        path: `foundation.tailwind.${key}`,
        message: `Tailwind contract mismatch for ${key}.`,
        details: comparison,
      });
    }
  }

  for (const [key, comparison] of Object.entries(diff.global_css)) {
    if (!comparison.equal) {
      issues.push({
        code: 'global_css_mismatch',
        severity: 'error',
        path: `global_behaviors.css_blocks.${key}`,
        message: `Global CSS contract mismatch for ${key}.`,
        details: comparison,
      });
    }
  }

  for (const mismatch of diff.component_file_mismatches) {
    issues.push({
      code: 'component_file_mismatch',
      severity: 'error',
      path: `component_contracts.${mismatch.component}.file`,
      message: `Component file mapping mismatch for ${mismatch.component}.`,
      details: mismatch,
    });
  }

  return issues;
}

async function checkBaseline({ baselinePath, contractRaw, specVersion, updateBaseline }) {
  const contractHash = sha256(contractRaw);
  const issues = [];
  const warnings = [];

  const versionParts = extractSemverParts(specVersion);
  if (!versionParts) {
    issues.push({
      code: 'invalid_semver',
      severity: 'error',
      path: 'meta.spec_version',
      message: 'Contract spec_version must be strict semver (X.Y.Z).',
      details: { spec_version: specVersion },
    });
    return { issues, warnings, contractHash };
  }

  let baseline = null;
  try {
    const raw = await fs.readFile(baselinePath, 'utf8');
    baseline = JSON.parse(raw);
  } catch (error) {
    if (error.code === 'ENOENT') {
      issues.push({
        code: 'missing_baseline',
        severity: 'error',
        path: path.relative(PROJECT_ROOT, baselinePath),
        message: 'Baseline file is missing. Run validator with --update-baseline once to initialize.',
      });
      if (updateBaseline) {
        const initialized = {
          spec_version: specVersion,
          contract_sha256: contractHash,
          updated_at: new Date().toISOString(),
        };
        await writeJson(baselinePath, initialized);
        issues.length = 0;
        warnings.push({
          code: 'baseline_initialized',
          severity: 'warning',
          path: path.relative(PROJECT_ROOT, baselinePath),
          message: 'Baseline file initialized with current contract hash.',
        });
      }
      return { issues, warnings, contractHash };
    }
    throw error;
  }

  if (baseline.contract_sha256 !== contractHash) {
    if (baseline.spec_version === specVersion) {
      issues.push({
        code: 'semver_bump_required',
        severity: 'error',
        path: 'meta.spec_version',
        message: 'Contract changed but spec_version did not bump.',
        details: {
          baseline_spec_version: baseline.spec_version,
          current_spec_version: specVersion,
        },
      });
    } else {
      warnings.push({
        code: 'spec_version_changed',
        severity: 'warning',
        path: 'meta.spec_version',
        message: 'Contract hash changed with a new spec_version. Update baseline to lock this revision.',
        details: {
          baseline_spec_version: baseline.spec_version,
          current_spec_version: specVersion,
        },
      });
    }

    if (updateBaseline) {
      const updated = {
        spec_version: specVersion,
        contract_sha256: contractHash,
        updated_at: new Date().toISOString(),
      };
      await writeJson(baselinePath, updated);
      warnings.push({
        code: 'baseline_updated',
        severity: 'warning',
        path: path.relative(PROJECT_ROOT, baselinePath),
        message: 'Baseline updated to current contract hash.',
      });
    }
  }

  return { issues, warnings, contractHash };
}

export async function createValidationReport({
  contractPath = CONTRACT_PATH,
  schemaPath = SCHEMA_PATH,
  factsOverride = null,
  baselinePath = BASELINE_PATH,
  updateBaseline = false,
} = {}) {
  const { raw: contractRaw, parsed: contract } = await loadContract(contractPath);
  const schema = await loadSchema(schemaPath);

  const ajv = new Ajv2020({ allErrors: true, strict: false });
  const validateSchema = ajv.compile(schema);
  const schemaValid = validateSchema(contract);

  const report = {
    ok: false,
    schema_valid: Boolean(schemaValid),
    semantic_valid: false,
    issues: [],
    warnings: [],
    summary: {
      contract_path: path.relative(PROJECT_ROOT, contractPath),
      schema_path: path.relative(PROJECT_ROOT, schemaPath),
    },
    semantic_diff: null,
  };

  if (!schemaValid) {
    for (const err of validateSchema.errors ?? []) {
      report.issues.push({
        code: 'schema_validation_failed',
        severity: 'error',
        path: err.instancePath || '(root)',
        message: err.message,
        details: err,
      });
    }
    report.ok = false;
    return report;
  }

  const facts = factsOverride || (await extractFacts());
  const semanticDiff = buildSemanticDiff(contract, facts);
  report.semantic_diff = semanticDiff;
  report.issues.push(...collectSemanticIssues(semanticDiff));

  const baselineResult = await checkBaseline({
    baselinePath,
    contractRaw,
    specVersion: contract.meta.spec_version,
    updateBaseline,
  });
  report.issues.push(...baselineResult.issues);
  report.warnings.push(...baselineResult.warnings);
  report.summary.contract_sha256 = baselineResult.contractHash;
  report.summary.spec_version = contract.meta.spec_version;

  report.semantic_valid = report.issues.length === 0;
  report.ok = report.schema_valid && report.semantic_valid;

  return report;
}

function parseArgs(argv) {
  const args = {
    contract: CONTRACT_PATH,
    schema: SCHEMA_PATH,
    facts: null,
    json: false,
    updateBaseline: false,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (token === '--contract' && argv[i + 1]) {
      args.contract = path.resolve(argv[i + 1]);
      i += 1;
      continue;
    }
    if (token === '--schema' && argv[i + 1]) {
      args.schema = path.resolve(argv[i + 1]);
      i += 1;
      continue;
    }
    if (token === '--facts' && argv[i + 1]) {
      args.facts = path.resolve(argv[i + 1]);
      i += 1;
      continue;
    }
    if (token === '--json') {
      args.json = true;
      continue;
    }
    if (token === '--update-baseline') {
      args.updateBaseline = true;
    }
  }

  return args;
}

async function readFactsIfProvided(factsPath) {
  if (!factsPath) {
    return null;
  }
  const raw = await fs.readFile(factsPath, 'utf8');
  return JSON.parse(raw);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const factsOverride = await readFactsIfProvided(args.facts);

  const report = await createValidationReport({
    contractPath: args.contract,
    schemaPath: args.schema,
    factsOverride,
    updateBaseline: args.updateBaseline,
  });

  if (args.json) {
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  } else {
    const lines = [];
    lines.push(`Contract: ${report.summary.contract_path}`);
    lines.push(`Schema:   ${report.summary.schema_path}`);
    lines.push(`Version:  ${report.summary.spec_version}`);
    lines.push(`SHA256:   ${report.summary.contract_sha256}`);
    lines.push(`Schema Valid:   ${report.schema_valid ? 'yes' : 'no'}`);
    lines.push(`Semantic Valid: ${report.semantic_valid ? 'yes' : 'no'}`);

    if (report.warnings.length > 0) {
      lines.push('Warnings:');
      for (const warning of report.warnings) {
        lines.push(`  - [${warning.code}] ${warning.path}: ${warning.message}`);
      }
    }

    if (report.issues.length > 0) {
      lines.push('Issues:');
      for (const issue of report.issues) {
        lines.push(`  - [${issue.code}] ${issue.path}: ${issue.message}`);
      }
    }

    process.stdout.write(`${lines.join('\n')}\n`);
  }

  process.exit(report.ok ? 0 : 1);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((error) => {
    process.stderr.write(`validate-contract failed: ${error.stack || error.message}\n`);
    process.exit(1);
  });
}

export { buildSemanticDiff };
