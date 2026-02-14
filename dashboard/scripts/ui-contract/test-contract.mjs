#!/usr/bin/env node
import fs from 'node:fs/promises';
import path from 'node:path';
import YAML from 'yaml';
import { createValidationReport } from './validate-contract.mjs';
import { BASELINE_PATH, CONTRACT_PATH, PROJECT_ROOT, extractFacts } from './shared.mjs';

const TMP_DIR = path.join(PROJECT_ROOT, 'scripts', 'ui-contract', 'fixtures', '.tmp');
const SCHEMA_FAIL_FIXTURE = path.join(
  PROJECT_ROOT,
  'scripts',
  'ui-contract',
  'fixtures',
  'schema-fail-missing-component-contracts.yaml'
);

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function hasIssue(report, code, pathIncludes = '') {
  return report.issues.some(
    (issue) => issue.code === code && (!pathIncludes || String(issue.path || '').includes(pathIncludes))
  );
}

async function writeTempFile(fileName, content) {
  await fs.mkdir(TMP_DIR, { recursive: true });
  const fullPath = path.join(TMP_DIR, fileName);
  await fs.writeFile(fullPath, content, 'utf8');
  return fullPath;
}

async function readYaml(filePath) {
  const raw = await fs.readFile(filePath, 'utf8');
  return YAML.parse(raw);
}

async function main() {
  const failures = [];
  const checks = [];

  const expect = (condition, title, details = '') => {
    checks.push(title);
    if (!condition) {
      failures.push(`${title}${details ? ` -> ${details}` : ''}`);
    }
  };

  const baseFacts = await extractFacts();

  // 1. Schema pass: canonical contract should validate.
  const schemaPass = await createValidationReport({ factsOverride: baseFacts });
  expect(schemaPass.schema_valid === true, 'Schema pass validates canonical contract');
  expect(schemaPass.ok === true, 'Canonical contract passes semantic validation');

  // 2. Schema fail: fixture missing required contract fields.
  const schemaFail = await createValidationReport({
    contractPath: SCHEMA_FAIL_FIXTURE,
    factsOverride: baseFacts,
    baselinePath: path.join(TMP_DIR, 'schema-fail-baseline.json'),
  });
  expect(schemaFail.schema_valid === false, 'Schema fail catches missing required fields');

  // 3. Drift fail: new color utility class should fail closed-set.
  const factsColorDrift = clone(baseFacts);
  factsColorDrift.utilities.exact_classes.push('text-fuchsia-300');
  factsColorDrift.utilities.exact_classes.sort((a, b) => a.localeCompare(b));
  const colorDrift = await createValidationReport({ factsOverride: factsColorDrift });
  expect(hasIssue(colorDrift, 'set_mismatch', 'utility_exact_classes'), 'Drift fail for new color utility class');

  // 4. Drift fail: new arbitrary shadow token should fail.
  const factsShadowDrift = clone(baseFacts);
  factsShadowDrift.utilities.arbitrary_classes.push('shadow-[0_0_99px_rgba(0,0,0,1)]');
  factsShadowDrift.utilities.arbitrary_classes.sort((a, b) => a.localeCompare(b));
  const shadowDrift = await createValidationReport({ factsOverride: factsShadowDrift });
  expect(hasIssue(shadowDrift, 'set_mismatch', 'utility_arbitrary_classes'), 'Drift fail for arbitrary shadow token');

  // 5. Drift fail: changed selection styling should fail global CSS check.
  const factsSelectionDrift = clone(baseFacts);
  factsSelectionDrift.global_css.selection = factsSelectionDrift.global_css.selection.replace('#22d3ee', '#ff00aa');
  const selectionDrift = await createValidationReport({ factsOverride: factsSelectionDrift });
  expect(hasIssue(selectionDrift, 'global_css_mismatch', 'selection'), 'Drift fail for global selection styling change');

  // 6. Drift fail: unregistered portal z-index should fail.
  const factsZDrift = clone(baseFacts);
  factsZDrift.tokens.z_index_levels.classes.push('z-[12345]');
  factsZDrift.tokens.z_index_levels.classes.sort((a, b) => a.localeCompare(b));
  factsZDrift.utilities.arbitrary_classes.push('z-[12345]');
  factsZDrift.utilities.arbitrary_classes.sort((a, b) => a.localeCompare(b));
  const zDrift = await createValidationReport({ factsOverride: factsZDrift });
  expect(hasIssue(zDrift, 'set_mismatch', 'token_z_index_classes'), 'Drift fail for unregistered portal z-index');

  // 7. Drift fail: missing component contract coverage should fail.
  const factsComponentDrift = clone(baseFacts);
  factsComponentDrift.components.names.push('GhostComponent');
  factsComponentDrift.components.names.sort((a, b) => a.localeCompare(b));
  factsComponentDrift.components.files.GhostComponent = 'components/GhostComponent.tsx';
  const componentDrift = await createValidationReport({ factsOverride: factsComponentDrift });
  expect(hasIssue(componentDrift, 'set_mismatch', 'component_coverage'), 'Drift fail for missing component contract coverage');

  // 8. Pass case: non-style facts should not fail style contract.
  const factsNonStyle = clone(baseFacts);
  factsNonStyle.non_style_metadata = { build_id: 'abc123' };
  const nonStylePass = await createValidationReport({ factsOverride: factsNonStyle });
  expect(nonStylePass.ok === true, 'Non-style changes do not fail style contract checks');

  // 9. Versioning fail: contract hash changes with same version should fail.
  const semverFailBaselinePath = await writeTempFile(
    'semver-fail-baseline.json',
    JSON.stringify(
      {
        spec_version: '1.0.0',
        contract_sha256: '0000000000000000000000000000000000000000000000000000000000000000',
        updated_at: new Date().toISOString(),
      },
      null,
      2
    ) + '\n'
  );
  const semverFail = await createValidationReport({
    factsOverride: baseFacts,
    baselinePath: semverFailBaselinePath,
  });
  expect(hasIssue(semverFail, 'semver_bump_required', 'meta.spec_version'), 'Versioning fail requires semver bump when contract hash changes');

  // 10. Versioning pass: bumped spec_version with changed hash should pass (warning allowed).
  const originalContract = await readYaml(CONTRACT_PATH);
  const bumpedContract = clone(originalContract);
  bumpedContract.meta.spec_version = '1.0.1';
  const bumpedContractPath = await writeTempFile(
    'semver-pass-bumped-contract.yaml',
    YAML.stringify(bumpedContract, { indent: 2, lineWidth: 0, minContentWidth: 0 })
  );

  const semverPass = await createValidationReport({
    contractPath: bumpedContractPath,
    factsOverride: baseFacts,
    baselinePath: BASELINE_PATH,
  });
  expect(!hasIssue(semverPass, 'semver_bump_required', 'meta.spec_version'), 'Versioning pass when semver is bumped');
  expect(semverPass.ok === true, 'Bumped semver contract remains valid with baseline warning only');

  if (failures.length > 0) {
    process.stderr.write(`ui-contract tests failed (${failures.length}/${checks.length})\n`);
    for (const failure of failures) {
      process.stderr.write(`- ${failure}\n`);
    }
    process.exit(1);
  }

  process.stdout.write(`ui-contract tests passed (${checks.length} checks)\n`);
}

main().catch((error) => {
  process.stderr.write(`test-contract failed: ${error.stack || error.message}\n`);
  process.exit(1);
});
