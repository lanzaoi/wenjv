/**
 * API client for TypeScript / Hono backend.
 * Dev: base = '/api' (Vite proxy). Prod: set VITE_API_URL.
 */
const API_BASE = (import.meta.env.VITE_API_URL || '/api').replace(/\/$/, '');

export interface RequestOptions {
  method?: string;
  token?: string | null;
  body?: unknown;
  headers?: Record<string, string>;
}

export interface ApiError extends Error {
  status?: number;
}

function authHeaders(token?: string | null, extra: Record<string, string> = {}): Record<string, string> {
  const h = { ...extra };
  if (token) h['Authorization'] = `Bearer ${token}`;
  return h;
}

async function parseError(res: Response): Promise<never> {
  let detail: string = res.statusText;
  try {
    const j = await res.json();
    detail = j.detail || JSON.stringify(j);
    if (Array.isArray(detail)) {
      detail = (detail as Array<{ msg?: string }>).map((d) => d.msg || JSON.stringify(d)).join('; ');
    }
  } catch {
    try {
      detail = await res.text();
    } catch {
      /* ignore */
    }
  }
  const err: ApiError = new Error(detail || `HTTP ${res.status}`);
  err.status = res.status;
  throw err;
}

export async function apiJson<T = any>(path: string, { method = 'GET', token, body, headers }: RequestOptions = {}): Promise<T> {
  const opts: RequestInit = {
    method,
    headers: authHeaders(token, {
      ...(body !== undefined && !(body instanceof FormData)
        ? { 'Content-Type': 'application/json' }
        : {}),
      ...headers,
    }),
  };
  if (body !== undefined) {
    opts.body = body instanceof FormData ? body : JSON.stringify(body);
  }
  const res = await fetch(`${API_BASE}${path}`, opts);
  if (!res.ok) await parseError(res);
  if (res.status === 204) return null as T;
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) return res.json();
  return (await res.text()) as unknown as T;
}

