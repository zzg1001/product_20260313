<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'

interface WorkflowNode {
  id: string
  type: 'skill' | 'workflow'
  name: string
  icon: string
  description: string
  position: { x: number; y: number }
  workflowData?: Workflow
}

interface WorkflowEdge {
  id: string
  from: string
  to: string
}

interface Workflow {
  id: string
  name: string
  description: string
  icon: string
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  createdAt: string
  updatedAt: string
}

const props = defineProps<{
  skills: Array<{ id: number; name: string; icon: string; description: string }>
  workflows: Workflow[]
  editingWorkflow?: Workflow | null
}>()

const emit = defineEmits<{
  save: [workflow: Workflow]
  close: []
}>()

const workflowName = ref('')
const workflowDesc = ref('')
const workflowIcon = ref('🔄')

const nodes = ref<WorkflowNode[]>([])
const edges = ref<WorkflowEdge[]>([])

// 初始化编辑数据
const initFromEditingWorkflow = () => {
  const editing = props.editingWorkflow
  console.log('initFromEditingWorkflow called, editingWorkflow:', editing)
  if (editing && editing.nodes && editing.nodes.length > 0) {
    workflowName.value = editing.name || ''
    workflowDesc.value = editing.description || ''
    workflowIcon.value = editing.icon || '🔄'
    nodes.value = JSON.parse(JSON.stringify(editing.nodes))
    edges.value = JSON.parse(JSON.stringify(editing.edges || []))
    console.log('Loaded nodes:', nodes.value.length, 'edges:', edges.value.length)
  } else if (!editing) {
    // 新建流程时清空
    workflowName.value = ''
    workflowDesc.value = ''
    workflowIcon.value = '🔄'
    nodes.value = []
    edges.value = []
  }
}

// 监听editingWorkflow变化
watch(() => props.editingWorkflow, (newVal, oldVal) => {
  console.log('editingWorkflow changed:', newVal?.name, 'from:', oldVal?.name)
  initFromEditingWorkflow()
}, { immediate: true, deep: true })

// 自动生成流程描述（根据节点和边的关系）
const autoDescription = computed(() => {
  if (nodes.value.length === 0) return ''

  // 找到起始节点（没有入边的节点）
  const nodeIds = new Set(nodes.value.map(n => n.id))
  const hasIncoming = new Set(edges.value.map(e => e.to))
  const startNodes = nodes.value.filter(n => !hasIncoming.has(n.id))

  // 构建邻接表
  const adj: Record<string, string[]> = {}
  edges.value.forEach(e => {
    if (!adj[e.from]) adj[e.from] = []
    const fromAdj = adj[e.from]
    if (fromAdj) fromAdj.push(e.to)
  })

  // 生成描述
  const parts: string[] = []
  const visited = new Set<string>()

  const traverse = (nodeId: string, depth: number): string => {
    if (visited.has(nodeId)) return ''
    visited.add(nodeId)

    const node = nodes.value.find(n => n.id === nodeId)
    if (!node) return ''

    const children = adj[nodeId] || []
    if (children.length === 0) {
      return node.name
    } else if (children.length === 1 && children[0]) {
      const childResult = traverse(children[0], depth + 1)
      return childResult ? `${node.name} → ${childResult}` : node.name
    } else if (children.length > 1) {
      // 分叉：并行执行
      const childResults = children.map(c => traverse(c, depth + 1)).filter(Boolean)
      if (childResults.length > 0) {
        return `${node.name} → [${childResults.join(' + ')}]`
      }
      return node.name
    }
    return node.name
  }

  const firstStart = startNodes[0]
  if (startNodes.length === 1 && firstStart) {
    return traverse(firstStart.id, 0)
  } else if (startNodes.length > 1) {
    return startNodes.map(n => traverse(n.id, 0)).join(' | ')
  } else if (nodes.value.length > 0) {
    // 没有明确的起始节点，按顺序列出
    return nodes.value.map(n => n.name).join(' → ')
  }
  return ''
})

// 显示的描述（用户输入优先，否则自动生成）
const displayDescription = computed(() => {
  return workflowDesc.value || autoDescription.value
})

const selectedNode = ref<string | null>(null)
const canvasRef = ref<HTMLElement | null>(null)

// 节点尺寸常量
const NODE_WIDTH = 150
const NODE_HEIGHT = 70

// 拖拽节点状态
const isDraggingNode = ref(false)
const draggedNode = ref<WorkflowNode | null>(null)
const dragOffset = ref({ x: 0, y: 0 })

// 拖拽连线状态
const isDraggingEdge = ref(false)
const edgeFromNode = ref<string | null>(null)
const tempEdge = ref({ x1: 0, y1: 0, x2: 0, y2: 0 })
const hoverTargetNode = ref<string | null>(null)

