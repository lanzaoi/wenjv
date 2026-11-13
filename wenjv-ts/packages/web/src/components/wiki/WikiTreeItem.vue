<template>
  <div class="tree-node-wrap">
    <div
      :class="[
        'tree-row',
        {
          'is-active': node.id === currentId,
          'is-confirming': confirmingDeleteId === node.id,
        },
      ]"
      :style="{ paddingLeft: `${8 + depth * 16}px` }"
      @click="$emit('select', node.id)"
      @dblclick.stop="startRename"
    >
      <!-- Expand/Collapse Chevron -->
      <button
        type="button"
        class="chevron-btn"
        :class="{ 'is-hidden': !hasChildren }"
        :aria-label="isExpanded ? '折叠子页面' : '展开子页面'"
        @click.stop="$emit('toggle-expand', node.id)"
      >
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
          :class="['chevron-svg', { 'is-open': isExpanded }]"
        >
          <polyline points="9 18 15 12 9 6" />
        </svg>
      </button>

      <!-- Page Icon -->
      <span class="node-icon" aria-hidden="true">
        <span v-if="node.icon">{{ node.icon }}</span>
        <svg
          v-else
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
        </svg>
      </span>

      <!-- Inline Rename Input OR Title -->
      <input
        v-if="editing"
        ref="renameInputRef"
        v-model="draftTitle"
        class="inline-rename-input"
        @click.stop
        @keydown.enter.stop.prevent="commitRename"
        @keydown.esc.stop.prevent="cancelRename"
        @blur="commitRename"
      />
      <span v-else class="node-label" :title="node.title">{{ node.title }}</span>

      <!-- Hover Actions -->
      <div v-if="!editing && confirmingDeleteId !== node.id" class="row-actions" @click.stop>
        <button
          type="button"
          class="mini-action-btn"
          title="新建子页面"
          @click="$emit('request-create-child', node.id)"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
        </button>
        <button
          type="button"
          class="mini-action-btn"
          title="重命名"
          @click="startRename"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 20h9" />
            <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
          </svg>
        </button>
        <button
          type="button"
          class="mini-action-btn"
          title="移动或调整位置"
          @click="$emit('request-move', node)"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="5 9 2 12 5 15" />
            <polyline points="9 5 12 2 15 5" />
            <polyline points="15 19 12 22 9 19" />
            <polyline points="19 9 22 12 19 15" />
            <line x1="2" y1="12" x2="22" y2="12" />
            <line x1="12" y1="2" x2="12" y2="22" />
          </svg>
        </button>
        <button
          type="button"
          class="mini-action-btn is-danger"
          title="删除页面"
          @click="$emit('request-delete', node.id)"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="3 6 5 6 21 6" />
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
          </svg>
        </button>
      </div>
    </div>

    <!-- Inline Delete Confirmation Bar -->
    <div v-if="confirmingDeleteId === node.id" class="inline-confirm-bar" @click.stop>
      <span class="confirm-text">确认删除“{{ node.title }}”？</span>
      <div class="confirm-btns">
        <button type="button" class="confirm-cancel-btn" @click="$emit('cancel-delete')">取消</button>
        <button type="button" class="confirm-ok-btn" @click="$emit('confirm-delete', node.id)">删除</button>
      </div>
    </div>

    <!-- Inline Child Creation Box -->
    <div
      v-if="creatingUnderParentId === node.id"
      class="inline-create-row"
      :style="{ paddingLeft: `${24 + depth * 16}px` }"
      @click.stop
    >
      <input
        ref="createInputRef"
        v-model="draftChildTitle"
        class="inline-create-input"
        placeholder="子页面名称，回车创建..."
        @keydown.enter.stop.prevent="commitCreateChild"
        @keydown.esc.stop.prevent="$emit('cancel-create')"
      />
      <button type="button" class="inline-create-go" @click="commitCreateChild">创建</button>
    </div>

    <!-- Children Recursion -->
    <div v-if="hasChildren && isExpanded" class="tree-children">
      <WikiTreeItem
        v-for="child in node.children"
        :key="child.id"
        :node="child"
        :depth="depth + 1"
        :current-id="currentId"
        :expanded-ids="expandedIds"
        :confirming-delete-id="confirmingDeleteId"
        :creating-under-parent-id="creatingUnderParentId"
        @select="$emit('select', $event)"
        @toggle-expand="$emit('toggle-expand', $event)"
        @request-create-child="$emit('request-create-child', $event)"
        @submit-create-child="$emit('submit-create-child', $event)"
        @cancel-create="$emit('cancel-create')"
        @rename="$emit('rename', $event)"
        @request-move="$emit('request-move', $event)"
        @request-delete="$emit('request-delete', $event)"
        @confirm-delete="$emit('confirm-delete', $event)"
        @cancel-delete="$emit('cancel-delete')"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import type { WikiTreeNode } from '../../stores/wiki';

defineOptions({
  name: 'WikiTreeItem',
});

const props = defineProps<{
  node: WikiTreeNode;
  depth: number;
  currentId?: number | null | undefined;
  expandedIds: Set<number>;
  confirmingDeleteId: number | null;
  creatingUnderParentId: number | null;
}>();

