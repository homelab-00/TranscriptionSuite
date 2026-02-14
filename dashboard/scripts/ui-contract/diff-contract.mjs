#!/usr/bin/env node
import fs from 'node:fs/promises';
import path from 'node:path';
import { GENERATED_DIR, ensureDir } from './shared.mjs';
import { createValidationReport } from './validate-contract.mjs';

function parseArgs(argv) {
  const args = {
    out: path.join(GENERATED_DIR, 'contract-diff.json'),
    json: false,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (token === '--out' && argv[i + 1]) {
      args.out = path.resolve(argv[i + 1]);
      i += 1;
      continue;
    }
    if (token === '--json') {
      args.json = true;
    }
  }

  return args;
}

function summarizeDiff(diff) {
  const summary = {
    set_mismatches: 0,
    tailwind_mismatches: 0,
    global_css_mismatches: 0,
    component_file_mismatches: diff.component_file_mismatches.length,
  };

  for (const entry of Object.values(diff.set_comparisons)) {
    if (entry.missing_in_contract.length > 0 || entry.stale_in_contract.length > 0) {
      summary.set_mismatches += 1;
    }
  }

  for (const entry of Object.values(diff.tailwind)) {
    if (!entry.equal) {
      summary.tailwind_mismatches += 1;
    }
  }

  for (const entry of Object.values(diff.global_css)) {
    if (!entry.equal) {
      summary.global_css_mismatches += 1;
    }
  }

  return summary;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const report = await createValidationReport();

  const payload = {
    generated_at: new Date().toISOString(),
    ok: report.ok,
    issue_count: report.issues.length,
    warning_count: report.warnings.length,
    diff_summary: report.semantic_diff ? summarizeDiff(report.semantic_diff) : null,
    semantic_diff: report.semantic_diff,
    issues: report.issues,
    warnings: report.warnings,
  };

  await ensureDir(path.dirname(args.out));
  await fs.writeFile(args.out, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');

  if (args.json) {
    process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
  } else {
    process.stdout.write(`Diff report written to ${args.out}\n`);
    process.stdout.write(`Issues: ${payload.issue_count}, Warnings: ${payload.warning_count}\n`);
    if (payload.diff_summary) {
      process.stdout.write(`Set mismatches: ${payload.diff_summary.set_mismatches}\n`);
      process.stdout.write(`Tailwind mismatches: ${payload.diff_summary.tailwind_mismatches}\n`);
      process.stdout.write(`Global CSS mismatches: ${payload.diff_summary.global_css_mismatches}\n`);
      process.stdout.write(`Component file mismatches: ${payload.diff_summary.component_file_mismatches}\n`);
    }
  }

  process.exit(payload.ok ? 0 : 1);
}

main().catch((error) => {
  process.stderr.write(`diff-contract failed: ${error.stack || error.message}\n`);
  process.exit(1);
});
