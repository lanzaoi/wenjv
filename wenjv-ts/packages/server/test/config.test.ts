import { describe, it, expect, afterEach } from 'vitest';
import { loadConfig } from '../src/config.js';

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
    try {
      delete process.env['JWT_SECRET'];
      process.env['SECRET_KEY'] = 'legacy-secret-value';
      const cfg = loadConfig();
      expect(cfg.JWT_SECRET).toBe('legacy-secret-value');
    } finally {
      if (prevSecret === undefined) delete process.env['SECRET_KEY'];
      else process.env['SECRET_KEY'] = prevSecret;
      if (prevJwt === undefined) delete process.env['JWT_SECRET'];
      else process.env['JWT_SECRET'] = prevJwt;
    }
  });
});
