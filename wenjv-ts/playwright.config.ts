import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { defineConfig } from '@playwright/test';

const userLibDir = path.join(os.homedir(), '.local', 'share', 'wenjv-e2e-libs', 'usr', 'lib');
const hasUserLibs = fs.existsSync(userLibDir);
const ldLibraryPath = hasUserLibs
  ? [userLibDir, process.env['LD_LIBRARY_PATH']].filter(Boolean).join(':')
  : process.env['LD_LIBRARY_PATH'];

export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  expect: {
    timeout: 15_000,
  },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:18797',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    ...(ldLibraryPath
      ? {
          launchOptions: {
            env: {
              ...process.env,
              LD_LIBRARY_PATH: ldLibraryPath,
            },
          },
        }
      : {}),
  },
  webServer: {
    command: 'pnpm --filter @wenjv/server exec tsx ../../e2e/start-e2e-server.ts',
    url: 'http://127.0.0.1:18797/health',
    reuseExistingServer: false,
    timeout: 45_000,
  },
});
