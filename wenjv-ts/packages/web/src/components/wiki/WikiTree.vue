<template>
  <aside class="wiki-tree-panel">
    <!-- Header -->
    <div class="tree-header">
      <div class="tree-title-group">
        <span class="tree-title">知识目录</span>
        <span v-if="totalCount > 0" class="tree-count">{{ totalCount }}</span>
      </div>
      <div class="tree-actions">
        <button
          type="button"
          class="icon-btn"
          :title="allExpanded ? '全部折叠' : '全部展开'"
          @click="toggleExpandAll"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="7 8 12 3 17 8" />
            <polyline points="7 16 12 21 17 16" />
          </svg>
        </button>
        <button
          type="button"
          class="icon-btn"
          title="全局知识图谱"
          @click="$emit('open-graph')"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="18" cy="5" r="3" />
            <circle cx="6" cy="12" r="3" />
            <circle cx="18" cy="19" r="3" />
            <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
            <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
          </svg>
        </button>
        <button
          type="button"
          class="icon-btn"
          title="搜索或快速跳转 (⌘K / Ctrl+K)"
          @click="$emit('open-search')"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
        </button>
        <button
          type="button"
          class="icon-btn is-primary"
          title="新建根页面"
          @click="openRootCreate"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
        </button>
      </div>
    </div>

    <!-- Filter Input -->
    <div class="tree-filter-wrap">
      <svg class="filter-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="11" cy="11" r="8" />
        <line x1="21" y1="21" x2="16.65" y2="16.65" />
      </svg>
      <input
        v-model="filterQuery"
        type="text"
        class="tree-filter-input"
        placeholder="过滤目录..."
      />
      <button
        v-if="filterQuery"
        type="button"
        class="filter-clear-btn"
        title="清空过滤"
        @click="filterQuery = ''"
      >
        ×
      </button>
    </div>

    <!-- Inline Root Creation Box -->
    <div v-if="creatingRoot" class="root-create-box">
      <input
        ref="rootCreateInputRef"
        v-model="draftRootTitle"
        type="text"
        class="root-create-input"
        placeholder="输入页面名称，回车创建..."
        @keydown.enter.prevent="submitRootCreate"
        @keydown.esc.prevent="creatingRoot = false"
      />
      <div class="root-create-actions">
        <button type="button" class="mini-ghost" @click="creatingRoot = false">取消</button>
        <button type="button" class="mini-primary" @click="submitRootCreate">创建</button>
      </div>
    </div>

    <!-- Inline Move Dialog Bar -->
    <div v-if="movingNode" class="move-panel">
      <div class="move-panel-head">
        <span>移动“{{ movingNode.title }}”</span>
        <button type="button" class="move-close" @click="movingNode = null">×</button>
      </div>
      <div class="move-row">
        <label class="move-label">目标父级</label>
        <select v-model="moveTargetParentId" class="move-select">
          <option :value="null">根目录</option>
          <option
            v-for="opt in availableParentOptions"
            :key="opt.id"
            :value="opt.id"
          >
            {{ opt.prefix }}{{ opt.title }}
          </option>
        </select>
      </div>
      <div class="move-order-row">
        <button type="button" class="order-btn" @click="nudgeSiblingOrder(-1)">上移一位</button>
        <button type="button" class="order-btn" @click="nudgeSiblingOrder(1)">下移一位</button>
        <button type="button" class="mini-primary" @click="confirmMoveParent">确定</button>
      </div>
    </div>

    <!-- Tree Content -->
    <div class="tree-scroll">
      <div v-if="loading && !tree.length" class="tree-empty">正在加载目录...</div>

      <div v-else-if="!tree.length" class="tree-empty">
        <p class="empty-msg">还没有知识页面</p>
        <button type="button" class="empty-cta" @click="openRootCreate">新建第一页</button>
      </div>

      <div v-else-if="!displayedTree.length" class="tree-empty">
        <p class="empty-msg">未找到匹配“{{ filterQuery }}”的页面</p>
      </div>

      <div v-else class="tree-nodes">
        <WikiTreeItem
          v-for="node in displayedTree"
          :key="node.id"
          :node="node"
          :depth="0"
          :current-id="currentId"
          :expanded-ids="effectiveExpandedIds"
          :confirming-delete-id="confirmingDeleteId"
          :creating-under-parent-id="creatingChildParentId"
          @select="$emit('select', $event)"
          @toggle-expand="toggleExpand"
          @request-create-child="openChildCreate"
          @submit-create-child="submitChildCreate"
          @cancel-create="creatingChildParentId = null"
          @rename="handleRename"
          @request-move="openMovePanel"
          @request-delete="confirmingDeleteId = $event"
          @confirm-delete="confirmDelete"
          @cancel-delete="confirmingDeleteId = null"
        />
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import type { WikiTreeNode } from '../../stores/wiki';
import WikiTreeItem from './WikiTreeItem.vue';

