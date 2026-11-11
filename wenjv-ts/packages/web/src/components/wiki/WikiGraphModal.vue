<template>
  <div class="graph-modal-backdrop" @click.self="$emit('close')">
    <div class="graph-modal-dialog">
      <div class="modal-header">
        <div class="header-left">
          <svg class="header-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
          <span class="modal-title">Wiki 全局知识图谱</span>
          <span class="node-count">{{ nodes.length }} 节点 · {{ edges.length }} 引用关系</span>
        </div>
        <button class="close-btn" @click="$emit('close')">✕</button>
      </div>

      <div class="canvas-container">
        <canvas
          ref="canvasRef"
          @mousedown="onMouseDown"
          @mousemove="onMouseMove"
          @mouseup="onMouseUp"
          @wheel="onWheel"
          @dblclick="onDoubleClick"
        />
        <div class="graph-tip">💡 拖拽节点移动 · 滚轮跟随鼠标缩放 · 双击节点直接跳转页面</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { wikiApi } from '../../api/client'
import { useAuthStore } from '../../stores/auth'

const emit = defineEmits(['close', 'select-page'])

const canvasRef = ref(null)
const nodes = ref([])
const edges = ref([])

let animFrame = null
let resizeObserver = null
let isDragging = false
let draggedNode = null
let dpr = 1
let logicalWidth = 800
let logicalHeight = 600
let zoom = 1
let pan = { x: 0, y: 0 }

function updateCanvasSize() {
  const canvas = canvasRef.value
  if (!canvas || !canvas.parentElement) return
  dpr = window.devicePixelRatio || 1
  logicalWidth = canvas.parentElement.clientWidth || 800
  logicalHeight = canvas.parentElement.clientHeight || 600

  canvas.width = Math.floor(logicalWidth * dpr)
  canvas.height = Math.floor(logicalHeight * dpr)
  canvas.style.width = `${logicalWidth}px`
  canvas.style.height = `${logicalHeight}px`
}

onMounted(async () => {
  const auth = useAuthStore()
  try {
    const data = await wikiApi.getGraph(auth.token)
    nodes.value = (data.nodes || []).map((n) => ({
      ...n,
      x: (Math.random() - 0.5) * 400 + 300,
      y: (Math.random() - 0.5) * 300 + 200,
      vx: 0,
      vy: 0,
      radius: 14,
    }))
    edges.value = data.edges || []
    startSimulation()
  } catch (err) {
    console.error('Failed to load graph data', err)
  }

  if (canvasRef.value?.parentElement) {
    resizeObserver = new ResizeObserver(() => {
      updateCanvasSize()
    })
    resizeObserver.observe(canvasRef.value.parentElement)
  }
})

onUnmounted(() => {
  if (animFrame) cancelAnimationFrame(animFrame)
  if (resizeObserver) resizeObserver.disconnect()
})

function startSimulation() {
  const canvas = canvasRef.value
  if (!canvas) return
  updateCanvasSize()
  pan.x = logicalWidth / 2
  pan.y = logicalHeight / 2

  const ctx = canvas.getContext('2d')

  function loop() {
    updateForces()
    draw(ctx, canvas)
    animFrame = requestAnimationFrame(loop)
  }
  loop()
}

function updateForces() {
  // Repulsion between nodes
  for (let i = 0; i < nodes.value.length; i++) {
    for (let j = i + 1; j < nodes.value.length; j++) {
      const a = nodes.value[i]
      const b = nodes.value[j]
      const dx = b.x - a.x
      const dy = b.y - a.y
      const dist = Math.sqrt(dx * dx + dy * dy) || 1
      if (dist < 250) {
        const force = ((250 - dist) / dist) * 0.4
        if (a !== draggedNode) {
          a.x -= dx * force * 0.05
          a.y -= dy * force * 0.05
        }
        if (b !== draggedNode) {
          b.x += dx * force * 0.05
          b.y += dy * force * 0.05
        }
      }
    }
  }

  // Edge springs
  const nodeMap = new Map(nodes.value.map((n) => [n.id, n]))
  for (const e of edges.value) {
    const u = nodeMap.get(e.source)
    const v = nodeMap.get(e.target)
    if (!u || !v) continue
    const dx = v.x - u.x
    const dy = v.y - u.y
    const dist = Math.sqrt(dx * dx + dy * dy) || 1
    const force = (dist - 120) * 0.02
    if (u !== draggedNode) {
      u.x += dx * force * 0.05
      u.y += dy * force * 0.05
    }
    if (v !== draggedNode) {
      v.x += dx * force * 0.05
      v.y += dy * force * 0.05
    }
  }
}

