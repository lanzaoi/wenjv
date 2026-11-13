<template>
  <div v-if="show" class="graph-backdrop" @click.self="$emit('close')">
    <div class="graph-modal">
      <header class="graph-header">
        <div class="graph-title-wrap">
          <h3>全局知识图谱</h3>
          <span class="graph-stats">{{ nodes.length }} 个页面 · {{ validEdges.length }} 条关联</span>
        </div>
        <div class="graph-controls">
          <button type="button" class="graph-ctrl-btn" @click="zoomBy(1.15)">+</button>
          <button type="button" class="graph-ctrl-btn" @click="zoomBy(0.87)">-</button>
          <button type="button" class="graph-ctrl-btn" @click="resetViewport">重置视角</button>
          <button type="button" class="graph-close-btn" aria-label="关闭图谱" @click="$emit('close')">×</button>
        </div>
      </header>

      <div ref="stageRef" class="graph-stage">
        <div v-if="loading" class="graph-status">正在构建图谱关系...</div>
        <div v-else-if="errorMsg" class="graph-status is-error">{{ errorMsg }}</div>
        <div v-else-if="!nodes.length" class="graph-status">暂无页面，请先创建知识页面与 [[双链]] 引用。</div>

        <svg
          v-else
          ref="svgRef"
          class="graph-svg"
          viewBox="-420 -260 840 520"
          @mousedown="onCanvasMouseDown"
          @mousemove="onMouseMove"
          @mouseup="onMouseUp"
          @mouseleave="onMouseUp"
          @wheel.prevent="onWheel"
        >
          <defs>
            <marker
              id="wiki-arrow"
              viewBox="0 0 10 10"
              refX="20"
              refY="5"
              markerWidth="5"
              markerHeight="5"
              orient="auto-start-reverse"
            >
              <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#94a3b8" />
            </marker>
          </defs>

          <g :transform="`translate(${panX}, ${panY}) scale(${zoom})`">
            <!-- Edges -->
            <g class="edges-layer">
              <line
                v-for="(edge, idx) in renderedEdges"
                :key="idx"
                :x1="edge.x1"
                :y1="edge.y1"
                :x2="edge.x2"
                :y2="edge.y2"
                :class="[
                  'graph-edge',
                  {
                    'is-highlighted': hoveredId !== null && (edge.source === hoveredId || edge.target === hoveredId),
                    'is-dimmed': hoveredId !== null && edge.source !== hoveredId && edge.target !== hoveredId,
                  },
                ]"
                marker-end="url(#wiki-arrow)"
              />
            </g>

            <!-- Nodes -->
            <g class="nodes-layer">
              <g
                v-for="node in nodes"
                :key="node.id"
                :transform="`translate(${node.x}, ${node.y})`"
                :class="[
                  'graph-node',
                  {
                    'is-current': node.id === currentPageId,
                    'is-dimmed': hoveredId !== null && hoveredId !== node.id && !isNeighbor(node.id, hoveredId),
                  },
                ]"
                @mousedown.stop="onNodeMouseDown($event, node)"
                @mouseenter="hoveredId = node.id"
                @mouseleave="hoveredId = null"
              >
                <circle :r="nodeRadius(node.id)" class="node-circle" />
                <text dy="24" text-anchor="middle" class="node-label">{{ node.title }}</text>
              </g>
            </g>
          </g>
        </svg>

        <div class="graph-hint">拖拽空白处平移 · 滚轮缩放 · 拖拽节点调整位置 · 点击节点跳转</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { wikiApi } from '../../api/client';
import { useAuthStore } from '../../stores/auth';

interface GraphNode {
  id: number;
  title: string;
  slug: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
}

interface GraphEdge {
  source: number;
  target: number;
  label?: string;
}

const props = defineProps<{
  show: boolean;
  currentPageId?: number | null;
}>();

const emit = defineEmits<{
  (e: 'close'): void;
  (e: 'select-page', pageId: number): void;
}>();

const auth = useAuthStore();

const loading = ref(false);
const errorMsg = ref<string | null>(null);
const nodes = ref<GraphNode[]>([]);
const edges = ref<GraphEdge[]>([]);
const hoveredId = ref<number | null>(null);

const panX = ref(0);
const panY = ref(0);
const zoom = ref(1);

const stageRef = ref<HTMLDivElement | null>(null);
const svgRef = ref<SVGSVGElement | null>(null);

let rafId: number | null = null;
let dragNode: GraphNode | null = null;
let panning = false;
let lastMouseX = 0;
let lastMouseY = 0;
let dragDistance = 0;

const nodeMap = computed(() => {
  const m = new Map<number, GraphNode>();
  for (const n of nodes.value) m.set(n.id, n);
  return m;
});

const validEdges = computed(() => {
  const map = nodeMap.value;
  return edges.value.filter((e) => e.source !== e.target && map.has(e.source) && map.has(e.target));
});