const props = defineProps<{
  tree: WikiTreeNode[];
  currentId?: number | null | undefined;
  loading?: boolean;
}>();

const emit = defineEmits<{
  (e: 'select', pageId: number): void;
  (e: 'create-page', payload: { title: string; parentId: number | null }): void;
  (e: 'rename-page', payload: { id: number; title: string }): void;
  (e: 'move-page', payload: { id: number; targetParentId: number | null; sortOrder: number }): void;
  (e: 'delete-page', pageId: number): void;
  (e: 'open-search'): void;
  (e: 'open-graph'): void;
}>();

const filterQuery = ref('');
const expandedIds = ref<Set<number>>(new Set());
const confirmingDeleteId = ref<number | null>(null);
const creatingRoot = ref(false);
const draftRootTitle = ref('');
const rootCreateInputRef = ref<HTMLInputElement | null>(null);
const creatingChildParentId = ref<number | null>(null);

const movingNode = ref<WikiTreeNode | null>(null);
const moveTargetParentId = ref<number | null>(null);

// Auto-expand root levels when tree first loads, and keep ancestors of currentId expanded
function collectAllIds(nodes: WikiTreeNode[], acc: number[] = []): number[] {
  for (const n of nodes) {
    acc.push(n.id);
    if (n.children && n.children.length > 0) {
      collectAllIds(n.children, acc);
    }
  }
  return acc;
}

function findAncestorIds(nodes: WikiTreeNode[], targetId: number, path: number[] = []): number[] | null {
  for (const n of nodes) {
    if (n.id === targetId) return path;
    if (n.children && n.children.length > 0) {
      const found = findAncestorIds(n.children, targetId, [...path, n.id]);
      if (found) return found;
    }
  }
  return null;
}

watch(
  () => props.tree,
  (nodes) => {
    if (expandedIds.value.size === 0 && nodes.length > 0) {
      const next = new Set<number>();
      for (const n of nodes) next.add(n.id);
      expandedIds.value = next;
    }
  },
  { immediate: true }
);

watch(
  () => props.currentId,
  (id) => {
    if (!id) return;
    const ancestors = findAncestorIds(props.tree, id);
    if (ancestors && ancestors.length > 0) {
      const next = new Set(expandedIds.value);
      for (const aid of ancestors) next.add(aid);
      expandedIds.value = next;
    }
  },
  { immediate: true }
);

const totalCount = computed(() => collectAllIds(props.tree).length);

const allIds = computed(() => collectAllIds(props.tree));
const allExpanded = computed(
  () => allIds.value.length > 0 && allIds.value.every((id) => expandedIds.value.has(id))
);

function filterTreeNodes(nodes: WikiTreeNode[], q: string): { nodes: WikiTreeNode[]; matchedIds: Set<number> } {
  const matchedIds = new Set<number>();
  const walk = (list: WikiTreeNode[]): WikiTreeNode[] => {
    const res: WikiTreeNode[] = [];
    for (const node of list) {
      const children = node.children ? walk(node.children) : [];
      const selfMatches = node.title.toLowerCase().includes(q);
      if (selfMatches || children.length > 0) {
        if (children.length > 0) matchedIds.add(node.id);
        res.push({ ...node, children });
      }
    }
    return res;
  };
  return { nodes: walk(nodes), matchedIds };
}

const filteredResult = computed(() => {
  const q = filterQuery.value.trim().toLowerCase();
  if (!q) return { nodes: props.tree, matchedIds: null as Set<number> | null };
  return filterTreeNodes(props.tree, q);
});

const displayedTree = computed(() => filteredResult.value.nodes);
const effectiveExpandedIds = computed(() => filteredResult.value.matchedIds ?? expandedIds.value);

function toggleExpand(pageId: number) {
  const next = new Set(expandedIds.value);
  if (next.has(pageId)) next.delete(pageId);
  else next.add(pageId);
  expandedIds.value = next;
}