function draw(ctx, canvas) {
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  ctx.save()
  // High-DPI Scaling
  ctx.scale(dpr, dpr)
  ctx.translate(pan.x, pan.y)
  ctx.scale(zoom, zoom)

  const nodeMap = new Map(nodes.value.map((n) => [n.id, n]))

  // Draw edges
  ctx.strokeStyle = 'rgba(156, 163, 175, 0.4)'
  ctx.lineWidth = 1.5
  for (const e of edges.value) {
    const u = nodeMap.get(e.source)
    const v = nodeMap.get(e.target)
    if (!u || !v) continue
    ctx.beginPath()
    ctx.moveTo(u.x, u.y)
    ctx.lineTo(v.x, v.y)
    ctx.stroke()
  }

  // Draw nodes
  for (const n of nodes.value) {
    ctx.fillStyle = '#0071e3'
    ctx.beginPath()
    ctx.arc(n.x, n.y, n.radius, 0, Math.PI * 2)
    ctx.fill()
    ctx.lineWidth = 2
    ctx.strokeStyle = '#ffffff'
    ctx.stroke()

    // Title
    ctx.fillStyle = '#1d1d1f'
    ctx.font = '11px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText(n.title, n.x, n.y + n.radius + 14)
  }

  ctx.restore()
}

function onMouseDown(e) {
  if (!canvasRef.value) return
  const rect = canvasRef.value.getBoundingClientRect()
  const clickX = (e.clientX - rect.left - pan.x) / zoom
  const clickY = (e.clientY - rect.top - pan.y) / zoom

  for (const n of nodes.value) {
    const d = Math.hypot(n.x - clickX, n.y - clickY)
    if (d <= n.radius + 4) {
      draggedNode = n
      isDragging = true
      return
    }
  }

  isDragging = false
  draggedNode = null
}

function onMouseMove(e) {
  if (draggedNode && canvasRef.value) {
    const rect = canvasRef.value.getBoundingClientRect()
    draggedNode.x = (e.clientX - rect.left - pan.x) / zoom
    draggedNode.y = (e.clientY - rect.top - pan.y) / zoom
  }
}

function onMouseUp() {
  draggedNode = null
  isDragging = false
}

function onDoubleClick(e) {
  if (!canvasRef.value) return
  const rect = canvasRef.value.getBoundingClientRect()
  const clickX = (e.clientX - rect.left - pan.x) / zoom
  const clickY = (e.clientY - rect.top - pan.y) / zoom

  for (const n of nodes.value) {
    const d = Math.hypot(n.x - clickX, n.y - clickY)
    if (d <= n.radius + 6) {
      emit('select-page', n.id)
      emit('close')
      return
    }
  }
}

function onWheel(e) {
  e.preventDefault()
  if (!canvasRef.value) return
  const rect = canvasRef.value.getBoundingClientRect()
  const mouseX = e.clientX - rect.left
  const mouseY = e.clientY - rect.top

  const factor = e.deltaY < 0 ? 1.1 : 0.9
  const newZoom = Math.max(0.3, Math.min(3, zoom * factor))

  pan.x = mouseX - (mouseX - pan.x) * (newZoom / zoom)
  pan.y = mouseY - (mouseY - pan.y) * (newZoom / zoom)
  zoom = newZoom
}
</script>

<style scoped>
.graph-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  backdrop-filter: blur(6px);
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
}

.graph-modal-dialog {
  width: 80vw;
  height: 80vh;
  max-width: 1100px;
  background: var(--surface, #ffffff);
  border-radius: var(--radius-sm, 12px);
  border: 1px solid var(--border, #e5e5ea);
  box-shadow: 0 20px 48px -10px rgba(0, 0, 0, 0.16);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.modal-header {
  height: 52px;
  border-bottom: 1px solid var(--border, #e5e5ea);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  background: var(--surface-secondary, #fafafa);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-icon {
  width: 18px;
  height: 18px;
  color: var(--accent, #0071e3);
}

.modal-title {
  font-size: 14px;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--text, #1d1d1f);
}

.node-count {
  font-size: 12px;
  color: var(--text-tertiary, #86868b);
  background: var(--bg-hover, #f0f0f4);
  padding: 2px 8px;
  border-radius: 999px;
}

.close-btn {
  border: none;
  background: transparent;
  color: var(--text-tertiary, #86868b);
  font-size: 14px;
  cursor: pointer;
  padding: 6px;
  border-radius: 6px;
  transition: all 150ms ease;
}

.close-btn:hover {
  background: var(--bg-hover, #f0f0f4);
  color: var(--text, #1d1d1f);
}

.canvas-container {
  flex: 1;
  position: relative;
  background: #fdfdfd;
  overflow: hidden;
}

canvas {
  display: block;
  width: 100%;
  height: 100%;
  cursor: grab;
}

canvas:active {
  cursor: grabbing;
}

.graph-tip {
  position: absolute;
  bottom: 14px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(8px);
  border: 1px solid var(--border, #e5e5ea);
  padding: 6px 14px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 500;
  color: var(--text-secondary, #6e6e73);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
  pointer-events: none;
}
</style>
