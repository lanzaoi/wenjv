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

    <!-- Top Tag Filter Bar -->
    <div class="tag-bar card">
      <div class="tag-bar-left">
        <div class="tag-bar-label">
          <Icon name="tag" :size="14" />
          <span>分类标签</span>
        </div>
        <div class="tag-pills">
          <button
            class="tag-pill"
            :class="{ active: !activeTag }"
            type="button"
            @click="activeTag = null"
          >
            全部 <span class="tag-count">{{ totalCount }}</span>
          </button>
          <button
            v-for="t in tagSummary"
            :key="t.name"
            class="tag-pill"
            :class="{ active: activeTag === t.name }"
            type="button"
            @click="activeTag = activeTag === t.name ? null : t.name"
          >
            #{{ t.name }} <span class="tag-count">{{ t.count }}</span>
          </button>
        </div>
      </div>
      <div class="tag-bar-right">
        <span v-if="backfillMessage" class="backfill-msg">{{ backfillMessage }}</span>
        <button
          class="btn btn-secondary btn-sm backfill-btn"
          type="button"
          :disabled="backfilling"
          title="扫描未打标文档并利用语义自动补齐标签"
          @click="triggerBackfill"
        >
          <Icon name="sparkles" :size="13" :spin="backfilling" />
          <span>{{ backfilling ? '补标中...' : '一键补标' }}</span>
        </button>
      </div>
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
      <!-- Files section -->
      <section class="card panel">
        <div class="panel-h">
          <div class="panel-title">
            <Icon name="file" :size="16" />
            <h2>文件</h2>
          </div>
          <span class="badge">{{ filteredFiles.length }} / {{ files.total || 0 }}</span>
        </div>
        <div v-if="!filteredFiles.length" class="empty muted">
          <div class="empty-glyph"><Icon name="file" :size="20" /></div>
          {{ activeTag ? `无带有 #${activeTag} 的文件` : '暂无文件' }}
        </div>
        <ul v-else>
          <li v-for="f in filteredFiles" :key="f.file_url + f.filename">
            <div class="row-ico"><Icon name="file" :size="16" /></div>
            <div class="row-body">
              <div class="row-main">
                <strong>{{ f.filename }}</strong>
                <StatusDot :status="f.status" />
              </div>
              <div class="muted meta">{{ formatDate(f.created_at) }}</div>

              <!-- Tags display & inline edit -->
              <div v-if="editingKey === getItemKey(f, 'file')" class="inline-tag-edit" @click.stop>
                <input
                  v-model="editingInput"
                  ref="tagInputRef"
                  class="inline-tag-input"
                  placeholder="标签，空格/逗号分隔..."
                  @keydown.enter="saveTags(f, 'file')"
                  @keydown.esc="cancelEdit"
                />
                <button class="btn btn-xs btn-primary" :disabled="savingTags" @click="saveTags(f, 'file')">保存</button>
                <button class="btn btn-xs btn-secondary" @click="cancelEdit">取消</button>
              </div>
              <div v-else class="item-tags">
                <span
                  v-for="t in f.tags || []"
                  :key="t"
                  class="tag-badge"
                  :class="{ active: activeTag === t }"
                  @click.stop="activeTag = activeTag === t ? null : t"
                >
                  #{{ t }}
                </span>
                <button
                  v-if="f.id"
                  class="tag-edit-btn"
                  title="编辑标签"
                  @click.stop="startEdit(f, 'file')"
                >
                  <Icon name="tag" :size="11" />
                </button>
              </div>
            </div>
          </li>
        </ul>
      </section>

      <!-- Notes section -->
      <section class="card panel">
        <div class="panel-h">
          <div class="panel-title">
            <Icon name="note" :size="16" />
            <h2>笔记</h2>
          </div>
          <span class="badge">{{ filteredNotes.length }} / {{ notes.total || 0 }}</span>
        </div>
        <div v-if="!filteredNotes.length" class="empty muted">
          <div class="empty-glyph"><Icon name="note" :size="20" /></div>
          {{ activeTag ? `无带有 #${activeTag} 的笔记` : '暂无笔记' }}
        </div>
        <ul v-else>
          <li v-for="n in filteredNotes" :key="n.id">
            <div class="row-ico"><Icon name="note" :size="16" /></div>
            <div class="row-body">
              <div class="row-main">
                <strong>{{ n.title }}</strong>
                <StatusDot :status="n.status || '-'" />
              </div>
              <div class="muted meta">{{ n.filename }}</div>

              <!-- Tags display & inline edit -->
              <div v-if="editingKey === getItemKey(n, 'note')" class="inline-tag-edit" @click.stop>
                <input
                  v-model="editingInput"
                  ref="tagInputRef"
                  class="inline-tag-input"
                  placeholder="标签，空格/逗号分隔..."
                  @keydown.enter="saveTags(n, 'note')"
                  @keydown.esc="cancelEdit"
                />
                <button class="btn btn-xs btn-primary" :disabled="savingTags" @click="saveTags(n, 'note')">保存</button>
                <button class="btn btn-xs btn-secondary" @click="cancelEdit">取消</button>
              </div>
              <div v-else class="item-tags">
                <span
                  v-for="t in n.tags || []"
                  :key="t"
                  class="tag-badge"
                  :class="{ active: activeTag === t }"
                  @click.stop="activeTag = activeTag === t ? null : t"
                >
                  #{{ t }}
                </span>
                <button
                  class="tag-edit-btn"
                  title="编辑标签"
                  @click.stop="startEdit(n, 'note')"
                >
                  <Icon name="tag" :size="11" />
                </button>
              </div>
            </div>
          </li>
        </ul>
      </section>

      <!-- Links section -->
      <section class="card panel">
        <div class="panel-h">
          <div class="panel-title">
            <Icon name="globe" :size="16" />
            <h2>链接</h2>
          </div>
          <span class="badge">{{ filteredLinks.length }} / {{ links.total || 0 }}</span>
        </div>
        <div v-if="!filteredLinks.length" class="empty muted">
          <div class="empty-glyph"><Icon name="link" :size="20" /></div>
          {{ activeTag ? `无带有 #${activeTag} 的链接` : '暂无链接' }}
        </div>
        <ul v-else>
          <li v-for="l in filteredLinks" :key="l.id">
            <div class="row-ico"><Icon name="link" :size="16" /></div>
            <div class="row-body">
              <div class="row-main">
                <strong>{{ l.title || l.url }}</strong>
                <StatusDot :status="l.status" />
              </div>
              <div class="muted mono meta">{{ l.url }}</div>

              <!-- Tags display & inline edit -->
              <div v-if="editingKey === getItemKey(l, 'link')" class="inline-tag-edit" @click.stop>
                <input
                  v-model="editingInput"
                  ref="tagInputRef"
                  class="inline-tag-input"
                  placeholder="标签，空格/逗号分隔..."
                  @keydown.enter="saveTags(l, 'link')"
                  @keydown.esc="cancelEdit"
                />
                <button class="btn btn-xs btn-primary" :disabled="savingTags" @click="saveTags(l, 'link')">保存</button>
                <button class="btn btn-xs btn-secondary" @click="cancelEdit">取消</button>
              </div>
              <div v-else class="item-tags">
                <span
                  v-for="t in l.tags || []"
                  :key="t"
                  class="tag-badge"
                  :class="{ active: activeTag === t }"
                  @click.stop="activeTag = activeTag === t ? null : t"
                >
                  #{{ t }}
                </span>
                <button
                  class="tag-edit-btn"
                  title="编辑标签"
                  @click.stop="startEdit(l, 'link')"
                >
                  <Icon name="tag" :size="11" />
                </button>
              </div>
            </div>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed, nextTick } from 'vue'