function toggleExpandAll() {
  if (allExpanded.value) {
    expandedIds.value = new Set();
  } else {
    expandedIds.value = new Set(allIds.value);
  }
}

function openRootCreate() {
  confirmingDeleteId.value = null;
  creatingChildParentId.value = null;
  creatingRoot.value = true;
  draftRootTitle.value = '';
  nextTick(() => rootCreateInputRef.value?.focus());
}

function submitRootCreate() {
  const title = draftRootTitle.value.trim() || '未命名页面';
  creatingRoot.value = false;
  draftRootTitle.value = '';
  emit('create-page', { title, parentId: null });
}

function openChildCreate(parentId: number) {
  confirmingDeleteId.value = null;
  creatingRoot.value = false;
  const next = new Set(expandedIds.value);
  next.add(parentId);
  expandedIds.value = next;
  creatingChildParentId.value = parentId;
}

function submitChildCreate(payload: { parentId: number; title: string }) {
  creatingChildParentId.value = null;
  emit('create-page', { title: payload.title, parentId: payload.parentId });
}

function handleRename(payload: { id: number; title: string }) {
  emit('rename-page', payload);
}

function confirmDelete(pageId: number) {
  confirmingDeleteId.value = null;
  emit('delete-page', pageId);
}

function collectDescendantIds(node: WikiTreeNode, acc = new Set<number>()): Set<number> {
  acc.add(node.id);
  for (const ch of node.children || []) {
    collectDescendantIds(ch, acc);
  }
  return acc;
}

function flattenOptions(nodes: WikiTreeNode[], excluded: Set<number>, depth = 0): Array<{ id: number; title: string; prefix: string }> {
  const out: Array<{ id: number; title: string; prefix: string }> = [];
  for (const n of nodes) {
    if (!excluded.has(n.id)) {
      out.push({ id: n.id, title: n.title, prefix: depth > 0 ? `${'· '.repeat(depth)}` : '' });
      if (n.children && n.children.length > 0) {
        out.push(...flattenOptions(n.children, excluded, depth + 1));
      }
    }
  }
  return out;
}

const availableParentOptions = computed(() => {
  if (!movingNode.value) return [];
  const excluded = collectDescendantIds(movingNode.value);
  return flattenOptions(props.tree, excluded);
});

function openMovePanel(node: WikiTreeNode) {
  confirmingDeleteId.value = null;
  movingNode.value = node;
  moveTargetParentId.value = node.parent_id ?? null;
}

function findSiblings(nodes: WikiTreeNode[], parentId: number | null): WikiTreeNode[] {
  if (parentId === null) return nodes;
  for (const n of nodes) {
    if (n.id === parentId) return n.children || [];
    if (n.children?.length) {
      const found = findSiblings(n.children, parentId);
      if (found.length) return found;
    }
  }
  return [];
}

function nudgeSiblingOrder(delta: -1 | 1) {
  if (!movingNode.value) return;
  const node = movingNode.value;
  const siblings = findSiblings(props.tree, node.parent_id ?? null);
  const idx = siblings.findIndex((s) => s.id === node.id);
  const currentSort = node.sort_order ?? idx * 10;
  const targetSort = idx >= 0 && idx + delta >= 0 && idx + delta < siblings.length
    ? (siblings[idx + delta]!.sort_order ?? (idx + delta) * 10) + delta
    : currentSort + delta * 10;
  emit('move-page', {
    id: node.id,
    targetParentId: node.parent_id ?? null,
    sortOrder: targetSort,
  });
  movingNode.value = null;
}

function confirmMoveParent() {
  if (!movingNode.value) return;
  emit('move-page', {
    id: movingNode.value.id,
    targetParentId: moveTargetParentId.value,
    sortOrder: movingNode.value.sort_order ?? 0,
  });
  movingNode.value = null;
}
</script>

<style scoped>
.wiki-tree-panel {
  width: 264px;
  min-width: 230px;
  max-width: 290px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #fbfbfd;
  border-right: 1px solid var(--border, #e5e5ea);
  user-select: none;
}

.tree-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px 12px 8px;
  flex-shrink: 0;
}

