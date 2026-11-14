import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, it, expect, afterEach } from 'vitest';
import { loadConfig, resolveJwtSecret } from '../src/config.js';

describe('Config Boolean & Env Compatibility', () => {
  afterEach(() => {
    loadConfig();
  });

  it('parses string "false", "0", "no", "off" as false for RERANK_ENABLED and OCR_ENABLED', () => {
    const disabled = loadConfig({
      RERANK_ENABLED: 'false' as unknown as boolean,
      OCR_ENABLED: '0' as unknown as boolean,
    });
    expect(disabled.RERANK_ENABLED).toBe(false);
    expect(disabled.OCR_ENABLED).toBe(false);

    const enabled = loadConfig({
      RERANK_ENABLED: 'true' as unknown as boolean,
      OCR_ENABLED: 'on' as unknown as boolean,
    });
    expect(enabled.RERANK_ENABLED).toBe(true);
    expect(enabled.OCR_ENABLED).toBe(true);
  });

  it('maps legacy SECRET_KEY env var to JWT_SECRET when JWT_SECRET is unset', () => {
    const prevSecret = process.env['SECRET_KEY'];
    const prevJwt = process.env['JWT_SECRET'];
    const emptyBaseDir = fs.mkdtempSync(path.join(os.tmpdir(), 'wenjv-cfg-'));
    try {
      delete process.env['JWT_SECRET'];
      process.env['SECRET_KEY'] = 'legacy-secret-value';
      const cfg = loadConfig({ BASE_DIR: emptyBaseDir });
      expect(cfg.JWT_SECRET).toBe('legacy-secret-value');
    } finally {
      fs.rmSync(emptyBaseDir, { recursive: true, force: true });
      if (prevSecret === undefined) delete process.env['SECRET_KEY'];
      else process.env['SECRET_KEY'] = prevSecret;
      if (prevJwt === undefined) delete process.env['JWT_SECRET'];
      else process.env['JWT_SECRET'] = prevJwt;
    }
  });

  it('rejects missing JWT_SECRET in production and rejects public placeholder secrets (H1)', () => {
    expect(() => resolveJwtSecret(undefined, false)).toThrow(/JWT_SECRET 未设置/);
    expect(() => resolveJwtSecret('YOUR_SECRET_KEY_CHANGE_THIS', true)).toThrow(/占位符/);
    expect(() => loadConfig({ JWT_SECRET: 'YOUR_SECRET_KEY_CHANGE_THIS' })).toThrow(/占位符/);
    const testSecret = resolveJwtSecret(undefined, true);
    expect(testSecret.length).toBeGreaterThanOrEqual(32);
    expect(testSecret).not.toBe('YOUR_SECRET_KEY_CHANGE_THIS');
  });

  it('formats numeric env parse errors with field context (L3)', () => {
    expect(() => loadConfig({ PORT: 'not-a-number' as unknown as number })).toThrow(/环境变量配置无效: PORT:/);
  });
});