// 可用项目
const availableItems = computed(() => {
  const skillItems = props.skills.map(s => ({
    id: `skill-${s.id}`,
    type: 'skill' as const,
    name: s.name,
    icon: s.icon,
    description: s.description
  }))
  const workflowItems = props.workflows.map(w => ({
    id: `workflow-${w.id}`,
    type: 'workflow' as const,
    name: w.name,
    icon: w.icon,
    description: w.description,
    workflowData: w
  }))
  return [...skillItems, ...workflowItems]
})

// 添加节点
const addNode = (item: any, x: number, y: number) => {
  nodes.value.push({
    id: `node-${Date.now()}`,
    type: item.type,
    name: item.name,
    icon: item.icon,
    description: item.description,
    position: { x, y },
    workflowData: item.workflowData
  })
}

// 删除节点
const deleteNode = (nodeId: string) => {
  nodes.value = nodes.value.filter(n => n.id !== nodeId)
  edges.value = edges.value.filter(e => e.from !== nodeId && e.to !== nodeId)
  if (selectedNode.value === nodeId) selectedNode.value = null
}

// 删除连线
const deleteEdge = (edgeId: string) => {
  edges.value = edges.value.filter(e => e.id !== edgeId)
}

// === 节点拖拽 ===
const startDragNode = (e: MouseEvent, node: WorkflowNode) => {
  // 如果点击的是端口，不触发节点拖拽
  if ((e.target as HTMLElement).closest('.port')) return

  e.stopPropagation()
  isDraggingNode.value = true
  draggedNode.value = node
  selectedNode.value = node.id
  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
  dragOffset.value = { x: e.clientX - rect.left, y: e.clientY - rect.top }
}

// === 连线拖拽 ===
const startDragEdge = (e: MouseEvent, nodeId: string) => {
  e.stopPropagation()
  e.preventDefault()
  isDraggingEdge.value = true
  edgeFromNode.value = nodeId

  const node = nodes.value.find(n => n.id === nodeId)
  if (node && canvasRef.value) {
    const rect = canvasRef.value.getBoundingClientRect()
    // 从右侧输出端口中心开始
    const x = node.position.x + NODE_WIDTH + 6
    const y = node.position.y + NODE_HEIGHT / 2
    tempEdge.value = { x1: x, y1: y, x2: e.clientX - rect.left, y2: e.clientY - rect.top }
  }
}

// 在输入端口上松开鼠标 - 完成连线
const onInputPortMouseUp = (e: MouseEvent, nodeId: string) => {
  if (isDraggingEdge.value && edgeFromNode.value && edgeFromNode.value !== nodeId) {
    const exists = edges.value.some(e =>
      (e.from === edgeFromNode.value && e.to === nodeId) ||
      (e.from === nodeId && e.to === edgeFromNode.value)
    )
    if (!exists) {
      edges.value.push({
        id: `edge-${Date.now()}`,
        from: edgeFromNode.value,
        to: nodeId
      })
    }
  }
  resetDragState()
}

// 鼠标移动
const onMouseMove = (e: MouseEvent) => {
  if (!canvasRef.value) return
  const rect = canvasRef.value.getBoundingClientRect()
  const mx = e.clientX - rect.left
  const my = e.clientY - rect.top

  // 移动节点
  if (isDraggingNode.value && draggedNode.value) {
    draggedNode.value.position = {
      x: Math.max(0, mx - dragOffset.value.x),
      y: Math.max(0, my - dragOffset.value.y)
    }
  }

  // 拖拽连线
  if (isDraggingEdge.value) {
    tempEdge.value.x2 = mx
    tempEdge.value.y2 = my

    // 检测是否悬停在某个节点的输入端口附近
    hoverTargetNode.value = null
    for (const node of nodes.value) {
      if (node.id === edgeFromNode.value) continue
      // 输入端口位置（节点左侧）
      const portX = node.position.x - 6
      const portY = node.position.y + NODE_HEIGHT / 2
      // 检测距离（40px 范围内）
      const dist = Math.sqrt(Math.pow(mx - portX, 2) + Math.pow(my - portY, 2))
      if (dist < 40) {
        hoverTargetNode.value = node.id
        break
      }
    }
  }
}

// 重置拖拽状态
const resetDragState = () => {
  isDraggingNode.value = false
  draggedNode.value = null
  isDraggingEdge.value = false
  edgeFromNode.value = null
  hoverTargetNode.value = null
}

// 鼠标松开
const onMouseUp = () => {
  // 完成连线（如果在目标节点上松开）
  if (isDraggingEdge.value && edgeFromNode.value && hoverTargetNode.value) {
    const exists = edges.value.some(e =>
      (e.from === edgeFromNode.value && e.to === hoverTargetNode.value) ||
      (e.from === hoverTargetNode.value && e.to === edgeFromNode.value)
    )
    if (!exists) {
      edges.value.push({
        id: `edge-${Date.now()}`,
        from: edgeFromNode.value,
        to: hoverTargetNode.value
      })
    }
  }
  resetDragState()
}

