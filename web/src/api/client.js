/**
 * API client for FastAPI backend.
 * Dev: base = '/api' (Vite proxy). Prod: set VITE_API_URL.
 */
const API_BASE = (import.meta.env.VITE_API_URL || '/api').replace(/\/$/, '')

function authHeaders(token, extra = {}) {
  const h = { ...extra }
  if (token) h.Authorization = `Bearer ${token}`
  return h
}

async function parseError(res) {
  let detail = res.statusText
  try {
    const j = await res.json()
    detail = j.detail || JSON.stringify(j)
    if (Array.isArray(detail)) {
      detail = detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
    }
  } catch {
    try {
      detail = await res.text()
    } catch {
      /* ignore */
    }
  }
  const err = new Error(detail || `HTTP ${res.status}`)
  err.status = res.status
  throw err
}

export async function apiJson(path, { method = 'GET', token, body, headers } = {}) {
  const opts = {
    method,
    headers: authHeaders(token, {
      ...(body !== undefined && !(body instanceof FormData)
        ? { 'Content-Type': 'application/json' }
        : {}),
      ...headers,
    }),
  }
  if (body !== undefined) {
    opts.body = body instanceof FormData ? body : JSON.stringify(body)
  }
  const res = await fetch(`${API_BASE}${path}`, opts)
  if (!res.ok) await parseError(res)
  if (res.status === 204) return null
  const ct = res.headers.get('content-type') || ''
  if (ct.includes('application/json')) return res.json()
  return res.text()
}

export async function login(email, password) {
  const form = new URLSearchParams()
  form.set('username', email)
  form.set('password', password)
  const res = await fetch(`${API_BASE}/auth/jwt/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: form,
  })
  if (!res.ok) await parseError(res)
  return res.json() // { access_token, token_type }
}

export async function register(email, password) {
  return apiJson('/auth/register', {
    method: 'POST',
    body: { email, password },
  })
}

export async function validateToken(token) {
  return apiJson('/auth/validate-token', {
    method: 'POST',
    body: { token },
  })
}

export async function listFiles(token, skip = 0, limit = 50) {
  return apiJson(`/file/?skip=${skip}&limit=${limit}`, { token })
}

export async function listNotes(token, skip = 0, limit = 50) {
  return apiJson(`/file/note?skip=${skip}&limit=${limit}`, { token })
}

export async function listLinks(token, skip = 0, limit = 50) {
  return apiJson(`/links/?skip=${skip}&limit=${limit}`, { token })
}

export async function uploadFile(token, file) {
  const fd = new FormData()
  fd.append('file', file, file.name)
  return apiJson('/file/upload', { method: 'POST', token, body: fd })
}

export async function createNote(token, title, content) {
  return apiJson('/file/note', {
    method: 'POST',
    token,
    body: { title, content },
  })
}

export async function submitLink(token, url, headers = {}) {
  return apiJson('/links/submit', {
    method: 'POST',
    token,
    body: { url, headers },
  })
}

export async function deleteFile(token, fileId) {
  return apiJson(`/file/${fileId}`, { method: 'DELETE', token })
}

export async function deleteNote(token, noteId) {
  return apiJson(`/file/note/${noteId}`, { method: 'DELETE', token })
}

export async function deleteLink(token, linkId) {
  return apiJson(`/links/${linkId}`, { method: 'DELETE', token })
}

export async function searchDocuments(token, prompt, windowSize = 5, sourceType = null) {
  return apiJson('/documents/search', {
    method: 'POST',
    token,
    body: {
      prompt,
      window_size: windowSize,
      source_type: sourceType || null,
    },
  })
}

export async function searchByImage(token, file, windowSize = 5) {
  const fd = new FormData()
  fd.append('file', file, file.name)
  fd.append('window_size', String(windowSize))
  return apiJson('/documents/search/by-image', {
    method: 'POST',
    token,
    body: fd,
  })
}

export async function listChatModels(token) {
  return apiJson('/chat/models', { token })
}

/**
 * SSE chat. onEvent({type, ...})
 */
export async function streamChat(token, payload, onEvent, signal) {
  const res = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: authHeaders(token, {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    }),
    body: JSON.stringify(payload),
    signal,
  })
  if (!res.ok) await parseError(res)
  await readSSE(res, onEvent)
}

export async function streamChatByImage(token, file, fields, onEvent, signal) {
  const fd = new FormData()
  fd.append('file', file, file.name)
  Object.entries(fields || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null) fd.append(k, String(v))
  })
  const res = await fetch(`${API_BASE}/chat/by-image`, {
    method: 'POST',
    headers: authHeaders(token, { Accept: 'text/event-stream' }),
    body: fd,
    signal,
  })
  if (!res.ok) await parseError(res)
  await readSSE(res, onEvent)
}

async function readSSE(res, onEvent) {
  const reader = res.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    const parts = buf.split('\n')
    buf = parts.pop() || ''
    for (const line of parts) {
      const t = line.trim()
      if (!t.startsWith('data:')) continue
      const raw = t.slice(5).trim()
      if (!raw) continue
      try {
        onEvent(JSON.parse(raw))
      } catch {
        /* ignore partial */
      }
    }
  }
}

export { API_BASE }
