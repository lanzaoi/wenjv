<template>
  <div class="wiki-view-layout">
    <!-- UI Notification Toast -->
    <transition name="toast-fade">
      <div v-if="toast.message" class="wiki-toast" :class="toast.type" role="alert">
        <span class="toast-dot" />
        <span class="toast-text">{{ toast.message }}</span>
        <button type="button" class="toast-close" @click="clearToast">✕</button>
      </div>
    </transition>

    <!-- Left Tree Navigation -->
    <wiki-tree
      :tree="wikiStore.tree"
      :current-id="wikiStore.currentPage?.id"
      @select="handleSelectPage"
      @create="handleCreatePage"
      @delete="handleDeletePage"
      @open-graph="showGraphModal = true"
    />

    <!-- Middle Notion-style Editor -->
    <wiki-editor
      ref="editorRef"
      :page="wikiStore.currentPage"
      :saving="wikiStore.saving"
      :dirty="wikiStore.dirty"
      :all-pages="allPagesFlattened"
      @update="handleUpdatePage"
      @toc-change="currentToc = $event"
      @navigate-page="handleSelectPage"
      @create-page="handleQuickCreatePage"
    />

    <!-- Right Sidebar (TOC, Backlinks, Diff & Copilot) -->
    <wiki-sidebar
      v-if="wikiStore.currentPage"
      :page-id="wikiStore.currentPage?.id"
      :backlinks="wikiStore.currentPage?.backlinks || []"
      :toc="currentToc"
      @open-page="handleSelectPage"
      @rollback="handleRollback"
      @scroll-to-heading="handleScrollToHeading"
    />

    <!-- Global Knowledge Graph Modal -->
    <wiki-graph-modal
      v-if="showGraphModal"
      @close="showGraphModal = false"
      @select-page="handleSelectPage"
    />

    <!-- Ctrl+K Quick Command & Search Palette -->
    <wiki-command-modal
      :is-open="showCommandModal"
      @close="showCommandModal = false"
      @select-page="handleSelectPage"
      @create-page="handleQuickCreatePage"
    />
  </div>
</template>

<script setup>
import { onMounted, onBeforeUnmount, computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useWikiStore } from '../stores/wiki'
import WikiTree from '../components/wiki/WikiTree.vue'
import WikiEditor from '../components/wiki/WikiEditor.vue'
import WikiSidebar from '../components/wiki/WikiSidebar.vue'
import WikiGraphModal from '../components/wiki/WikiGraphModal.vue'
import WikiCommandModal from '../components/wiki/WikiCommandModal.vue'

const route = useRoute()
const router = useRouter()
const wikiStore = useWikiStore()
const editorRef = ref(null)
const showGraphModal = ref(false)
const showCommandModal = ref(false)
const currentToc = ref([])

const toast = ref({ message: '', type: 'info', timer: null })

function showToast(message, type = 'info', duration = 3500) {
  if (toast.value.timer) clearTimeout(toast.value.timer)
  toast.value = {
    message,
    type,
    timer: setTimeout(() => {
      toast.value.message = ''
      toast.value.timer = null
    }, duration),
  }
}

function clearToast() {
  if (toast.value.timer) clearTimeout(toast.value.timer)
  toast.value.message = ''
  toast.value.timer = null
}

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleGlobalKeydown)
  clearToast()
})

function handleGlobalKeydown(e) {
  if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
    e.preventDefault()
    showCommandModal.value = !showCommandModal.value
  }
}

onMounted(async () => {
  window.addEventListener('keydown', handleGlobalKeydown)
  try {
    const tree = await wikiStore.loadTree()
    const targetId = route.params.id ? Number(route.params.id) : (tree && tree.length > 0 ? tree[0].id : null)
    if (targetId) {
      if (!route.params.id) {
        router.replace({ name: 'wiki', params: { id: targetId } })
      }
      await wikiStore.openPage(targetId)
    }
  } catch (e) {
    showToast(e.message || '加载知识库失败，请检查网络或重新登录', 'error')
    console.error('Failed to init wiki view', e)
  }
})

