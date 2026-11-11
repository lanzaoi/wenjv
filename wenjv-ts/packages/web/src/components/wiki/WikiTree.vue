<template>
  <aside class="wiki-tree-panel">
    <div class="tree-header">
      <div class="header-title">
        <svg class="w-4 h-4 text-neutral-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
        </svg>
        <span class="font-medium text-xs tracking-wide uppercase text-neutral-500">知识目录</span>
      </div>
      <div class="header-actions flex items-center gap-1">
        <button class="icon-btn-sm" @click="$emit('open-graph')" title="打开全局知识图谱">
          <svg class="w-3.5 h-3.5 text-indigo-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
        </button>
        <button class="icon-btn-sm" @click="handleCreateRoot" title="新建根页面">
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
          </svg>
        </button>
      </div>
    </div>

    <!-- Tree nodes -->
    <div class="tree-scroll">
      <div v-if="!tree.length" class="empty-hint">暂无页面，点击上方 + 新建</div>
      <tree-node
        v-for="node in tree"
        :key="node.id"
        :node="node"
        :current-id="currentId"
        :depth="0"
        @select="onSelect"
        @create-child="onCreateChild"
        @delete="onDelete"
      />
    </div>
  </aside>
</template>

<script setup>
import { defineComponent, h, ref } from 'vue'

const props = defineProps({
  tree: { type: Array, default: () => [] },
  currentId: { type: [Number, String], default: null },
})

const emit = defineEmits(['select', 'create', 'delete', 'open-graph'])

function handleCreateRoot() {
  emit('create', { title: '未命名页面', parentId: null })
}

function onSelect(id) {
  emit('select', id)
}

function onCreateChild(parentId) {
  emit('create', { title: '未命名子页面', parentId })
}

function onDelete(id) {
  if (window.confirm('确定要删除该页面及其子页面吗？')) {
    emit('delete', id)
  }
}

// Recursive TreeNode Component
const TreeNode = defineComponent({
  name: 'TreeNode',
  props: {
    node: { type: Object, required: true },
    currentId: { type: [Number, String], default: null },
    depth: { type: Number, default: 0 },
  },
  emits: ['select', 'create-child', 'delete'],
  setup(props, { emit }) {
    const expanded = ref(true)

    return () => {
      const hasChildren = props.node.children && props.node.children.length > 0
      const isSelected = props.node.id === props.currentId

      return h('div', { class: 'tree-node-wrapper' }, [
        h(
          'div',
          {
            class: ['tree-row', isSelected ? 'active' : ''],
            style: { paddingLeft: `${props.depth * 14 + 10}px` },
            onClick: () => emit('select', props.node.id),
          },
          [
            // Expand toggle
            h(
              'span',
              {
                class: ['toggle-icon', hasChildren ? '' : 'invisible'],
                onClick: (e) => {
                  e.stopPropagation()
                  expanded.value = !expanded.value
                },
              },
              expanded.value ? '▾' : '▸'
            ),
            // Page Title
            h('span', { class: 'node-title truncate' }, props.node.title),
            // Actions
            h('div', { class: 'node-actions' }, [
              h(
                'button',
                {
                  class: 'action-btn',
                  title: '添加子页面',
                  onClick: (e) => {
                    e.stopPropagation()
                    emit('create-child', props.node.id)
                  },
                },
                '+'
              ),
              h(
                'button',
                {
                  class: 'action-btn delete',
                  title: '删除页面',
                  onClick: (e) => {
                    e.stopPropagation()
                    emit('delete', props.node.id)
                  },
                },
                '×'
              ),
            ]),
          ]
        ),
        // Child nodes
        hasChildren && expanded.value
          ? props.node.children.map((child) =>
              h(TreeNode, {
                key: child.id,
                node: child,
                currentId: props.currentId,
                depth: props.depth + 1,
                onSelect: (id) => emit('select', id),
                onCreateChild: (id) => emit('create-child', id),
                onDelete: (id) => emit('delete', id),
              })
            )
          : null,
      ])
    }
  },
})
</script>

<style scoped>
.wiki-tree-panel {
  width: 250px;
  height: 100%;
  border-right: 1px solid rgba(0, 0, 0, 0.08);
  background: #fbfbfd;
  display: flex;
  flex-direction: column;
}

.tree-header {
  padding: 14px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid rgba(0, 0, 0, 0.05);
}

.header-title {
  display: flex;
  align-items: center;
  gap: 6px;
}

.icon-btn-sm {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  color: #6b7280;
  transition: all 0.15s ease;
}
.icon-btn-sm:hover {
  background: rgba(0, 0, 0, 0.05);
  color: #111827;
}

.tree-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 8px 4px;
}

.empty-hint {
  padding: 24px 16px;
  font-size: 13px;
  color: #9ca3af;
  text-align: center;
}

:deep(.tree-row) {
  display: flex;
  align-items: center;
  height: 32px;
  border-radius: 6px;
  cursor: pointer;
  user-select: none;
  font-size: 13px;
  color: #374151;
  transition: background 0.15s ease;
  position: relative;
}

:deep(.tree-row:hover) {
  background: rgba(0, 0, 0, 0.04);
}

:deep(.tree-row.active) {
  background: rgba(0, 113, 227, 0.1);
  color: #0071e3;
  font-weight: 500;
}

:deep(.toggle-icon) {
  width: 16px;
  font-size: 11px;
  color: #9ca3af;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-right: 2px;
}

:deep(.toggle-icon.invisible) {
  visibility: hidden;
}

:deep(.node-title) {
  flex: 1;
  margin-right: 6px;
}

:deep(.node-actions) {
  display: none;
  align-items: center;
  gap: 2px;
  margin-right: 6px;
}

:deep(.tree-row:hover .node-actions) {
  display: flex;
}

:deep(.action-btn) {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  color: #6b7280;
  font-size: 14px;
}

:deep(.action-btn:hover) {
  background: rgba(0, 0, 0, 0.08);
  color: #111827;
}

:deep(.action-btn.delete:hover) {
  color: #ef4444;
}
</style>