import { useAuthStore } from '../stores/auth'
import {
  listFiles,
  listNotes,
  listLinks,
  getTags,
  updateResourceTags,
  backfillTags,
} from '../api/client'
import Icon from '../components/Icon.vue'
import StatusDot from '../components/StatusDot.vue'

const auth = useAuthStore()
const loading = ref(false)
const error = ref('')
const files = ref({ files: [], total: 0 })
const notes = ref({ notes: [], total: 0 })
const links = ref({ links: [], total: 0 })
const tagSummary = ref([])
const activeTag = ref(null)

const backfilling = ref(false)
const backfillMessage = ref('')

const editingKey = ref(null)
const editingInput = ref('')
const savingTags = ref(false)
const tagInputRef = ref(null)

const hasAny = computed(() => {
  return (
    (files.value.files?.length || 0) +
      (notes.value.notes?.length || 0) +
      (links.value.links?.length || 0) >
    0
  )
})

const totalCount = computed(() => {
  return (files.value.total || 0) + (notes.value.total || 0) + (links.value.total || 0)
})

const filteredFiles = computed(() => {
  const list = files.value.files || []
  if (!activeTag.value) return list
  return list.filter((f) => (f.tags || []).includes(activeTag.value))
})

const filteredNotes = computed(() => {
  const list = notes.value.notes || []
  if (!activeTag.value) return list
  return list.filter((n) => (n.tags || []).includes(activeTag.value))
})