// 获取连线路径（贝塞尔曲线）
const getEdgePath = (edge: WorkflowEdge) => {
  const from = nodes.value.find(n => n.id === edge.from)
  const to = nodes.value.find(n => n.id === edge.to)
  if (!from || !to) return ''

  // 起点：from 节点的右侧输出端口
  const x1 = from.position.x + NODE_WIDTH + 6
  const y1 = from.position.y + NODE_HEIGHT / 2
  // 终点：to 节点的左侧输入端口
  const x2 = to.position.x - 6
  const y2 = to.position.y + NODE_HEIGHT / 2

  // 控制点偏移量
  const dx = Math.abs(x2 - x1)
  const ctrl = Math.max(dx * 0.4, 50)

  return `M ${x1} ${y1} C ${x1 + ctrl} ${y1}, ${x2 - ctrl} ${y2}, ${x2} ${y2}`
}

// 临时连线路径
const getTempEdgePath = () => {
  const { x1, y1, x2, y2 } = tempEdge.value
  const dx = Math.abs(x2 - x1)
  const ctrl = Math.max(dx * 0.3, 30)
  return `M ${x1} ${y1} C ${x1 + ctrl} ${y1}, ${x2 - ctrl} ${y2}, ${x2} ${y2}`
}

// 从侧边栏拖入
const onDrop = (e: DragEvent) => {
  const data = e.dataTransfer?.getData('application/json')
  if (data && canvasRef.value) {
    const item = JSON.parse(data)
    const rect = canvasRef.value.getBoundingClientRect()
    addNode(item, e.clientX - rect.left - 70, e.clientY - rect.top - 35)
  }
}

// 点击添加
const quickAdd = (item: any) => {
  const last = nodes.value[nodes.value.length - 1]
  addNode(item, last ? last.position.x + 180 : 60, last ? last.position.y : 80)
}

// 保存对话框状态
const showSaveDialog = ref(false)
const saveDialogName = ref('')
const saveDialogDesc = ref('')
const saveDialogIcon = ref('🔄')
const saveNameError = ref('')

// 打开保存对话框
const openSaveDialog = () => {
  // 预填充当前值
  saveDialogName.value = workflowName.value.trim()
  saveDialogDesc.value = workflowDesc.value.trim() || autoDescription.value
  saveDialogIcon.value = workflowIcon.value
  saveNameError.value = ''
  showSaveDialog.value = true
}

// 确认保存
const confirmSave = () => {
  // 验证名字
  if (!saveDialogName.value.trim()) {
    saveNameError.value = '请输入工作流名称'
    return
  }

  emit('save', {
    id: props.editingWorkflow?.id || `wf-${Date.now()}`,
    name: saveDialogName.value.trim(),
    description: saveDialogDesc.value.trim(),
    icon: saveDialogIcon.value,
    nodes: nodes.value,
    edges: edges.value,
    createdAt: props.editingWorkflow?.createdAt || new Date().toISOString(),
    updatedAt: new Date().toISOString()
  })

  showSaveDialog.value = false
}

// 取消保存
const cancelSave = () => {
  showSaveDialog.value = false
}

// 重新创建（清空当前内容）
const resetWorkflow = () => {
  if (nodes.value.length > 0) {
    if (confirm('确定要放弃当前内容并重新创建吗？')) {
      nodes.value = []
      edges.value = []
      workflowName.value = ''
      workflowDesc.value = ''
      workflowIcon.value = '🔄'
    }
  }
}

// 加载示例
const loadExample = () => {
  nodes.value = [
    { id: 'n1', type: 'skill', name: 'sql-helper', icon: '🗃️', description: '构建SQL查询', position: { x: 50, y: 80 } },
    { id: 'n2', type: 'skill', name: 'data-visualizer', icon: '📊', description: '数据可视化', position: { x: 230, y: 40 } },
    { id: 'n3', type: 'skill', name: 'doc-parser', icon: '📑', description: '解析文档', position: { x: 230, y: 130 } },
    { id: 'n4', type: 'skill', name: 'email-composer', icon: '📧', description: '生成邮件', position: { x: 410, y: 80 } },
  ]
  edges.value = [
    { id: 'e1', from: 'n1', to: 'n2' },
    { id: 'e2', from: 'n1', to: 'n3' },
    { id: 'e3', from: 'n2', to: 'n4' },
    { id: 'e4', from: 'n3', to: 'n4' },
  ]
  workflowName.value = '数据分析报告'
  workflowDesc.value = 'SQL查询 → 可视化+解析 → 邮件发送'
}

const icons = ['🔄', '📊', '🗃️', '📋', '⚡', '🔗', '🤖', '📦', '🎯', '🚀']
</script>

