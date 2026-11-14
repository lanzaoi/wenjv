import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { z } from 'zod';

function parseEnvFile(filePath: string): Record<string, string> {
  const result: Record<string, string> = {};
  if (!fs.existsSync(filePath)) {
    return result;
  }
  const content = fs.readFileSync(filePath, 'utf8');
  for (const rawLine of content.split('\n')) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#') || line.startsWith('---') || !line.includes('=')) {
      continue;
    }
    const idx = line.indexOf('=');
    const key = line.slice(0, idx).trim();
    const value = line.slice(idx + 1).trim();
    result[key] = value;
  }
  return result;
}

const defaultBaseDir = process.env['WENJV_BASE_DIR'] || process.env['BASE_DIR'] || path.join(os.homedir(), '.config', 'wenjv');
const envFromFile = parseEnvFile(path.join(defaultBaseDir, 'backend.env'));

const mergedEnv = {
  ...envFromFile,
  ...process.env,
};

const parseEnvBoolean = (defaultValue: boolean) =>
  z.preprocess(
    (v) =>
      v === undefined
        ? undefined
        : typeof v === 'string'
          ? !['false', '0', 'no', 'off', ''].includes(v.trim().toLowerCase())
          : Boolean(v),
    z.boolean().default(defaultValue)
  );

const ConfigSchema = z.object({
  PORT: z.coerce.number().default(8787),
  HOST: z.string().default('0.0.0.0'),
  BASE_DIR: z.string().default(defaultBaseDir),
  DB_PATH: z.string().optional(),
  LANCE_DIR: z.string().optional(),
  VECTOR_STORE_COLLECTION_NAME: z.string().default('text_vectors'),
  VISUAL_VECTOR_STORE_COLLECTION_NAME: z.string().default('visual_vectors'),
  UPLOAD_DIR: z.string().optional(),
  VAULT_DIR: z.string().optional(),
  MODELS_DIR: z.string().default(
    process.env['MODELS_DIR'] || path.resolve(process.cwd(), '..', 'models')
  ),
  JWT_SECRET: z.string().default('YOUR_SECRET_KEY_CHANGE_THIS'),
  JWT_AUDIENCE: z.string().default('fastapi-users:auth'),
  JWT_EXPIRES_IN_SECONDS: z.coerce.number().default(86400),
  ALLOWED_UPLOAD_EXTENSIONS: z.array(z.string()).default([
    'txt', 'pdf', 'md', 'json', 'sh', 'markdown',
    'docx', 'pptx', 'csv', 'html', 'htm', 'png', 'jpg', 'jpeg',
  ]),
  MAX_UPLOAD_BYTES: z.coerce.number().default(25 * 1024 * 1024),
  JOB_WORKER_CONCURRENCY: z.coerce.number().default(6),
  JOB_MAX_ATTEMPTS: z.coerce.number().default(3),
  JOB_POLL_INTERVAL_SECONDS: z.coerce.number().default(2.0),
  JOB_STALE_SECONDS: z.coerce.number().default(30 * 60),

  CHAT_PROVIDER: z.string().default('openai'),
  CHAT_API_KEY: z.string().default(''),
  CHAT_MODEL: z.string().default('spark-x2.6'),
  CHAT_API_BASE: z.string().default('https://maas-api.cn-huabei-1.xf-yun.com/v2'),

  EMBEDDING_PROVIDER: z.string().default('local'),
  EMBEDDING_API_KEY: z.string().default(''),
  EMBEDDING_API_BASE: z.string().default('https://api.siliconflow.cn/v1'),
  EMBEDDINGS_MODEL: z.string().default('BAAI/bge-m3'),

  RERANK_ENABLED: parseEnvBoolean(true),
  RERANK_PROVIDER: z.string().default('local_onnx'),
  RERANK_API_KEY: z.string().default(''),
  RERANK_API_BASE: z.string().default('https://api.siliconflow.cn/v1'),
  RERANK_MODEL: z.string().default('BAAI/bge-reranker-v2-m3'),
  RERANK_MAX_LENGTH: z.coerce.number().default(256),
  RERANK_MICRO_BATCH_SIZE: z.coerce.number().default(4),

  OCR_ENABLED: parseEnvBoolean(true),
  OCR_SIDECAR_URL: z.string().default('http://127.0.0.1:8788'),
  OCR_TIMEOUT_MS: z.coerce.number().default(60000),
  OCR_MIN_CHARS: z.coerce.number().default(40),
  OCR_IMAGE_MODE: z.enum(['auto', 'general', 'formula']).default('auto'),
});

export type Config = z.infer<typeof ConfigSchema> & {
  resolvedDbPath: string;
  resolvedLanceDir: string;
  resolvedUploadDir: string;
  resolvedVaultDir: string;
  resolvedModelsDir: string;
};

export const config: Config = {} as Config;

export function loadConfig(overrides?: Partial<z.infer<typeof ConfigSchema>>): Config {
  const effectiveBaseDir =
    overrides?.BASE_DIR ||
    process.env['WENJV_BASE_DIR'] ||
    process.env['BASE_DIR'] ||
    path.join(os.homedir(), '.config', 'wenjv');
  const dynamicFileEnv = parseEnvFile(path.join(effectiveBaseDir, 'backend.env'));
  const combined: Record<string, unknown> = {
    ...dynamicFileEnv,
    ...process.env,
    ...overrides,
  };
  if (!combined['JWT_SECRET'] && typeof combined['SECRET_KEY'] === 'string' && combined['SECRET_KEY']) {
    combined['JWT_SECRET'] = combined['SECRET_KEY'];
  }

  const parsed = ConfigSchema.parse(combined);

  const baseDir = parsed.BASE_DIR;
  const resolvedDbPath = parsed.DB_PATH || path.join(baseDir, 'wenjv.db');
  const resolvedLanceDir = parsed.LANCE_DIR || path.join(baseDir, 'lance_db');
  const resolvedUploadDir = parsed.UPLOAD_DIR || path.join(baseDir, 'uploads');
  const resolvedVaultDir = parsed.VAULT_DIR || path.join(baseDir, 'wiki_vault');

  let resolvedModelsDir = parsed.MODELS_DIR;
  if (!fs.existsSync(resolvedModelsDir)) {
    const candidates = [
      path.resolve(process.cwd(), 'models'),
      path.resolve(process.cwd(), '..', 'models'),
      path.resolve(process.cwd(), '..', '..', 'models'),
      '/home/lanzao/antigravity/jolly-hawking/models',
    ];
    for (const cand of candidates) {
      if (fs.existsSync(cand)) {
        resolvedModelsDir = cand;
        break;
      }
    }
  }

  const updated: Config = {
    ...parsed,
    resolvedDbPath,
    resolvedLanceDir,
    resolvedUploadDir,
    resolvedVaultDir,
    resolvedModelsDir,
  };

  Object.assign(config, updated);
  return updated;
}

loadConfig();
