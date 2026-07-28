<template>
  <div class="lib">
    <header class="head">
      <div class="head-left">
        <div class="head-icon"><Icon name="library" :size="22" /></div>
        <div>
          <h1>资料库</h1>
          <p class="muted sub">已入库的文件、笔记与链接</p>
        </div>
      </div>
      <button class="btn btn-secondary" type="button" :disabled="loading" @click="reload">
        <Icon name="refresh" :size="15" :spin="loading" />
        <span>{{ loading ? '刷新中' : '刷新' }}</span>
      </button>
    </header>
    <div v-if="error" class="error-banner">
      <Icon name="x" :size="15" />
      <span>{{ error }}</span>
    </div>

    <div v-if="loading && !hasAny" class="skel-grid">
      <div v-for="i in 3" :key="i" class="card panel skel-panel">
        <div class="skel" style="height: 18px; width: 40%; margin-bottom: 16px" />
        <div class="skel" style="height: 12px; width: 90%; margin-bottom: 10px" />
        <div class="skel" style="height: 12px; width: 70%; margin-bottom: 10px" />
        <div class="skel" style="height: 12px; width: 80%" />
      </div>
    </div>

    <div v-else class="grid">
      <section class="card panel">
        <div class="panel-h">
          <div class="panel-title">
            <Icon name="file" :size="16" />
            <h2>文件</h2>
          </div>
          <span class="badge">{{ files.total || 0 }}</span>
        </div>
        <div v-if="!files.files?.length" class="empty muted">
          <div class="empty-glyph"><Icon name="file" :size="20" /></div>
          暂无文件
        </div>
        <ul v-else>
          <li v-for="f in files.files || []" :key="f.file_url + f.filename">
            <div class="row-ico"><Icon name="file" :size="16" /></div>
            <div class="row-body">
              <div class="row-main">
                <strong>{{ f.filename }}</strong>
                <StatusDot :status="f.status" />
              </div>
              <div class="muted meta">{{ formatDate(f.created_at) }}</div>
            </div>
          </li>
        </ul>
      </section>

      <section class="card panel">
        <div class="panel-h">
          <div class="panel-title">
            <Icon name="note" :size="16" />
            <h2>笔记</h2>
          </div>
          <span class="badge">{{ notes.total || 0 }}</span>
        </div>
        <div v-if="!notes.notes?.length" class="empty muted">
          <div class="empty-glyph"><Icon name="note" :size="20" /></div>
          暂无笔记
        </div>
        <ul v-else>
          <li v-for="n in notes.notes || []" :key="n.id">
            <div class="row-ico"><Icon name="note" :size="16" /></div>
            <div class="row-body">
              <div class="row-main">
                <strong>{{ n.title }}</strong>
                <StatusDot :status="n.status || '—'" />
              </div>
              <div class="muted meta">{{ n.filename }}</div>
            </div>
          </li>
        </ul>
      </section>

      <section class="card panel">
        <div class="panel-h">
          <div class="panel-title">
            <Icon name="globe" :size="16" />
            <h2>链接</h2>
          </div>
          <span class="badge">{{ links.total || 0 }}</span>
        </div>
        <div v-if="!links.links?.length" class="empty muted">
          <div class="empty-glyph"><Icon name="link" :size="20" /></div>
          暂无链接
        </div>
        <ul v-else>
          <li v-for="l in links.links || []" :key="l.id">
            <div class="row-ico"><Icon name="link" :size="16" /></div>
            <div class="row-body">
              <div class="row-main">
                <strong>{{ l.title || l.url }}</strong>
                <StatusDot :status="l.status" />
              </div>
              <div class="muted mono meta">{{ l.url }}</div>
            </div>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useAuthStore } from '../stores/auth'
import { listFiles, listNotes, listLinks } from '../api/client'
import Icon from '../components/Icon.vue'
import StatusDot from '../components/StatusDot.vue'

const auth = useAuthStore()
const loading = ref(false)
const error = ref('')
const files = ref({ files: [], total: 0 })
const notes = ref({ notes: [], total: 0 })
const links = ref({ links: [], total: 0 })

const hasAny = computed(() => {
  return (
    (files.value.files?.length || 0) +
      (notes.value.notes?.length || 0) +
      (links.value.links?.length || 0) >
    0
  )
})

function formatDate(v) {
  if (!v) return ''
  try {
    const d = new Date(v)
    if (Number.isNaN(d.getTime())) return String(v)
    return d.toLocaleString()
  } catch {
    return String(v)
  }
}

async function reload() {
  loading.value = true
  error.value = ''
  try {
    const [f, n, l] = await Promise.all([
      listFiles(auth.token),
      listNotes(auth.token),
      listLinks(auth.token),
    ])
    files.value = f || { files: [], total: 0 }
    notes.value = n || { notes: [], total: 0 }
    links.value = l || { links: [], total: 0 }
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

onMounted(reload)
</script>

<style scoped>
.lib {
  padding: 22px 22px 40px;
  max-width: 1180px;
  margin: 0 auto;
}
.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}
.head-left {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}
.head-icon {
  width: 44px;
  height: 44px;
  border-radius: 14px;
  background: var(--surface);
  border: 1px solid var(--border);
  display: grid;
  place-items: center;
  color: var(--accent);
  box-shadow: var(--shadow-sm);
}
.head h1 {
  margin: 0;
  font-size: 30px;
  font-weight: 650;
  letter-spacing: -0.035em;
}
.sub {
  margin: 4px 0 0;
}
.head .btn {
  display: inline-flex;
  gap: 7px;
}
.error-banner {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 14px;
}
.panel {
  padding: 16px 16px 8px;
  min-height: 220px;
  transition: box-shadow var(--dur-ui) var(--ease-out);
}
.panel:hover {
  box-shadow: var(--shadow-lg);
}
.panel-h {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.panel-title {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text);
}
.panel h2 {
  margin: 0;
  font-size: 15px;
  font-weight: 650;
  letter-spacing: -0.02em;
}
ul {
  list-style: none;
  margin: 0;
  padding: 0;
}
li {
  display: flex;
  gap: 10px;
  padding: 12px 6px;
  border-top: 1px solid var(--border);
  transition: background var(--dur-ui) var(--ease-out);
  border-radius: 8px;
  margin: 0 -4px;
}
li:hover {
  background: rgba(0, 0, 0, 0.02);
}
.row-ico {
  width: 32px;
  height: 32px;
  border-radius: 9px;
  background: var(--bg);
  border: 1px solid var(--border);
  display: grid;
  place-items: center;
  color: var(--text-secondary);
  flex-shrink: 0;
}
.row-body {
  min-width: 0;
  flex: 1;
}
.row-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.row-main strong {
  font-size: 14px;
  font-weight: 560;
  letter-spacing: -0.01em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.meta {
  margin-top: 4px;
  font-size: 12px;
}
.empty {
  padding: 36px 8px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}
.empty-glyph {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: var(--bg);
  border: 1px solid var(--border);
  display: grid;
  place-items: center;
  color: var(--text-tertiary);
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  word-break: break-all;
  white-space: normal;
}
.skel-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 14px;
}
.skel-panel {
  padding: 18px;
  min-height: 180px;
}
</style>
