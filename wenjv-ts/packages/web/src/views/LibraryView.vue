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
      <div class="head-actions">
        <button class="btn btn-secondary" type="button" @click="openImport('legacy')">
          <Icon name="folder" :size="15" />
          <span>从旧库导入</span>
        </button>
        <button class="btn btn-primary" type="button" @click="openImport('batch')">
          <Icon name="upload" :size="15" />
          <span>批量导入</span>
        </button>
        <button class="btn btn-secondary" type="button" :disabled="loading" @click="() => reload()">
          <Icon name="refresh" :size="15" :spin="loading" />
          <span>{{ loading ? '刷新中' : '刷新' }}</span>
        </button>
      </div>
    </header>

    <ImportModal
      :show="showImportModal"
      :initial-tab="importTab"
      @close="showImportModal = false"
      @imported="handleImported"
      @go-wiki="goToWiki"
    />

    <div v-if="error" class="error-banner">
      <Icon name="x" :size="15" />
      <span>{{ error }}</span>
    </div>

    <!-- Top Filter & Search Bar -->
    <div class="tag-bar card">
      <div class="tag-bar-top">
        <div class="search-box">
          <Icon name="search" :size="14" />
          <input
            v-model="searchQuery"
            type="search"
            class="lib-search-input"
            placeholder="搜索标题、文件名、链接或标签…"
          />
          <button
            v-if="searchQuery"
            type="button"
            class="search-clear-btn"
            aria-label="清除搜索"
            @click="searchQuery = ''"
          >
            <Icon name="x" :size="12" />
          </button>
        </div>
        <div class="type-pills" role="tablist" aria-label="按类型筛选">
          <button
            v-for="tp in typeFilters"
            :key="tp.value"
            type="button"
            class="type-pill"
            :class="{ active: activeType === tp.value }"
            @click="activeType = tp.value"
          >
            {{ tp.label }}
            <span class="tag-count">{{ tp.value === 'all' ? totalCount : byType(tp.value).length }}</span>
          </button>
        </div>
      </div>

      <div class="tag-bar-bottom">
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
          <span v-if="tagActionMessage" class="backfill-msg">{{ tagActionMessage }}</span>
          <span class="muted" style="font-size: 12px">切换页签自动保留筛选与进度</span>
        </div>
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
      <section v-for="sec in visibleSections" :key="sec.type" class="card panel">
        <div class="panel-h">
          <div class="panel-title">
            <Icon :name="sec.icon" :size="16" />
            <h2>{{ sec.label }}</h2>
          </div>
          <span class="badge">{{ filteredByType(sec.type).length }} / {{ byType(sec.type).length }}</span>
        </div>
        <div v-if="!filteredByType(sec.type).length" class="empty muted">
          <div class="empty-glyph"><Icon :name="sec.rowIcon" :size="20" /></div>
          {{ activeTag || searchQuery ? `未找到匹配的${sec.label}` : `暂无${sec.label}` }}
        </div>
        <ul v-else>
          <li
            v-for="item in filteredByType(sec.type)"
            :key="item.id"
            class="resource-row"
            @click="openDetail(item)"
          >
            <div class="row-ico">
              <img
                v-if="isImageResource(item) && auth.token"
                :src="resourceContentUrl(item.id, auth.token)"
                class="row-thumb"
                loading="lazy"
                :alt="item.filename || item.title || '图片'"
              />
              <Icon v-else :name="isImageResource(item) ? 'image' : sec.rowIcon" :size="16" />
            </div>
            <div class="row-body">
              <div class="row-main">
                <strong>{{ item.title || item.filename || item.source_url }}</strong>
                <div style="display: inline-flex; align-items: center; gap: 6px">
                  <StatusDot :status="item.status || '-'" />
                  <button
                    class="tag-edit-btn"
                    title="删除资源"
                    @click.stop="askDeleteResource(item)"
                  >
                    <Icon name="x" :size="12" />
                  </button>
                </div>
              </div>
              <div class="muted meta" :class="{ mono: sec.type === 'link' }">
                {{ sec.type === 'link' ? item.source_url : (item.filename || formatDate(item.created_at)) }}
              </div>
              <div v-if="item.status === 'failed' && item.error_message" class="item-err-line" :title="item.error_message">
                失败原因：{{ item.error_message }}
              </div>

              <div v-if="editingKey === item.id" class="inline-tag-edit" @click.stop>
                <input
                  v-model="editingInput"
                  ref="tagInputRef"
                  class="inline-tag-input"
                  placeholder="标签，空格/逗号分隔..."
                  @keydown.enter="saveTags(item)"
                  @keydown.esc="cancelEdit"
                />
                <button class="btn btn-xs btn-primary" :disabled="savingTags" @click="saveTags(item)">保存</button>
                <button class="btn btn-xs btn-secondary" @click="cancelEdit">取消</button>
              </div>
              <div v-else class="item-tags">
                <span
                  v-for="t in item.tags || []"
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
                  @click.stop="startEdit(item)"
                >
                  <Icon name="tag" :size="11" />
                </button>
              </div>
            </div>
          </li>
        </ul>
      </section>
    </div>

    <!-- Resource Detail Modal -->
    <Teleport to="body">
      <div v-if="selectedResource" class="lib-modal-backdrop" @click.self="closeDetail">
        <div class="lib-detail-dialog" role="dialog" aria-modal="true" aria-label="资源详情">
          <header class="detail-head">
            <div class="detail-title-wrap">
              <h4>{{ selectedResource.title || selectedResource.filename || selectedResource.source_url }}</h4>
              <StatusDot :status="selectedResource.status || '-'" />
            </div>
            <button type="button" class="detail-close" aria-label="关闭" @click="closeDetail">×</button>
          </header>
          <div class="detail-body">
            <div class="detail-kv"><span>类型</span><strong>{{ selectedResource.type }}</strong></div>
            <div class="detail-kv"><span>创建时间</span><strong>{{ formatDate(selectedResource.created_at) }}</strong></div>
            <div v-if="selectedResource.filename" class="detail-kv">
              <span>文件名</span><code class="mono">{{ selectedResource.filename }}</code>
            </div>
            <div v-if="selectedResource.source_url" class="detail-kv">
              <span>来源链接</span>
              <a :href="selectedResource.source_url" target="_blank" rel="noopener noreferrer" class="mono">
                {{ selectedResource.source_url }}
              </a>
            </div>
            <div v-if="selectedResource.error_message" class="detail-err-box">
              <strong>错误详情：</strong>{{ selectedResource.error_message }}
            </div>
            <div class="detail-kv">
              <span>标签</span>
              <div class="item-tags" style="margin-top: 0">
                <span v-for="t in selectedResource.tags || []" :key="t" class="tag-badge">#{{ t }}</span>
                <span v-if="!selectedResource.tags?.length" class="muted" style="font-size: 12px">无标签</span>
              </div>
            </div>
            <div v-if="isImageResource(selectedResource) && auth.token" class="detail-kv">
              <span>图片预览</span>
              <div class="detail-image-wrap">
                <img
                  :src="resourceContentUrl(selectedResource.id, auth.token)"
                  class="detail-image-preview"
                  :alt="selectedResource.filename || selectedResource.title || '图片预览'"
                />
              </div>
            </div>
            <div v-if="detailLoading" class="muted" style="font-size: 12px">加载提取文本中…</div>
            <div v-else-if="detailContent" class="detail-kv">
              <span>已提取 / 索引文本</span>
              <pre class="detail-content-box">{{ detailContent }}</pre>
            </div>
            <div v-if="reingestMessage" class="detail-info-box">{{ reingestMessage }}</div>
          </div>
          <footer class="detail-foot">
            <button
              v-if="selectedResource.type === 'file'"
              type="button"
              class="btn btn-secondary btn-sm"
              :disabled="reingesting"
              @click="triggerReingest(selectedResource, 'formula')"
            >
              {{ reingesting ? '入队中…' : '公式 OCR 重索引' }}
            </button>
            <button
              type="button"
              class="btn btn-secondary btn-sm"
              :disabled="reingesting"
              @click="triggerReingest(selectedResource, 'auto')"
            >
              重新索引
            </button>
            <button type="button" class="btn btn-secondary btn-sm" @click="askDeleteResource(selectedResource)">
              删除资源
            </button>
            <button type="button" class="btn btn-primary btn-sm" @click="closeDetail">关闭</button>
          </footer>
        </div>
      </div>

      <!-- Non-blocking Delete Confirm Dialog -->
      <div v-if="pendingDeleteItem" class="lib-modal-backdrop" @click.self="pendingDeleteItem = null">
        <div class="lib-confirm-dialog" role="dialog" aria-modal="true">
          <h4>删除资源</h4>
          <p>
            确定删除 <strong>{{ pendingDeleteItem.title || pendingDeleteItem.filename || pendingDeleteItem.source_url }}</strong>？该操作会同步移除对应分块与索引，不可恢复。
          </p>
          <div class="detail-foot">
            <button type="button" class="btn btn-secondary btn-sm" :disabled="deleting" @click="pendingDeleteItem = null">
              取消
            </button>
            <button type="button" class="btn btn-danger-solid btn-sm" :disabled="deleting" @click="confirmDeleteResource">
              {{ deleting ? '删除中…' : '确认删除' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onActivated, onDeactivated, onBeforeUnmount, computed, nextTick } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { useLibraryStore } from '../stores/library'
import { useAuthStore } from '../stores/auth'
import {
  getResourceDetail,
  reingestResource,
  resourceContentUrl,
  type ResourceItem,
  type ResourceType,
} from '../api/client.js'
import Icon from '../components/Icon.vue'
import StatusDot from '../components/StatusDot.vue'
import ImportModal from '../components/ImportModal.vue'

defineOptions({ name: 'LibraryView' })

interface SectionDef {
  type: ResourceType
  label: string
  icon: string
  rowIcon: string
}

const sections: SectionDef[] = [
  { type: 'file', label: '文件', icon: 'file', rowIcon: 'file' },
  { type: 'note', label: '笔记', icon: 'note', rowIcon: 'note' },
  { type: 'link', label: '链接', icon: 'globe', rowIcon: 'link' },
]

const typeFilters: Array<{ value: 'all' | ResourceType; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'file', label: '文件' },
  { value: 'note', label: '笔记' },
  { value: 'link', label: '链接' },
]