const degreeMap = computed(() => {
  const counts = new Map<number, number>();
  for (const e of validEdges.value) {
    counts.set(e.source, (counts.get(e.source) || 0) + 1);
    counts.set(e.target, (counts.get(e.target) || 0) + 1);
  }
  return counts;
});

const renderedEdges = computed(() => {
  const map = nodeMap.value;
  return validEdges.value.map((e) => {
    const s = map.get(e.source)!;
    const t = map.get(e.target)!;
    return {
      ...e,
      x1: s.x,
      y1: s.y,
      x2: t.x,
      y2: t.y,
    };
  });
});

function nodeRadius(id: number): number {
  const deg = degreeMap.value.get(id) || 0;
  return Math.min(18, 9 + deg * 1.5);
}

function isNeighbor(a: number, b: number): boolean {
  return validEdges.value.some(
    (e) => (e.source === a && e.target === b) || (e.source === b && e.target === a)
  );
}

watch(
  () => props.show,
  (visible) => {
    if (visible) {
      resetViewport();
      void loadGraph();
    } else {
      stopSimulation();
    }
  }
);

onBeforeUnmount(() => {
  stopSimulation();
});

async function loadGraph() {
  loading.value = true;
  errorMsg.value = null;
  stopSimulation();

  try {
    const data = await wikiApi.getGraph(auth.token);
    const rawNodes: Array<{ id: number; title: string; slug: string }> = data?.nodes || [];
    const total = Math.max(1, rawNodes.length);
    const radius = Math.min(180, 60 + total * 12);

    nodes.value = rawNodes.map((n, idx) => {
      const angle = (idx / total) * Math.PI * 2;
      return {
        ...n,
        x: total === 1 ? 0 : Math.cos(angle) * radius,
        y: total === 1 ? 0 : Math.sin(angle) * radius,
        vx: 0,
        vy: 0,
      };
    });

    edges.value = data?.links || data?.edges || [];
    if (nodes.value.length > 1) {
      startSimulation(160);
    }
  } catch (err: unknown) {
    errorMsg.value = err instanceof Error ? err.message : '加载知识图谱失败';
  } finally {
    loading.value = false;
  }
}

function stopSimulation() {
  if (rafId !== null) {
    cancelAnimationFrame(rafId);
    rafId = null;
  }
}

function startSimulation(maxSteps = 120) {
  stopSimulation();
  let steps = 0;

  const step = () => {
    steps += 1;
    const ns = nodes.value;
    const map = nodeMap.value;
    let totalEnergy = 0;

    // 1. Repulsion between all pairs
    for (let i = 0; i < ns.length; i++) {
      const a = ns[i]!;
      for (let j = i + 1; j < ns.length; j++) {
        const b = ns[j]!;
        let dx = a.x - b.x;
        let dy = a.y - b.y;
        let distSq = dx * dx + dy * dy;
        if (distSq < 1) {
          dx = 1;
          dy = 0;
          distSq = 1;
        }
        const dist = Math.sqrt(distSq);
        const force = 2600 / distSq;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        a.vx += fx;
        a.vy += fy;
        b.vx -= fx;
        b.vy -= fy;
      }
    }

    // 2. Spring attraction along edges
    const idealLen = 125;
    for (const e of validEdges.value) {
      const s = map.get(e.source);
      const t = map.get(e.target);
      if (!s || !t) continue;
      const dx = t.x - s.x;
      const dy = t.y - s.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const force = (dist - idealLen) * 0.03;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      s.vx += fx;
      s.vy += fy;
      t.vx -= fx;
      t.vy -= fy;
    }

    // 3. Center gravity + damping
    for (const n of ns) {
      if (dragNode && dragNode.id === n.id) continue;
      n.vx = (n.vx - n.x * 0.012) * 0.82;
      n.vy = (n.vy - n.y * 0.012) * 0.82;
      n.x += n.vx;
      n.y += n.vy;
      totalEnergy += Math.abs(n.vx) + Math.abs(n.vy);
    }

    if (steps < maxSteps && (totalEnergy > 0.15 || dragNode !== null)) {
      rafId = requestAnimationFrame(step);
    } else {
      rafId = null;
    }
  };

  rafId = requestAnimationFrame(step);
}

function resetViewport() {
  panX.value = 0;
  panY.value = 0;
  zoom.value = 1;
}

function zoomBy(factor: number) {
  zoom.value = Math.min(2.4, Math.max(0.4, Number((zoom.value * factor).toFixed(2))));
}

function onWheel(e: WheelEvent) {
  zoomBy(e.deltaY < 0 ? 1.1 : 0.91);
}

function onCanvasMouseDown(e: MouseEvent) {
  panning = true;
  dragNode = null;
  lastMouseX = e.clientX;
  lastMouseY = e.clientY;
}

function onNodeMouseDown(e: MouseEvent, node: GraphNode) {
  dragNode = node;
  panning = false;
  dragDistance = 0;
  lastMouseX = e.clientX;
  lastMouseY = e.clientY;
}

