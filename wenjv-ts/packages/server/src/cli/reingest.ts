import path from 'node:path';
import { loadConfig, config } from '../config.js';
import { getDb, closeDb } from '../db/index.js';
import { importV1SnapshotIntoV2, rebuildAllIndexes } from '../services/reingest.js';

function parseArgs(argv: string[]): {
  fromV1?: string | undefined;
  uploadsDir?: string | undefined;
  includeLinks: boolean;
  skipRebuild: boolean;
  skipMissing: boolean;
} {
  let fromV1: string | undefined;
  let uploadsDir: string | undefined;
  let includeLinks = false;
  let skipRebuild = false;
  let skipMissing = false;

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i]!;
    if (arg === '--from-v1' && argv[i + 1]) {
      fromV1 = path.resolve(argv[++i]!);
    } else if (arg === '--uploads-dir' && argv[i + 1]) {
      uploadsDir = path.resolve(argv[++i]!);
    } else if (arg === '--include-links') {
      includeLinks = true;
    } else if (arg === '--import-only') {
      skipRebuild = true;
    } else if (arg === '--skip-missing') {
      skipMissing = true;
    }
  }

  return { fromV1, uploadsDir, includeLinks, skipRebuild, skipMissing };
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));
  loadConfig();
  getDb();

  try {
    const importStats = args.fromV1
      ? importV1SnapshotIntoV2({
          v1DbPath: args.fromV1,
          ...(args.uploadsDir ? { sourceUploadsDir: args.uploadsDir } : {}),
          copyFiles: true,
          skipMissing: args.skipMissing,
        })
      : null;

    const rebuildStats = args.skipRebuild
      ? null
      : await rebuildAllIndexes({
          includeLinks: args.includeLinks,
          cleanExisting: true,
        });

    console.log(
      JSON.stringify(
        {
          baseDir: config.BASE_DIR,
          dbPath: config.resolvedDbPath,
          lanceDir: config.resolvedLanceDir,
          imported: importStats,
          rebuilt: rebuildStats,
        },
        null,
        2
      )
    );
  } finally {
    closeDb();
  }
}

main().catch((err: unknown) => {
  console.error('Re-ingestion failed:', err);
  process.exit(1);
});