watch(
  () => route.params.id,
  async (newId) => {
    if (newId) {
      const numId = Number(newId)
      if (wikiStore.currentPage?.id !== numId) {
        try {
          await wikiStore.openPage(numId)
        } catch (e) {
          showToast(e.message || '切换页面失败', 'error')
        }
      }
    }
  }
)

const allPagesFlattened = computed(() => {
  const out = []
  function traverse(nodes) {
    for (const n of nodes) {
      out.push({ id: n.id, title: n.title, slug: n.slug })
      if (n.children && n.children.length) {
        traverse(n.children)
      }
    }
  }
  traverse(wikiStore.tree)
  return out
})

async function handleSelectPage(pageId) {
  try {
    if (route.params.id !== String(pageId)) {
      router.push({ name: 'wiki', params: { id: pageId } })
    }
    await wikiStore.openPage(pageId)
  } catch (e) {
    showToast(e.message || '打开页面失败', 'error')
  }
}

async function handleQuickCreatePage(title) {
  try {
    const newPage = await wikiStore.createPage({ title: title || '未命名页面', parentId: null })
    if (newPage?.id) {
      router.push({ name: 'wiki', params: { id: newPage.id } })
      showToast(`已创建并打开页面: ${newPage.title}`, 'success', 2000)
    }
  } catch (e) {
    showToast(e.message || '快速创建页面失败', 'error')
  }
}

async function handleCreatePage({ title, parentId }) {
  try {
    const newPage = await wikiStore.createPage({ title, parentId })
    if (newPage?.id) {
      router.push({ name: 'wiki', params: { id: newPage.id } })
      showToast('已新建页面', 'success', 2000)
    }
  } catch (e) {
    showToast(e.message || '新建页面失败', 'error')
  }
}

async function handleDeletePage(pageId) {
  try {
    await wikiStore.deletePage(pageId)
    showToast('已删除页面', 'info', 2000)
    if (route.params.id === String(pageId)) {
      const nextId = wikiStore.tree.length > 0 ? wikiStore.tree[0].id : null
      if (nextId) {
        router.push({ name: 'wiki', params: { id: nextId } })
      } else {
        router.push({ name: 'wiki' })
      }
    }
  } catch (e) {
    showToast(e.message || '删除页面失败', 'error')
  }
}

function handleUpdatePage(patch) {
  wikiStore.scheduleAutoSave(patch)
}

async function handleRollback(revNo) {
  if (window.confirm(`确定要回滚到历史版本 ${revNo} 吗？`)) {
    try {
      await wikiStore.rollbackRevision(wikiStore.currentPage.id, revNo)
      showToast(`已成功回滚到版本 #${revNo}`, 'success')
    } catch (e) {
      showToast(e.message || '回滚版本失败', 'error')
    }
  }
}

function handleScrollToHeading(text) {
  editorRef.value?.scrollToHeading(text)
}
</script>

<style scoped>
.wiki-view-layout {
  position: relative;
  display: flex;
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: var(--surface, #ffffff);
}

.wiki-toast {
  position: absolute;
  top: 16px;
  right: 24px;
  z-index: 1000;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  border-radius: var(--radius-sm, 12px);
  background: #ffffff;
  color: var(--text, #1d1d1f);
  font-size: 13px;
  font-weight: 500;
  border: 1px solid var(--border, #e5e5ea);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
}

.toast-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent, #0071e3);
  flex-shrink: 0;
}

.wiki-toast.error .toast-dot {
  background: var(--danger, #ff3b30);
}

.wiki-toast.success .toast-dot {
  background: var(--success, #34c759);
}

.wiki-toast.error {
  border-color: rgba(255, 59, 48, 0.25);
  background: #fffafa;
}

.toast-close {
  border: none;
  background: transparent;
  color: var(--text-tertiary, #86868b);
  cursor: pointer;
  padding: 0 2px;
  font-size: 11px;
}
.toast-close:hover {
  color: var(--text, #1d1d1f);
}

.toast-fade-enter-active,
.toast-fade-leave-active {
  transition: opacity 180ms ease, transform 180ms ease;
}
.toast-fade-enter-from,
.toast-fade-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