function onMouseMove(e: MouseEvent) {
  const dx = e.clientX - lastMouseX;
  const dy = e.clientY - lastMouseY;
  lastMouseX = e.clientX;
  lastMouseY = e.clientY;

  if (dragNode) {
    const svg = svgRef.value;
    const scaleX = svg ? 840 / Math.max(1, svg.clientWidth) : 1;
    const scaleY = svg ? 520 / Math.max(1, svg.clientHeight) : 1;
    dragNode.x += (dx * scaleX) / zoom.value;
    dragNode.y += (dy * scaleY) / zoom.value;
    dragNode.vx = 0;
    dragNode.vy = 0;
    dragDistance += Math.hypot(dx, dy);
  } else if (panning) {
    const svg = svgRef.value;
    const scaleX = svg ? 840 / Math.max(1, svg.clientWidth) : 1;
    const scaleY = svg ? 520 / Math.max(1, svg.clientHeight) : 1;
    panX.value += dx * scaleX;
    panY.value += dy * scaleY;
  }
}

function onMouseUp() {
  if (dragNode && dragDistance < 5) {
    const clickedId = dragNode.id;
    dragNode = null;
    emit('select-page', clickedId);
    emit('close');
    return;
  }
  dragNode = null;
  panning = false;
}
</script>

<style scoped>
.graph-backdrop {
  position: fixed;
  inset: 0;
  z-index: 100;
  background: rgba(15, 23, 42, 0.45);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.graph-modal {
  width: min(980px, 94vw);
  height: min(640px, 86vh);
  background: #ffffff;
  border-radius: 14px;
  border: 1px solid var(--border, #e5e5ea);
  box-shadow: 0 24px 48px rgba(0, 0, 0, 0.22);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.graph-header {
  height: 50px;
  padding: 0 18px;
  border-bottom: 1px solid var(--border, #e5e5ea);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}

.graph-title-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
}

.graph-title-wrap h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 650;
  color: var(--text, #1d1d1f);
}

.graph-stats {
  font-size: 12px;
  color: var(--text-tertiary, #86868b);
  background: #f2f2f7;
  padding: 2px 9px;
  border-radius: 999px;
}

.graph-controls {
  display: flex;
  align-items: center;
  gap: 6px;
}

.graph-ctrl-btn {
  border: 1px solid var(--border, #d1d1d6);
  background: #fff;
  color: var(--text, #1d1d1f);
  border-radius: 6px;
  font-size: 12px;
  padding: 4px 10px;
  cursor: pointer;
}

.graph-ctrl-btn:hover {
  background: #f5f5f7;
}

.graph-close-btn {
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  font-size: 20px;
  color: var(--text-secondary, #6e6e73);
  border-radius: 7px;
  cursor: pointer;
}

.graph-close-btn:hover {
  background: rgba(0, 0, 0, 0.06);
}

.graph-stage {
  flex: 1;
  min-height: 0;
  position: relative;
  background: radial-gradient(circle at 1px 1px, #e5e7eb 1px, transparent 0);
  background-size: 22px 22px;
  background-color: #fbfbfd;
}

.graph-svg {
  width: 100%;
  height: 100%;
  display: block;
  cursor: grab;
}

.graph-svg:active {
  cursor: grabbing;
}

.graph-status {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13.5px;
  color: var(--text-secondary, #6e6e73);
}

.graph-status.is-error {
  color: #b91c1c;
}

.graph-edge {
  stroke: #cbd5e1;
  stroke-width: 1.5;
  transition: stroke 0.15s ease, opacity 0.15s ease;
}

.graph-edge.is-highlighted {
  stroke: var(--accent, #0071e3);
  stroke-width: 2.2;
}

.graph-edge.is-dimmed {
  opacity: 0.25;
}

.graph-node {
  cursor: pointer;
  transition: opacity 0.15s ease;
}

.graph-node.is-dimmed {
  opacity: 0.3;
}

.node-circle {
  fill: #ffffff;
  stroke: var(--accent, #0071e3);
  stroke-width: 2.2;
  transition: transform 0.12s ease, fill 0.12s ease;
}

.graph-node:hover .node-circle {
  fill: #e8f2fd;
  transform: scale(1.12);
}

.graph-node.is-current .node-circle {
  fill: var(--accent, #0071e3);
  stroke: #004e9e;
}

.node-label {
  font-size: 11.5px;
  font-weight: 500;
  fill: #1d1d1f;
  pointer-events: none;
  paint-order: stroke;
  stroke: rgba(255, 255, 255, 0.9);
  stroke-width: 3px;
}

.graph-hint {
  position: absolute;
  bottom: 10px;
  left: 14px;
  font-size: 11.5px;
  color: var(--text-tertiary, #86868b);
  background: rgba(255, 255, 255, 0.85);
  padding: 3px 9px;
  border-radius: 6px;
  pointer-events: none;
}
</style>