<template>
  <div class="builder">
    <!-- Header -->
    <header class="header">
      <div class="header-left">
        <button class="back-btn" @click="emit('close')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>
        </button>
        <div class="header-title">
          <span class="header-icon">{{ workflowIcon }}</span>
          <span class="header-text">{{ props.editingWorkflow ? '编辑工作流' : '创建工作流' }}</span>
        </div>
      </div>
      <div class="header-right">
        <button class="btn text" @click="loadExample">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
            <line x1="16" y1="13" x2="8" y2="13"/>
            <line x1="16" y1="17" x2="8" y2="17"/>
          </svg>
          示例
        </button>
        <button v-if="nodes.length > 0" class="btn text danger" @click="resetWorkflow">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
            <path d="M3 3v5h5"/>
          </svg>
          重新创建
        </button>
        <button class="btn save" @click="openSaveDialog" :disabled="nodes.length === 0">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
          保存工作流
        </button>
      </div>
    </header>

    <!-- 保存确认对话框 -->
    <Transition name="dialog">
      <div v-if="showSaveDialog" class="save-dialog-overlay" @click.self="cancelSave">
        <div class="save-dialog">
          <div class="save-dialog-header">
            <h3>保存工作流</h3>
            <button class="close-btn" @click="cancelSave">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M18 6L6 18M6 6l12 12"/>
              </svg>
            </button>
          </div>

          <div class="save-dialog-body">
            <!-- 图标选择 -->
            <div class="form-group">
              <label>图标</label>
              <div class="icon-select">
                <button
                  v-for="ic in icons"
                  :key="ic"
                  class="icon-option"
                  :class="{ active: saveDialogIcon === ic }"
                  @click="saveDialogIcon = ic"
                >{{ ic }}</button>
              </div>
            </div>

            <!-- 名称输入 -->
            <div class="form-group">
              <label>名称 <span class="required">*</span></label>
              <input
                v-model="saveDialogName"
                class="form-input"
                :class="{ error: saveNameError }"
                placeholder="请输入工作流名称"
                @input="saveNameError = ''"
              />
              <span v-if="saveNameError" class="error-msg">{{ saveNameError }}</span>
            </div>

            <!-- 描述输入 -->
            <div class="form-group">
              <label>描述 <span class="optional">(可选)</span></label>
              <textarea
                v-model="saveDialogDesc"
                class="form-textarea"
                placeholder="添加工作流描述..."
                rows="3"
              ></textarea>
            </div>

            <!-- 预览 -->
            <div class="save-preview">
              <div class="preview-icon">{{ saveDialogIcon }}</div>
              <div class="preview-info">
                <div class="preview-name">{{ saveDialogName || '未命名工作流' }}</div>
                <div class="preview-meta">{{ nodes.length }} 个步骤</div>
              </div>
            </div>
          </div>

          <div class="save-dialog-footer">
            <button class="btn secondary" @click="cancelSave">取消</button>
            <button class="btn primary" @click="confirmSave">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="20 6 9 17 4 12"/>
              </svg>
              确认保存
            </button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- 拖拽连线提示 -->
    <div v-if="isDraggingEdge" class="drag-hint" :class="{ 'ready': hoverTargetNode }">
      <template v-if="hoverTargetNode">✓ 松开鼠标完成连接！</template>
      <template v-else>拖到目标节点的左侧端口 ● 建立连接</template>
    </div>

    <div class="body">
      <!-- Sidebar -->
      <aside class="sidebar">
        <div class="section">
          <div class="section-title">Skills <span>{{ skills.length }}</span></div>
          <div class="item-list">
            <div
              v-for="item in availableItems.filter(i => i.type === 'skill')"
              :key="item.id"
              class="item"
              draggable="true"
              @dragstart="e => e.dataTransfer?.setData('application/json', JSON.stringify(item))"
              @click="quickAdd(item)"
            >
              <span class="item-icon">{{ item.icon }}</span>
              <span class="item-name">{{ item.name }}</span>
              <span class="item-add">+</span>
            </div>
          </div>
        </div>

        <div v-if="workflows.length" class="section">
          <div class="section-title">子流程 <span>{{ workflows.length }}</span></div>
          <div class="item-list">
            <div
              v-for="item in availableItems.filter(i => i.type === 'workflow')"
              :key="item.id"
              class="item workflow"
              draggable="true"
              @dragstart="e => e.dataTransfer?.setData('application/json', JSON.stringify(item))"
              @click="quickAdd(item)"
            >
              <span class="item-icon">{{ item.icon }}</span>
              <span class="item-name">{{ item.name }}</span>
              <span class="item-add">+</span>
            </div>
          </div>
        </div>

        <div class="section help">
          <div class="section-title">操作指南</div>
          <ul>
            <li><span class="help-icon">➕</span> 点击添加节点</li>
            <li><span class="help-icon">🔗</span> 从 <b>●→</b> 拖到 <b>●</b></li>
            <li><span class="help-icon">🗑️</span> 点击连线删除</li>
          </ul>
        </div>
      </aside>

      <!-- Canvas -->
      <div
        ref="canvasRef"
        class="canvas"
        :class="{ 'dragging-edge': isDraggingEdge }"
        @mousemove="onMouseMove"
        @mouseup="onMouseUp"
        @mouseleave="onMouseUp"
        @dragover.prevent
        @drop="onDrop"
        @click="selectedNode = null"
      >
        <div class="grid"></div>

        <!-- Edges SVG -->
        <svg class="edges">
          <defs>
            <!-- 渐变 -->
            <linearGradient id="edgeGradient" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stop-color="#6366f1" />
              <stop offset="100%" stop-color="#8b5cf6" />
            </linearGradient>
            <linearGradient id="edgeGradientHover" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stop-color="#ef4444" />
              <stop offset="100%" stop-color="#f97316" />
            </linearGradient>
            <!-- 箭头 -->
            <marker id="arrow" markerWidth="12" markerHeight="10" refX="10" refY="5" orient="auto">
              <path d="M0 0 L12 5 L0 10 L3 5 Z" fill="#6366f1" />
            </marker>
            <marker id="arrow-hover" markerWidth="12" markerHeight="10" refX="10" refY="5" orient="auto">
              <path d="M0 0 L12 5 L0 10 L3 5 Z" fill="#ef4444" />
            </marker>
            <marker id="arrow-temp" markerWidth="10" markerHeight="8" refX="8" refY="4" orient="auto">
              <path d="M0 0 L10 4 L0 8 L2 4 Z" fill="#10b981" />
            </marker>
            <!-- 发光效果 -->
            <filter id="glow">
              <feGaussianBlur stdDeviation="2" result="coloredBlur"/>
              <feMerge>
                <feMergeNode in="coloredBlur"/>
                <feMergeNode in="SourceGraphic"/>
              </feMerge>
            </filter>
          </defs>

          <!-- 已有连线（底层阴影） -->
          <path
            v-for="edge in edges"
            :key="edge.id + '-shadow'"
            :d="getEdgePath(edge)"
            class="edge-shadow"
          />

          <!-- 已有连线 -->
          <g v-for="edge in edges" :key="edge.id" class="edge-group" @click.stop="deleteEdge(edge.id)">
            <path :d="getEdgePath(edge)" class="edge-hitarea" />
            <path :d="getEdgePath(edge)" class="edge" />
          </g>

          <!-- 临时连线 -->
          <g v-if="isDraggingEdge">
            <path :d="getTempEdgePath()" class="edge temp-shadow" />
            <path :d="getTempEdgePath()" class="edge temp" />
          </g>
        </svg>

        <!-- Nodes -->
        <div
          v-for="node in nodes"
          :key="node.id"
          class="node"
          :class="{
            selected: selectedNode === node.id,
            'is-workflow': node.type === 'workflow',
            'drop-target': hoverTargetNode === node.id,
            'is-source': edgeFromNode === node.id
          }"
          :style="{ left: node.position.x + 'px', top: node.position.y + 'px' }"
          @mousedown="startDragNode($event, node)"
          @click.stop="selectedNode = node.id"
        >
          <!-- 输入端口（左侧） -->
          <div
            class="port input"
            :class="{ 'port-active': isDraggingEdge && edgeFromNode !== node.id }"
            @mouseup="onInputPortMouseUp($event, node.id)"
          >
            <div class="port-ring"></div>
          </div>

          <div class="node-icon">{{ node.icon }}</div>
          <div class="node-info">
            <div class="node-name">{{ node.name }}</div>
            <div class="node-type">{{ node.type === 'workflow' ? '子流程' : 'Skill' }}</div>
          </div>

          <!-- 输出端口（右侧）- 拖拽建立连线 -->
          <div
            class="port output"
            @mousedown="startDragEdge($event, node.id)"
            title="从这里拖出连线"
          >
            <div class="port-ring"></div>
            <svg class="port-arrow" viewBox="0 0 24 24" fill="currentColor">
              <path d="M8 5v14l11-7z"/>
            </svg>
          </div>

          <!-- 删除按钮 -->
          <button class="delete-btn" @click.stop="deleteNode(node.id)">×</button>
        </div>

        <!-- Empty -->
        <div v-if="nodes.length === 0" class="empty">
          <div class="empty-icon">🔄</div>
          <h3>开始构建流程</h3>
          <p>点击左侧添加节点</p>
          <p class="sub-hint">从右侧 <span class="port-demo">●→</span> 拖拽到左侧 <span class="port-demo in">●</span> 建立连接</p>
          <button @click="loadExample">加载示例</button>
        </div>
      </div>
    </div>

    <!-- Footer - 显示自动生成的流程描述 -->
    <footer class="footer">
      <div class="footer-flow">
        <span class="flow-label">流程：</span>
        <span class="flow-desc">{{ autoDescription || '添加节点开始构建流程...' }}</span>
      </div>
      <div class="stats">{{ nodes.length }} 节点 · {{ edges.length }} 连接</div>
    </footer>
  </div>