const IMAGE_EXT_RE = /\.(png|jpe?g|webp|gif|bmp|tiff?)$/i

function isImageResource(item: ResourceItem | null | undefined): boolean {
  if (!item || item.type !== 'file') return false
  const name = item.original_filename || item.filename || item.title || ''
  return IMAGE_EXT_RE.test(name)
}

const router = useRouter()
const auth = useAuthStore()
const library = useLibraryStore()
const {
  loading,
  error,
  resources,
  totalCount,
  tagSummary,
  activeTag,
  activeType,
  searchQuery,
  selectedResource,
} = storeToRefs(library)

const tagActionMessage = ref('')
const showImportModal = ref(false)
const importTab = ref<'batch' | 'legacy'>('batch')
let pollTimer: ReturnType<typeof setTimeout> | null = null
let isViewActive = true

const editingKey = ref<number | null>(null)
const editingInput = ref('')
const savingTags = ref(false)
const tagInputRef = ref<HTMLInputElement | HTMLInputElement[] | null>(null)

const pendingDeleteItem = ref<ResourceItem | null>(null)
const deleting = ref(false)
const detailContent = ref('')
const detailLoading = ref(false)
const reingesting = ref(false)
const reingestMessage = ref('')

const hasAny = computed(() => resources.value.length > 0)
const visibleSections = computed(() => {
  if (activeType.value === 'all') return sections
  return sections.filter((s) => s.type === activeType.value)
})

