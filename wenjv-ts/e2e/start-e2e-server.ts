import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const e2eBaseDir = process.env['WENJV_E2E_DIR'] || path.join(os.tmpdir(), 'wenjv-e2e-data');

// Start each E2E run cleanly in an isolated workspace directory
fs.rmSync(e2eBaseDir, { recursive: true, force: true });
fs.mkdirSync(e2eBaseDir, { recursive: true });

process.env['NODE_ENV'] = 'production';
process.env['WENJV_BASE_DIR'] = e2eBaseDir;
process.env['HOST'] = '127.0.0.1';
process.env['PORT'] = '18797';
process.env['ALLOW_SELF_REGISTRATION'] = 'true';
process.env['SECRET_KEY'] = 'e2e-deterministic-secret-key-at-least-32-chars!!';

// Probe local OCR sidecar if available; otherwise keep offline fallback fast
let ocrUp = false;
try {
  const resp = await fetch('http://127.0.0.1:8788/health', {
    signal: AbortSignal.timeout(1000),
  });
  ocrUp = resp.ok;
} catch {
  ocrUp = false;
}
process.env['OCR_ENABLED'] = ocrUp ? 'true' : 'false';
if (ocrUp) {
  process.env['OCR_SIDECAR_URL'] = 'http://127.0.0.1:8788';
}

const { startServer } = await import('../packages/server/src/main.js');
startServer();