</template>

<style scoped>
.builder {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #f8fafc;
  border-radius: 12px;
  overflow: hidden;
}

/* Header */
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  background: #fff;
  border-bottom: 1px solid #e2e8f0;
}
.header-left, .header-right { display: flex; align-items: center; gap: 8px; }

.back-btn {
  width: 32px; height: 32px;
  background: #f1f5f9; border: none; border-radius: 8px;
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  color: #64748b; transition: all 0.15s;
}
.back-btn:hover { background: #e2e8f0; color: #1e293b; }
.back-btn svg { width: 16px; height: 16px; }

/* Header 标题 */
.header-title {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-icon {
  width: 36px;
  height: 36px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.25);
}

.header-text {
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
}

.btn {
  padding: 7px 14px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
  display: flex;
  align-items: center;
  gap: 5px;
  border: none;
}

.btn svg {
  width: 14px;
  height: 14px;
}

.btn.text {
  background: transparent;
  color: #64748b;
}

.btn.text:hover {
  background: #f1f5f9;
  color: #475569;
}

.btn.text.danger {
  color: #94a3b8;
}

.btn.text.danger:hover {
  background: #fef2f2;
  color: #ef4444;
}

.btn.secondary {
  background: #f1f5f9;
  color: #64748b;
}

.btn.secondary:hover {
  background: #e2e8f0;
  color: #475569;
}

.btn.save {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.3);
}

