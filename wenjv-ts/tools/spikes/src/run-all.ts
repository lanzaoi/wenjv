import { runSqliteSpike } from './sqlite.spike.js';
import { runLanceDbSpike } from './lancedb.spike.js';
import { runBgeM3Spike } from './bge-m3.spike.js';
import { runRerankerSpike } from './reranker.spike.js';
import { runParsersSpike } from './parsers.spike.js';
import { runSharpSpike } from './sharp.spike.js';
import { runAuthSpike } from './auth.spike.js';

async function main() {
  console.log('== Running G1 Component Spikes ==');
  const spikes: [string, () => Promise<void>][] = [
    ['sqlite (better-sqlite3 + trigram FTS5)', runSqliteSpike],
    ['lancedb (@lancedb/lancedb vector store)', runLanceDbSpike],
    ['bge-m3 (local ONNX dense embedder)', runBgeM3Spike],
    ['reranker (local ONNX bge-reranker-base)', runRerankerSpike],
    ['parsers (unpdf, mammoth, pptx/jszip, readability)', runParsersSpike],
    ['sharp (image resizing & WebP convert)', runSharpSpike],
    ['auth (argon2id + jose JWT)', runAuthSpike],
  ];

  let hasFailure = false;
  for (const [name, fn] of spikes) {
    try {
      const start = Date.now();
      await fn();
      const elapsed = Date.now() - start;
      console.log(`  \x1b[32mOK\x1b[0m   ${name} (${elapsed}ms)`);
    } catch (err) {
      hasFailure = true;
      console.error(`  \x1b[31mFAIL\x1b[0m ${name}`);
      console.error(err);
    }
  }

  if (hasFailure) {
    console.error('\nG1 Spikes: SOME FAILED');
    process.exit(1);
  } else {
    console.log('\nG1 Spikes: ALL PASSED (100%)');
    process.exit(0);
  }
}

main().catch((err) => {
  console.error('Fatal spike runner error:', err);
  process.exit(1);
});