export async function login(email: string, password: string): Promise<{ access_token: string; token_type: string }> {
  const form = new URLSearchParams();
  form.set('username', email);
  form.set('password', password);
  const res = await fetch(`${API_BASE}/auth/jwt/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: form,
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function register(email: string, password: string): Promise<any> {
  return apiJson('/auth/register', {
    method: 'POST',
    body: { email, password },
  });
}

export interface UserMe {
  id: number;
  email: string;
  username: string | null;
  is_active: boolean;
  is_superuser: boolean;
  is_verified: boolean;
}

export async function validateToken(token: string): Promise<{
  valid: boolean;
  user_id?: number;
  email?: string;
  is_superuser?: boolean;
}> {
  return apiJson('/auth/validate-token', {
    method: 'POST',
    body: { token },
  });
}

export async function getMe(token: string): Promise<UserMe> {
  return apiJson('/auth/users/me', { token });
}

export type ResourceType = 'file' | 'note' | 'link';

export interface ResourceItem {
  id: number;
  user_id: number;
  type: ResourceType;
  title: string;
  filename: string | null;
  original_filename: string | null;
  source_url: string | null;
  status: string;
  error_message: string | null;
  tags: string[];
  created_at: string;
  updated_at: string | null;
}

export interface TagSummary {
  id: number;
  name: string;
  tag: string;
  color: string;
  count: number;
}

export async function listResources(
  token?: string | null,
  options: { type?: ResourceType; tag?: string; skip?: number; limit?: number } = {}
): Promise<{ resources: ResourceItem[]; total: number }> {
  const params = new URLSearchParams();
  if (options.type) params.set('type', options.type);
  if (options.tag) params.set('tag', options.tag);
  if (options.skip !== undefined) params.set('skip', String(options.skip));
  if (options.limit !== undefined) params.set('limit', String(options.limit));
  const qs = params.toString();
  return apiJson(`/resources${qs ? '?' + qs : ''}`, { token });
}

export async function uploadFile(token: string | null, file: File, tags: string[] | null = null): Promise<ResourceItem> {
  const fd = new FormData();
  fd.append('file', file, file.name);
  if (tags && tags.length > 0) {
    fd.append('tags', JSON.stringify(tags));
  }
  return apiJson('/resources/files', { method: 'POST', token, body: fd });
}

export async function createNote(
  token: string | null,
  title: string,
  content: string,
  tags: string[] | null = null
): Promise<ResourceItem> {
  const body: Record<string, unknown> = { title, content };
  if (tags && tags.length > 0) body['tags'] = tags;
  return apiJson('/resources/notes', {
    method: 'POST',
    token,
    body,
  });
}

export async function submitLink(
  token: string | null,
  url: string,
  headers: Record<string, string> = {},
  tags: string[] | null = null
): Promise<ResourceItem> {
  const body: Record<string, unknown> = { url, headers };
  if (tags && tags.length > 0) body['tags'] = tags;
  return apiJson('/resources/links', {
    method: 'POST',
    token,
    body,
  });
}

export async function deleteResource(token: string | null, resourceId: string | number): Promise<{ status: string }> {
  return apiJson(`/resources/${resourceId}`, { method: 'DELETE', token });
}

export async function getResourceDetail(
  token: string | null,
  resourceId: string | number
): Promise<ResourceItem & { content?: string }> {
  return apiJson(`/resources/${resourceId}`, { token });
}

export async function reingestResource(
  token: string | null,
  resourceId: string | number,
  ocrMode: 'auto' | 'general' | 'formula' = 'auto'
): Promise<{ status: string; resource_id: number; job_id: number }> {
  return apiJson(`/resources/${resourceId}/reingest`, {
    method: 'POST',
    token,
    body: { ocr_mode: ocrMode },
  });
}

export function resourceContentUrl(resourceId: number | string, token?: string | null): string {
  const qs = token ? `?token=${encodeURIComponent(token)}` : '';
  return `/api/resources/${encodeURIComponent(String(resourceId))}/content${qs}`;
}

export interface AdminStats {
  total_queries: number;
  avg_latency_ms: number;
  v_hit_rate: number;
  fts5_hit_rate: number;
  s_hit_rate: number;
  cache_hit_rate: number;
  error_rate: number;
  last_24h_queries: number;
  counts: {
    users: number;
    resources: number;
    files: number;
    notes: number;
    links: number;
    chunks: number;
    assets: number;
    tags: number;
    wiki_pages: number;
    queries: number;
  };
  jobs?: Record<string, number>;
  runtime?: {
    ocr?: { ok: boolean; status?: string; engines?: Record<string, unknown> };
    siglip2_vision?: boolean;
  };
  api_calls: Array<{
    provider: string;
    call_type: string;
    call_count: number;
    last_reset: string | null;
  }>;
}

export interface AdminQueryLog {
  id: number;
  query: string;
  timestamp: string;
  latency_ms: number;
  v_hits: number;
  fts5_hits: number;
  s_hits: number;
  total_hits: number;
  cache_hit: number;
  error: string | null;
}

export interface IngestionJobItem {
  id: number;
  entity_type: string;
  entity_id: number;
  status: string;
  attempts: number;
  max_attempts: number;
  last_error: string | null;
  created_at: string;
  updated_at: string | null;
}

export async function getAdminStats(token: string | null): Promise<AdminStats> {
  return apiJson('/admin/stats', { token });
}

export async function getAdminLogs(token: string | null, limit = 50): Promise<{ logs: AdminQueryLog[] }> {
  return apiJson(`/admin/logs?limit=${limit}`, { token });
}

export async function resetAdminCounts(token: string | null): Promise<{ message: string }> {
  return apiJson('/admin/reset-counts', { method: 'POST', token });
}

export async function listJobs(token: string | null): Promise<IngestionJobItem[]> {
  return apiJson('/jobs', { token });
}

export async function retryJob(token: string | null, jobId: number): Promise<{ status: string; job_id: number }> {
  return apiJson(`/jobs/${jobId}/retry`, { method: 'POST', token });
}

export interface LegacyImportPreview {
  isValidLegacyDb: boolean;
  files: number;
  notes: number;
  links: number;
  wikiPages: number;
  foundOnDisk: number;
  missingFiles: number;
}

export interface LegacyDetectResult {
  detected: boolean;
  same_as_active: boolean;
  source_label?: string;
  preview?: LegacyImportPreview;
}

export interface LegacyImportResult {
  status: string;
  enqueued: number;
  stats: {
    files: number;
    notes: number;
    links: number;
    wikiPages: number;
    wikiRevisions: number;
    wikiLinks: number;
    copiedFiles: number;
    missingFiles: number;
  };
}

export async function detectLegacyImport(token?: string | null): Promise<LegacyDetectResult> {
  return apiJson('/resources/import-legacy/detect', { token });
}

export async function importLocalLegacy(
  token: string | null,
  skipMissing = true
): Promise<LegacyImportResult> {
  return apiJson('/resources/import-legacy', {
    method: 'POST',
    token,
    body: { source: 'local_v1', skip_missing: skipMissing },
  });
}

export async function importLegacyBundle(
  token: string | null,
  dbFile: File,
  attachmentFiles: File[] = [],
  skipMissing = true
): Promise<LegacyImportResult> {
  const fd = new FormData();
  fd.append('db', dbFile, dbFile.name);
  fd.append('skip_missing', String(skipMissing));
  for (const f of attachmentFiles) {
    fd.append('files', f, f.name);
  }
  return apiJson('/resources/import-legacy', {
    method: 'POST',
    token,
    body: fd,
  });
}

export async function getTags(token?: string | null, limit = 100): Promise<{ tags: TagSummary[] }> {
  return apiJson(`/tags?limit=${limit}`, { token });
}

export async function updateTag(
  token: string | null,
  tagId: number,
  patch: { name?: string; color?: string }
): Promise<TagSummary> {
  return apiJson(`/tags/${tagId}`, {
    method: 'PUT',
    token,
    body: patch,
  });
}

export async function deleteTag(token: string | null, tagId: number): Promise<{ status: string }> {
  return apiJson(`/tags/${tagId}`, { method: 'DELETE', token });
}

export async function updateResourceTags(
  token: string | null,
  entityType: 'resource' | 'wiki',
  entityId: string | number,
  tags: string[]
): Promise<{ tags: string[] }> {
  return apiJson(`/tags/entities/${entityType}/${entityId}`, {
    method: 'PUT',
    token,
    body: { tags },
  });
}

export async function searchDocuments(
  token: string | null,
  prompt: string,
  windowSize = 5,
  sourceType: string | null = null,
  tags: string[] | null = null
): Promise<{ documents: any[]; count: number }> {
  const body: Record<string, unknown> = {
    prompt,
    window_size: windowSize,
    type: sourceType || null,
  };
  if (tags && tags.length > 0) body['tags'] = tags;
  return apiJson('/search', {
    method: 'POST',
    token,
    body,
  });
}

export async function searchByImage(
  token: string | null,
  file: File,
  windowSize = 5,
  prompt = ''
): Promise<{ documents: any[]; count: number }> {
  const fd = new FormData();
  fd.append('file', file, file.name);
  fd.append('window_size', String(windowSize));
  if (prompt && prompt.trim()) {
    fd.append('prompt', prompt.trim());
  }
  return apiJson('/search/by-image', {
    method: 'POST',
    token,
    body: fd,
  });
}

export async function listChatModels(token?: string | null): Promise<any> {
  return apiJson('/chat/models', { token });
}

/**
 * SSE chat. onEvent({type, ...})
 */
export async function streamChat(
  token: string | null,
  payload: unknown,
  onEvent: (data: any) => void,
  signal?: AbortSignal
): Promise<void> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: authHeaders(token, {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    }),
    body: JSON.stringify(payload),
    signal,
  });
  if (!res.ok) await parseError(res);
  await readSSE(res, onEvent);
}

export async function uploadChatAttachment(
  token: string | null,
  file: File,
  sessionId?: string
): Promise<{ media_url: string; media_id: string; filename: string; content_type: string; size: number }> {
  const fd = new FormData();
  fd.append('file', file, file.name);
  if (sessionId) fd.append('session_id', sessionId);
  const res = await fetch(`${API_BASE}/chat/attachments`, {
    method: 'POST',
    headers: authHeaders(token),
    body: fd,
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

export async function streamChatByImage(
  token: string | null,
  file: File,
  fields: Record<string, unknown>,
  onEvent: (data: any) => void,
  signal?: AbortSignal
): Promise<void> {
  const fd = new FormData();
  fd.append('file', file, file.name);
  Object.entries(fields || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null) fd.append(k, String(v));
  });
  const res = await fetch(`${API_BASE}/chat/by-image`, {
    method: 'POST',
    headers: authHeaders(token, { Accept: 'text/event-stream' }),
    body: fd,
    signal,
  });
  if (!res.ok) await parseError(res);
  await readSSE(res, onEvent);
}

async function readSSE(res: Response, onEvent: (data: any) => void): Promise<void> {
  if (!res.body) return;
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const parts = buf.split('\n');
    buf = parts.pop() || '';
    for (const line of parts) {
      const t = line.trim();
      if (!t.startsWith('data:')) continue;
      const raw = t.slice(5).trim();
      if (!raw) continue;
      try {
        onEvent(JSON.parse(raw));
      } catch {
        /* ignore partial */
      }
    }
  }
}

export const wikiApi = {
  getTree(token?: string | null) {
    return apiJson('/wiki/tree', { token });
  },
  getPage(pageId: number | string, token?: string | null) {
    return apiJson(`/wiki/pages/${pageId}`, { token });
  },
  createPage(body: unknown, token?: string | null) {
    return apiJson('/wiki/pages', { method: 'POST', body, token });
  },
  updatePage(pageId: number | string, body: unknown, token?: string | null) {
    return apiJson(`/wiki/pages/${pageId}`, { method: 'PUT', body, token });
  },
  deletePage(pageId: number | string, token?: string | null) {
    return apiJson(`/wiki/pages/${pageId}`, { method: 'DELETE', token });
  },
  movePage(pageId: number | string, body: unknown, token?: string | null) {
    return apiJson(`/wiki/pages/${pageId}/move`, { method: 'POST', body, token });
  },
  getRevisions(pageId: number | string, token?: string | null) {
    return apiJson(`/wiki/pages/${pageId}/revisions`, { token });
  },
  rollbackRevision(pageId: number | string, revNo: number, token?: string | null) {
    return apiJson(`/wiki/pages/${pageId}/rollback/${revNo}`, { method: 'POST', token });
  },
  uploadAsset(pageId: number | string, file: File, token?: string | null) {
    const fd = new FormData();
    fd.append('file', file, file.name);
    return apiJson(`/wiki/pages/${pageId}/assets`, { method: 'POST', body: fd, token });
  },
  getDiff(pageId: number | string, fromRev: number, toRev: number, token?: string | null) {
    return apiJson(`/wiki/pages/${pageId}/diff?from_rev=${fromRev}&to_rev=${toRev}`, { token });
  },
  getGraph(token?: string | null) {
    return apiJson('/wiki/graph', { token });
  },
  searchWiki(q: string, token?: string | null) {
    return apiJson(`/wiki/search?q=${encodeURIComponent(q)}`, { token });
  },
  getUnlinkedMentions(pageId: number | string, token?: string | null) {
    return apiJson(`/wiki/pages/${pageId}/unlinked-mentions`, { token });
  },
  linkMention(pageId: number | string, sourcePageId: number | string, token?: string | null) {
    return apiJson(`/wiki/pages/${pageId}/link-mention`, {
      method: 'POST',
      body: { source_page_id: sourcePageId },
      token,
    });
  },
  async streamCopilot(
    pageId: number | string,
    body: unknown,
    token: string | null,
    onEvent: (data: any) => void,
    signal?: AbortSignal
  ): Promise<void> {
    const res = await fetch(`${API_BASE}/wiki/pages/${pageId}/copilot`, {
      method: 'POST',
      headers: authHeaders(token, {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      }),
      body: JSON.stringify(body),
      signal,
    });
    if (!res.ok) await parseError(res);
    await readSSE(res, onEvent);
  },
};

export { API_BASE };