.btn.save:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 16px rgba(99, 102, 241, 0.4);
}

.btn.save:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  transform: none;
}

.btn.primary {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
}

.btn.primary:hover:not(:disabled) {
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

/* Drag hint */
.drag-hint {
  padding: 10px 16px;
  text-align: center;
  background: linear-gradient(90deg, #e0e7ff, #dbeafe);
  border-bottom: 2px solid #6366f1;
  font-size: 12px;
  font-weight: 600;
  color: #4338ca;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  animation: hintPulse 1.5s ease infinite;
}
.drag-hint::before {
  content: '🔗';
  font-size: 14px;
}
.drag-hint.ready {
  background: linear-gradient(90deg, #dcfce7, #bbf7d0);
  border-bottom-color: #10b981;
  color: #047857;
  animation: none;
}
.drag-hint.ready::before {
  content: '✨';
}

@keyframes hintPulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.85; }
}

/* Body */
.body { flex: 1; display: flex; overflow: hidden; }

/* Sidebar */
.sidebar {
  width: 170px; background: #fff; border-right: 1px solid #e2e8f0;
  padding: 12px; overflow-y: auto; display: flex; flex-direction: column; gap: 14px;
}
.section { display: flex; flex-direction: column; gap: 6px; }
.section-title {
  font-size: 10px; font-weight: 600; color: #94a3b8;
  text-transform: uppercase; letter-spacing: 0.5px;
  display: flex; justify-content: space-between;
}
.section-title span { background: #f1f5f9; padding: 1px 5px; border-radius: 4px; font-size: 9px; }

.item-list { display: flex; flex-direction: column; gap: 3px; }
.item {
  display: flex; align-items: center; gap: 6px;
  padding: 7px 8px; background: #f8fafc; border: 1px solid #e2e8f0;
  border-radius: 6px; cursor: pointer; transition: all 0.15s;
}
.item:hover { background: #f1f5f9; border-color: #6366f1; }
.item:hover .item-add { opacity: 1; }
.item.workflow { background: rgba(99,102,241,0.06); border-color: rgba(99,102,241,0.2); }
.item-icon { font-size: 13px; }
.item-name { flex: 1; font-size: 11px; font-weight: 500; color: #475569; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.item-add { font-size: 12px; font-weight: 600; color: #6366f1; opacity: 0; transition: opacity 0.15s; }

.section.help { margin-top: auto; padding-top: 10px; border-top: 1px solid #e2e8f0; }
.section.help ul { list-style: none; padding: 0; margin: 0; font-size: 10px; color: #64748b; }
.section.help li {
  display: flex; align-items: center; gap: 6px;
  padding: 4px 0; border-bottom: 1px dashed #f1f5f9;
}
.section.help li:last-child { border-bottom: none; }
.section.help .help-icon { font-size: 11px; }
.section.help b { color: #6366f1; font-weight: 700; }

/* Canvas */
.canvas {
  flex: 1; position: relative; overflow: hidden;
}
.canvas.dragging-edge { cursor: crosshair; }

.grid {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(0,0,0,0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,0,0,0.03) 1px, transparent 1px);
  background-size: 20px 20px;
}

/* Edges */
.edges { position: absolute; inset: 0; pointer-events: none; overflow: visible; }

.edge-shadow {
  fill: none;
  stroke: rgba(99, 102, 241, 0.15);
  stroke-width: 8;
  stroke-linecap: round;
}

.edge-group { cursor: pointer; }
.edge-hitarea {
  fill: none;
  stroke: transparent;
  stroke-width: 20;
  pointer-events: stroke;
}

.edge {
  fill: none;
  stroke: url(#edgeGradient);
  stroke-width: 3;
  stroke-linecap: round;
  marker-end: url(#arrow);
  transition: all 0.2s ease;
  pointer-events: none;
}

.edge-group:hover .edge {
  stroke: url(#edgeGradientHover);
  stroke-width: 4;
  marker-end: url(#arrow-hover);
  filter: url(#glow);
}

.edge-group:hover .edge-shadow {
  stroke: rgba(239, 68, 68, 0.2);
}

.edge.temp-shadow {
  stroke: rgba(16, 185, 129, 0.2);
  stroke-width: 10;
  stroke-dasharray: none;
  marker-end: none;
}

.edge.temp {
  stroke: #10b981;
  stroke-width: 3;
  stroke-dasharray: 8 4;
  marker-end: url(#arrow-temp);
  animation: dashMove 0.5s linear infinite;
}

@keyframes dashMove {
  to { stroke-dashoffset: -12; }
}

/* Nodes */
.node {
  position: absolute; width: 150px; height: 70px;
  background: #fff; border: 2px solid #e2e8f0; border-radius: 12px;
  display: flex; align-items: center; gap: 8px; padding: 0 12px;
  cursor: grab; box-shadow: 0 2px 8px rgba(0,0,0,0.06);
  transition: all 0.2s ease; user-select: none;
}
.node:hover { border-color: #cbd5e1; box-shadow: 0 4px 16px rgba(0,0,0,0.1); }
.node.selected { border-color: #6366f1; box-shadow: 0 0 0 3px rgba(99,102,241,0.2); }
.node.is-workflow { background: rgba(99,102,241,0.04); border-color: rgba(99,102,241,0.4); }
.node.drop-target {
  border-color: #10b981;
  box-shadow: 0 0 0 4px rgba(16,185,129,0.25), 0 4px 20px rgba(16,185,129,0.2);
  transform: scale(1.02);
}
.node.is-source {
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99,102,241,0.2);
}

.node-icon {
  width: 36px; height: 36px;
  background: #f8fafc; border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  font-size: 18px; flex-shrink: 0;
}
.node.is-workflow .node-icon { background: linear-gradient(135deg, #6366f1, #8b5cf6); }

.node-info { flex: 1; overflow: hidden; }
.node-name { font-size: 12px; font-weight: 600; color: #1e293b; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.node-type { font-size: 9px; color: #94a3b8; margin-top: 2px; }

/* Ports */
.port {
  position: absolute;
  width: 16px; height: 16px;
  display: flex; align-items: center; justify-content: center;
  z-index: 10;
  transition: all 0.2s ease;
}

.port-ring {
  width: 12px; height: 12px;
  background: #fff;
  border: 2px solid #cbd5e1;
  border-radius: 50%;
  transition: all 0.2s ease;
}

/* 输入端口（左侧） */
.port.input {
  left: -8px; top: 50%; transform: translateY(-50%);
  cursor: default;
}

.port.input .port-ring {
  width: 10px; height: 10px;
  background: #f1f5f9;
  border-color: #94a3b8;
}

.port.input.port-active .port-ring {
  width: 18px; height: 18px;
  background: #dcfce7;
  border-color: #10b981;
  border-width: 3px;
  animation: portPulse 1s ease infinite;
}

.node.drop-target .port.input .port-ring {
  width: 20px; height: 20px;
  background: #10b981;
  border-color: #10b981;
}

/* 输出端口（右侧） */
.port.output {
  right: -8px; top: 50%; transform: translateY(-50%);
  width: 28px; height: 28px;
  cursor: crosshair;
}

.port.output .port-ring {
  width: 20px; height: 20px;
  background: linear-gradient(135deg, #f8fafc, #fff);
  border: 2px solid #6366f1;
  box-shadow: 0 2px 6px rgba(99, 102, 241, 0.2);
}

.port.output .port-arrow {
  position: absolute;
  width: 10px; height: 10px;
  color: #6366f1;
  transition: all 0.2s ease;
}

.port.output:hover {
  transform: translateY(-50%) scale(1.15);
}

.port.output:hover .port-ring {
  background: #6366f1;
  border-color: #6366f1;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4);
}

.port.output:hover .port-arrow {
  color: #fff;
  transform: scale(1.2);
}

@keyframes portPulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.4); }
  50% { box-shadow: 0 0 0 8px rgba(16, 185, 129, 0); }
}

/* Delete button */
.delete-btn {
  position: absolute; top: -8px; right: -8px;
  width: 18px; height: 18px;
  background: #ef4444; border: 2px solid #fff; border-radius: 50%;
  color: #fff; font-size: 12px; font-weight: 700;
  cursor: pointer; opacity: 0; transition: opacity 0.15s;
  display: flex; align-items: center; justify-content: center; line-height: 1;
}
.node:hover .delete-btn { opacity: 1; }

/* Empty state */
.empty {
  position: absolute; inset: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  text-align: center;
}
.empty-icon { font-size: 40px; margin-bottom: 12px; opacity: 0.6; }
.empty h3 { font-size: 16px; font-weight: 600; color: #475569; margin: 0 0 6px; }
.empty p { font-size: 12px; color: #94a3b8; margin: 0 0 6px; }
.empty .sub-hint {
  font-size: 11px;
  color: #64748b;
  background: #f8fafc;
  padding: 8px 14px;
  border-radius: 8px;
  margin-bottom: 16px;
  border: 1px dashed #e2e8f0;
}
.empty .port-demo {
  display: inline-flex;
  align-items: center;
  gap: 1px;
  font-weight: 700;
  color: #6366f1;
}
.empty .port-demo.in { color: #10b981; }
.empty button {
  padding: 10px 20px; background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border: none; border-radius: 8px;
  color: #fff; font-size: 12px; font-weight: 600; cursor: pointer;
  transition: all 0.2s ease;
}
.empty button:hover {
  background: linear-gradient(135deg, #4f46e5, #7c3aed);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4);
  transform: translateY(-1px);
}

/* Footer - 流程描述 */
.footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  background: #fff;
  border-top: 1px solid #e2e8f0;
}

.footer-flow {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
}

.flow-label {
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
  flex-shrink: 0;
}

.flow-desc {
  font-size: 12px;
  color: #475569;
  font-family: monospace;
  background: #f8fafc;
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stats {
  font-size: 11px;
  color: #94a3b8;
  background: #f1f5f9;
  padding: 4px 10px;
  border-radius: 12px;
  flex-shrink: 0;
  margin-left: 12px;
}

/* 保存对话框 */
.save-dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  backdrop-filter: blur(4px);
}

.save-dialog {
  background: #fff;
  border-radius: 16px;
  width: 400px;
  max-width: 90vw;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.2);
  overflow: hidden;
}

.save-dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid #e2e8f0;
}

.save-dialog-header h3 {
  font-size: 16px;
  font-weight: 600;
  color: #1e293b;
  margin: 0;
}

.close-btn {
  width: 28px;
  height: 28px;
  background: #f1f5f9;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #64748b;
  transition: all 0.15s ease;
}

.close-btn:hover {
  background: #fee2e2;
  color: #ef4444;
}

.close-btn svg {
  width: 14px;
  height: 14px;
}

.save-dialog-body {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-group label {
  font-size: 12px;
  font-weight: 600;
  color: #475569;
}

.form-group .required {
  color: #ef4444;
}

.form-group .optional {
  font-weight: 400;
  color: #94a3b8;
}

.icon-select {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.icon-option {
  width: 36px;
  height: 36px;
  background: #f8fafc;
  border: 2px solid #e2e8f0;
  border-radius: 10px;
  font-size: 18px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.icon-option:hover {
  border-color: #c7d2fe;
  background: #eef2ff;
  transform: scale(1.05);
}

.icon-option.active {
  border-color: #6366f1;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.3);
}

.form-input,
.form-textarea {
  padding: 10px 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 14px;
  color: #1e293b;
  outline: none;
  transition: all 0.15s ease;
  font-family: inherit;
}

.form-input:focus,
.form-textarea:focus {
  border-color: #6366f1;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.form-input.error {
  border-color: #ef4444;
  background: #fef2f2;
}

.form-textarea {
  resize: none;
}

.error-msg {
  font-size: 11px;
  color: #ef4444;
}

.save-preview {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  background: #f8fafc;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
}

.preview-icon {
  width: 44px;
  height: 44px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.25);
}

.preview-info {
  flex: 1;
}

.preview-name {
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
}

.preview-meta {
  font-size: 11px;
  color: #94a3b8;
  margin-top: 2px;
}

.save-dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 20px;
  background: #f8fafc;
  border-top: 1px solid #e2e8f0;
}

/* 对话框动画 */
.dialog-enter-active,
.dialog-leave-active {
  transition: all 0.2s ease;
}

.dialog-enter-from,
.dialog-leave-to {
  opacity: 0;
}

.dialog-enter-from .save-dialog,
.dialog-leave-to .save-dialog {
  transform: scale(0.95) translateY(-10px);
}
</style>