.tree-title-group {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.tree-title {
  font-size: 13px;
  font-weight: 650;
  color: var(--text, #1d1d1f);
  white-space: nowrap;
}

.tree-count {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-tertiary, #86868b);
  background: rgba(0, 0, 0, 0.05);
  padding: 1px 6px;
  border-radius: 999px;
}

.tree-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
}

.icon-btn {
  width: 26px;
  height: 26px;
  padding: 0;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary, #6e6e73);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
  transition: background 0.12s ease, color 0.12s ease;
}

.icon-btn svg {
  width: 15px;
  height: 15px;
  display: block;
}

.icon-btn:hover {
  background: rgba(0, 0, 0, 0.06);
  color: var(--text, #1d1d1f);
}

.icon-btn.is-primary {
  color: var(--accent, #0071e3);
}

.icon-btn.is-primary:hover {
  background: rgba(0, 113, 227, 0.12);
}

.tree-filter-wrap {
  position: relative;
  display: flex;
  align-items: center;
  margin: 0 10px 8px;
  flex-shrink: 0;
}

.filter-icon {
  position: absolute;
  left: 9px;
  color: var(--text-tertiary, #86868b);
  pointer-events: none;
}

.tree-filter-input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--border, #e5e5ea);
  border-radius: 8px;
  background: #fff;
  padding: 5px 24px 5px 28px;
  font-size: 12px;
  color: var(--text, #1d1d1f);
  outline: none;
  transition: border-color 0.12s ease;
}

.tree-filter-input:focus {
  border-color: var(--accent, #0071e3);
}

.filter-clear-btn {
  position: absolute;
  right: 6px;
  width: 16px;
  height: 16px;
  border: none;
  background: rgba(0, 0, 0, 0.08);
  color: var(--text-secondary, #6e6e73);
  border-radius: 50%;
  font-size: 12px;
  line-height: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.root-create-box {
  margin: 0 10px 8px;
  padding: 8px;
  border-radius: 8px;
  background: #fff;
  border: 1px solid var(--accent, #0071e3);
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex-shrink: 0;
}

.root-create-input {
  width: 100%;
  box-sizing: border-box;
  border: none;
  font-size: 12.5px;
  outline: none;
  color: var(--text, #1d1d1f);
}

.root-create-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}

.move-panel {
  margin: 0 10px 8px;
  padding: 9px 10px;
  border-radius: 8px;
  background: #fff;
  border: 1px solid var(--border, #d1d1d6);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
  display: flex;
  flex-direction: column;
  gap: 7px;
  font-size: 12px;
  flex-shrink: 0;
}

.move-panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
  color: var(--text, #1d1d1f);
}

.move-close {
  border: none;
  background: transparent;
  font-size: 15px;
  color: var(--text-tertiary, #86868b);
  cursor: pointer;
  padding: 0 2px;
}

.move-row {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.move-label {
  font-size: 11px;
  color: var(--text-secondary, #6e6e73);
}

.move-select {
  width: 100%;
  border: 1px solid var(--border, #d1d1d6);
  border-radius: 6px;
  padding: 4px 6px;
  font-size: 12px;
  background: #fbfbfd;
}

.move-order-row {
  display: flex;
  align-items: center;
  gap: 5px;
}

.order-btn {
  flex: 1;
  border: 1px solid var(--border, #d1d1d6);
  background: #fff;
  border-radius: 6px;
  font-size: 11px;
  padding: 4px 6px;
  cursor: pointer;
  color: var(--text, #1d1d1f);
}

.order-btn:hover {
  background: #f5f5f7;
}

.mini-ghost {
  border: 1px solid var(--border, #d1d1d6);
  background: #fff;
  color: var(--text-secondary, #6e6e73);
  border-radius: 6px;
  font-size: 11.5px;
  padding: 3px 9px;
  cursor: pointer;
}

.mini-primary {
  border: none;
  background: var(--accent, #0071e3);
  color: #fff;
  border-radius: 6px;
  font-size: 11.5px;
  font-weight: 600;
  padding: 4px 10px;
  cursor: pointer;
}

.tree-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 2px 8px 16px;
}

.tree-nodes {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.tree-empty {
  padding: 32px 14px;
  text-align: center;
  color: var(--text-tertiary, #86868b);
  font-size: 12.5px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

.empty-msg {
  margin: 0;
}

.empty-cta {
  border: 1px solid rgba(0, 113, 227, 0.3);
  background: rgba(0, 113, 227, 0.08);
  color: #0058b0;
  border-radius: 7px;
  font-size: 12px;
  font-weight: 600;
  padding: 6px 12px;
  cursor: pointer;
}

.empty-cta:hover {
  background: rgba(0, 113, 227, 0.14);
}
</style>