const filteredLinks = computed(() => {
  const list = links.value.links || []
  if (!activeTag.value) return list
  return list.filter((l) => (l.tags || []).includes(activeTag.value))
})

function getItemKey(item, type) {
  return `${type}:${item.id || item.filename || item.url}`
}

function startEdit(item, type) {
  editingKey.value = getItemKey(item, type)
  editingInput.value = (item.tags || []).join(', ')
  nextTick(() => {
    if (tagInputRef.value) {
      if (Array.isArray(tagInputRef.value)) {
        tagInputRef.value[0]?.focus()
      } else {
        tagInputRef.value.focus()
      }
    }
  })
}

function cancelEdit() {
  editingKey.value = null
  editingInput.value = ''
}

async function saveTags(item, type) {
  if (!item.id) return
  savingTags.value = true
  try {
    const rawList = editingInput.value
      .split(/[,，\s]+/)
      .map((s) => s.trim().replace(/^#+/, ''))
      .filter(Boolean)
    const res = await updateResourceTags(auth.token, type, item.id, rawList)
    item.tags = res.tags || []
    cancelEdit()
    await refreshTags()
  } catch (err) {
    error.value = '更新标签失败: ' + err.message
  } finally {
    savingTags.value = false
  }
}

async function triggerBackfill() {
  backfilling.value = true
  backfillMessage.value = ''
  try {
    const res = await backfillTags(auth.token)
    backfillMessage.value = `已为 ${res.enqueued_count || 0} 个资源自动补齐标签`
    await reload()
    setTimeout(() => {
      backfillMessage.value = ''
    }, 4000)
  } catch (err) {
    error.value = '一键补标失败: ' + err.message
  } finally {
    backfilling.value = false
  }
}

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

async function refreshTags() {
  try {
    const res = await getTags(auth.token)
    tagSummary.value = res.tags || []
  } catch (e) {
    // Silently log or ignore
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
    await refreshTags()
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
  margin-bottom: 14px;
}

/* Tag Bar */
.tag-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 14px;
  margin-bottom: 18px;
  flex-wrap: wrap;
}
.tag-bar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.tag-bar-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
}
.tag-pills {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.tag-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px;
  font-size: 12px;
  border-radius: 9999px;
  background: var(--bg);
  border: 1px solid var(--border);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--dur-ui) var(--ease-out);
}
.tag-pill:hover {
  background: rgba(0, 0, 0, 0.05);
  color: var(--text);
}
.tag-pill.active {
  background: var(--text);
  color: #fff;
  border-color: var(--text);
}
.tag-count {
  font-size: 10px;
  opacity: 0.75;
}
.tag-bar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}
.backfill-msg {
  font-size: 12px;
  color: var(--accent);
}
.backfill-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

/* Grid & Panels */
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

/* Item tags & inline editor */
.item-tags {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 6px;
  flex-wrap: wrap;
}
.tag-badge {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  font-size: 11px;
  border-radius: 4px;
  background: rgba(0, 0, 0, 0.04);
  color: var(--text-secondary);
  border: 1px solid rgba(0, 0, 0, 0.04);
  cursor: pointer;
  transition: all var(--dur-ui) var(--ease-out);
}
.tag-badge:hover,
.tag-badge.active {
  background: rgba(0, 0, 0, 0.08);
  color: var(--text);
}
.tag-badge.active {
  border-color: var(--text);
  font-weight: 500;
}
.tag-edit-btn {
  background: none;
  border: none;
  padding: 2px 4px;
  cursor: pointer;
  color: var(--text-tertiary);
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
}
.tag-edit-btn:hover {
  color: var(--text);
  background: rgba(0, 0, 0, 0.05);
}
.inline-tag-edit {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
}
.inline-tag-input {
  font-size: 12px;
  padding: 3px 8px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  outline: none;
  width: 180px;
}
.inline-tag-input:focus {
  border-color: var(--accent);
}
.btn-xs {
  padding: 2px 8px;
  font-size: 11px;
  border-radius: 5px;
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
