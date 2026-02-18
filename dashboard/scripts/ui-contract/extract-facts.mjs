#!/usr/bin/env node
import path from 'node:path';
import { extractFacts, GENERATED_DIR, ensureDir, writeJson } from './shared.mjs';

function parseArgs(argv) {
  const args = { out: path.join(GENERATED_DIR, 'extracted-facts.json') };
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (token === '--out' && argv[i + 1]) {
      args.out = path.resolve(argv[i + 1]);
      i += 1;
    }
  }
  return args;
}

async function main() {
  const { out } = parseArgs(process.argv.slice(2));
  const facts = await extractFacts();
  await ensureDir(path.dirname(out));
  await writeJson(out, facts);

  const summary = {
    out,
    utilities_exact: facts.utilities.exact_classes.length,
    utilities_arbitrary: facts.utilities.arbitrary_classes.length,
    components: facts.components.names.length,
    durations_ms: facts.tokens.motion.duration_ms,
    z_index_classes: facts.tokens.z_index_levels.classes,
  };

  process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
}

main().catch((error) => {
  process.stderr.write(`extract-facts failed: ${error.stack || error.message}\n`);
  process.exit(1);
});