const emit = defineEmits<{
  (e: 'select', pageId: number): void;
  (e: 'toggle-expand', pageId: number): void;
  (e: 'request-create-child', parentId: number): void;
  (e: 'submit-create-child', payload: { parentId: number; title: string }): void;
  (e: 'cancel-create'): void;
  (e: 'rename', payload: { id: number; title: string }): void;
  (e: 'request-move', node: WikiTreeNode): void;
  (e: 'request-delete', pageId: number): void;
  (e: 'confirm-delete', pageId: number): void;
  (e: 'cancel-delete'): void;
}>();

const editing = ref(false);
const draftTitle = ref('');
const renameInputRef = ref<HTMLInputElement | null>(null);

const draftChildTitle = ref('');
const createInputRef = ref<HTMLInputElement | null>(null);

const hasChildren = computed(() => Boolean(props.node.children && props.node.children.length > 0));
const isExpanded = computed(() => props.expandedIds.has(props.node.id));

watch(
  () => props.creatingUnderParentId,
  (val) => {
    if (val === props.node.id) {
      draftChildTitle.value = '';
      nextTick(() => createInputRef.value?.focus());
    }
  },
  { immediate: true }
);

function startRename() {
  draftTitle.value = props.node.title;
  editing.value = true;
  nextTick(() => {
    renameInputRef.value?.focus();
    renameInputRef.value?.select();
  });
}

function commitRename() {
  if (!editing.value) return;
  editing.value = false;
  const clean = draftTitle.value.trim();
  if (clean && clean !== props.node.title) {
    emit('rename', { id: props.node.id, title: clean });
  }
}

function cancelRename() {
  editing.value = false;
}

function commitCreateChild() {
  const title = draftChildTitle.value.trim() || '未命名子页面';
  emit('submit-create-child', { parentId: props.node.id, title });
  draftChildTitle.value = '';
}
</script>

<style scoped>
.tree-node-wrap {
  display: flex;
  flex-direction: column;
}

.tree-row {
  display: flex;
  align-items: center;
  gap: 5px;
  min-height: 30px;
  padding-top: 4px;
  padding-bottom: 4px;
  padding-right: 6px;
  border-radius: 7px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text, #1d1d1f);
  transition: background 0.12s ease;
  user-select: none;
  position: relative;
}

.tree-row:hover {
  background: rgba(0, 0, 0, 0.045);
}

.tree-row.is-active {
  background: rgba(0, 113, 227, 0.11);
  color: #0058b0;
  font-weight: 600;
}

.chevron-btn {
  width: 18px;
  height: 18px;
  border: none;
  background: transparent;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--text-tertiary, #86868b);
  cursor: pointer;
  border-radius: 4px;
  flex-shrink: 0;
}

.chevron-btn:hover {
  background: rgba(0, 0, 0, 0.06);
  color: var(--text, #1d1d1f);
}

.chevron-btn.is-hidden {
  visibility: hidden;
  pointer-events: none;
}

.chevron-svg {
  transition: transform 0.15s ease;
}

.chevron-svg.is-open {
  transform: rotate(90deg);
}

.node-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  font-size: 13px;
  line-height: 1;
  color: var(--text-secondary, #6e6e73);
  flex-shrink: 0;
}

.node-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.inline-rename-input {
  flex: 1;
  min-width: 0;
  border: 1px solid var(--accent, #0071e3);
  border-radius: 5px;
  background: #fff;
  padding: 2px 6px;
  font-size: 12.5px;
  color: var(--text, #1d1d1f);
  outline: none;
}

.row-actions {
  display: none;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
  background: inherit;
}

.tree-row:hover .row-actions,
.tree-row:focus-within .row-actions {
  display: flex;
}

.mini-action-btn {
  width: 21px;
  height: 21px;
  border: none;
  background: transparent;
  border-radius: 5px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary, #6e6e73);
  cursor: pointer;
  padding: 0;
  flex-shrink: 0;
}

.mini-action-btn:hover {
  background: rgba(0, 0, 0, 0.08);
  color: var(--text, #1d1d1f);
}

.mini-action-btn.is-danger:hover {
  background: rgba(255, 59, 48, 0.12);
  color: #d70015;
}

.inline-confirm-bar {
  margin: 2px 6px 4px 18px;
  padding: 6px 8px;
  border-radius: 7px;
  background: #fff5f5;
  border: 1px solid rgba(255, 59, 48, 0.28);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  font-size: 12px;
}

.confirm-text {
  color: #9e1c1c;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.confirm-btns {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.confirm-cancel-btn,
.confirm-ok-btn {
  border-radius: 5px;
  font-size: 11px;
  padding: 2px 7px;
  cursor: pointer;
  border: 1px solid transparent;
}

.confirm-cancel-btn {
  background: #fff;
  border-color: var(--border, #d1d1d6);
  color: var(--text-secondary, #6e6e73);
}

.confirm-ok-btn {
  background: #ff3b30;
  color: #fff;
}

.inline-create-row {
  display: flex;
  align-items: center;
  gap: 4px;
  padding-top: 3px;
  padding-bottom: 4px;
  padding-right: 6px;
}

.inline-create-input {
  flex: 1;
  min-width: 0;
  border: 1px solid var(--accent, #0071e3);
  border-radius: 6px;
  padding: 4px 7px;
  font-size: 12px;
  background: #fff;
  outline: none;
}

.inline-create-go {
  border: none;
  border-radius: 6px;
  background: var(--accent, #0071e3);
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  padding: 4px 8px;
  cursor: pointer;
  flex-shrink: 0;
}
</style>