function byType(type: ResourceType): ResourceItem[] {
  return resources.value.filter((r) => r.type === type)
}

function filteredByType(type: ResourceType): ResourceItem[] {
  let list = byType(type)
  if (activeTag.value) {
    const targetTag = activeTag.value
    list = list.filter((item) => (item.tags || []).includes(targetTag))
  }
  const q = searchQuery.value.trim().toLowerCase()
  if (q) {
    list = list.filter((item) => {
      const hay = [
        item.title,
        item.filename,
        item.original_filename,
        item.source_url,
        ...(item.tags || []),
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      return hay.includes(q)
    })
  }
  return list
}

function startEdit(item: ResourceItem) {
  editingKey.value = item.id
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

async function saveTags(item: ResourceItem) {
  if (!item.id) return
  savingTags.value = true
  try {
    const rawList = editingInput.value
      .split(/[,，\s]+/)
      .map((s) => s.trim().replace(/^#+/, ''))
      .filter(Boolean)
    await library.saveItemTags(item.id, rawList)
    cancelEdit()
  } catch (err) {
    library.error = '更新标签失败: ' + (err instanceof Error ? err.message : String(err))
  } finally {
    savingTags.value = false
  }
}

async function openDetail(item: ResourceItem) {
  library.selectedResourceId = item.id
  detailContent.value = ''
  reingestMessage.value = ''
  detailLoading.value = true
  try {
    const detail = await getResourceDetail(auth.token, item.id)
    if (library.selectedResourceId === item.id) {
      detailContent.value = detail?.content || ''
    }
  } catch {
    detailContent.value = ''
  } finally {
    detailLoading.value = false
  }
}

async function triggerReingest(item: ResourceItem, mode: 'auto' | 'formula' = 'auto') {
  if (!item?.id || reingesting.value) return
  reingesting.value = true
  reingestMessage.value = ''
  try {
    await reingestResource(auth.token, item.id, mode)
    reingestMessage.value = mode === 'formula'
      ? '已加入公式 + 文本 OCR 队列，稍后自动更新索引。'
      : '已加入重新索引队列，稍后自动更新。'
    await reload({ silent: true })
  } catch (err) {
    reingestMessage.value = '入队失败: ' + (err instanceof Error ? err.message : String(err))
  } finally {
    reingesting.value = false
  }
}

function closeDetail() {
  library.selectedResourceId = null
  detailContent.value = ''
  reingestMessage.value = ''
}

function askDeleteResource(item: ResourceItem) {
  pendingDeleteItem.value = item
}

async function confirmDeleteResource() {
  if (!pendingDeleteItem.value || deleting.value) return
  deleting.value = true
  try {
    await library.removeItem(pendingDeleteItem.value.id)
    pendingDeleteItem.value = null
  } catch (err) {
    library.error = '删除资源失败: ' + (err instanceof Error ? err.message : String(err))
  } finally {
    deleting.value = false
  }
}

function formatDate(v: string | null | undefined) {
  if (!v) return ''
  try {
    const d = new Date(v)
    if (Number.isNaN(d.getTime())) return String(v)
    return d.toLocaleString()
  } catch {
    return String(v)
  }
}

function openImport(tab: 'batch' | 'legacy') {
  importTab.value = tab
  showImportModal.value = true
}

function goToWiki() {
  showImportModal.value = false
  router.push('/wiki')
}

async function handleImported() {
  await reload()
}

function clearPollTimer() {
  if (pollTimer) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

function schedulePollIfPending() {
  clearPollTimer()
  if (isViewActive && library.hasActiveJobs) {
    pollTimer = setTimeout(() => {
      void reload({ silent: true })
    }, 2500)
  }
}

async function reload(opts: { silent?: boolean } = {}) {
  await library.reload(opts)
  schedulePollIfPending()
}

onMounted(() => {
  isViewActive = true
  void reload({ silent: library.loaded })
})

onActivated(() => {
  isViewActive = true
  void reload({ silent: true })
})

onDeactivated(() => {
  isViewActive = false
  clearPollTimer()
})

onBeforeUnmount(() => {
  isViewActive = false
  clearPollTimer()
})
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
.head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
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
  flex-direction: column;
  gap: 10px;
  padding: 12px 14px;
  margin-bottom: 18px;
}
.tag-bar-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.search-box {
  flex: 1;
  min-width: 220px;
  max-width: 420px;
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 6px 10px;
  border-radius: 9px;
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text-secondary);
}
.lib-search-input {
  flex: 1;
  border: none;
  background: transparent;
  outline: none;
  font-size: 13px;
  color: var(--text);
  min-width: 0;
}
.search-clear-btn {
  border: none;
  background: transparent;
  padding: 2px;
  color: var(--text-tertiary);
  display: inline-flex;
  align-items: center;
}
.type-pills {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.type-pill {
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-secondary);
  border-radius: 8px;
  font-size: 12px;
  font-weight: 500;
  padding: 4px 10px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.type-pill.active {
  background: var(--accent-soft);
  border-color: rgba(0, 113, 227, 0.35);
  color: var(--accent);
  font-weight: 600;
}
.tag-bar-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding-top: 8px;
  border-top: 1px solid var(--border);
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
.resource-row {
  cursor: pointer;
}
.item-err-line {
  margin-top: 4px;
  font-size: 11.5px;
  color: var(--danger);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.lib-modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 250;
  background: rgba(15, 23, 42, 0.42);
  backdrop-filter: blur(3px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}
.lib-detail-dialog,
.lib-confirm-dialog {
  width: min(560px, 94vw);
  max-height: 86vh;
  overflow-y: auto;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  box-shadow: var(--shadow-lg);
  padding: 18px 20px;
}
.lib-confirm-dialog p {
  margin: 8px 0 16px;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.55;
}
.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border);
}
.detail-title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.detail-title-wrap h4,
.lib-confirm-dialog h4 {
  margin: 0;
  font-size: 15.5px;
  font-weight: 650;
  word-break: break-word;
}
.detail-close {
  border: none;
  background: transparent;
  font-size: 20px;
  color: var(--text-secondary);
  line-height: 1;
}
.detail-body {
  padding: 14px 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.detail-kv {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 13px;
}
.detail-kv > span {
  font-size: 11.5px;
  color: var(--text-tertiary);
}
.detail-err-box {
  padding: 8px 10px;
  border-radius: 8px;
  background: #fff5f5;
  border: 1px solid rgba(255, 59, 48, 0.25);
  color: #b91c1c;
  font-size: 12.5px;
  word-break: break-word;
}
.detail-foot {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}
.detail-content-box {
  margin: 4px 0 0;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--bg);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 220px;
  overflow-y: auto;
}
.detail-info-box {
  padding: 8px 10px;
  border-radius: 8px;
  background: #f0f9ff;
  border: 1px solid rgba(2, 132, 199, 0.25);
  color: #0369a1;
  font-size: 12.5px;
}
.row-thumb {
  width: 30px;
  height: 30px;
  border-radius: 7px;
  object-fit: cover;
  display: block;
}
.detail-image-wrap {
  margin-top: 4px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--bg);
  padding: 8px;
  display: flex;
  justify-content: center;
}
.detail-image-preview {
  max-width: 100%;
  max-height: 260px;
  border-radius: 6px;
  object-fit: contain;
}
.btn-danger-solid {
  background: var(--danger);
  color: #fff;
}
</style>
