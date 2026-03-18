<script setup lang="ts">
import { ref, nextTick, watch, computed, onUnmounted, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { agentApi, dataNotesApi, type ChatMessage, type DataNote } from '@/api'
import SlashCommandPopup from './SlashCommandPopup.vue'

// 输出文件类型
interface OutputFile {
  type: 'ppt' | 'word' | 'markdown' | 'pdf' | 'png' | 'jpg' | 'video' | 'html' | 'excel' | 'code' | 'file' | 'other'
  name: string
  url: string
  size?: string
}

interface SkillStep {
  id: number
  skillId?: string  // 数据库中的技能ID (UUID)，用于执行
  nodeId: string  // 原始节点ID，用于追踪边关系
  skillName: string
  skillIcon: string
  description: string
  status: 'pending' | 'running' | 'completed' | 'error' | 'missing' | 'configuring'
  output?: string
  userInput?: string  // 用户输入的参数/指令
  outputFile?: OutputFile  // 输出文件
  errorDetails?: {  // 执行结果详情（用于分析和建议）
    error?: string
    output?: string
  }
  // 历史执行结果（重跑时保留之前的结果）
  outputHistory?: {
    id: number
    timestamp: Date
    output?: string
    outputFile?: OutputFile
    userInput?: string
  }[]
}

interface PipelineEdge {
  from: string
  to: string
}

// 消息附件
interface MessageAttachment {
  id: string
  name: string
  type: string
  size: number
  url?: string
  serverPath?: string  // 服务器上的文件路径
}

interface Message {
  id: number
  type: 'user' | 'agent'
  content: string
  timestamp: Date
  skillPlan?: SkillStep[]
  pipelineEdges?: PipelineEdge[]  // 边的关系
  dataNodes?: Record<string, any>  // 数据节点信息（用于获取输入文件）
  waitingForSkill?: string // 等待添加的技能名
  pipelineGroupId?: string  // 关联的 group ID
  attachments?: MessageAttachment[]  // 附件
}

// 新增：流程组接口
interface PipelineGroup {
  id: string                    // 唯一标识 'pg-{messageId}'
  name: string                  // 流程名称（从用户消息提取）
  description: string           // 完整的用户请求
  createdAt: Date

  // 关联的消息
  messageRange: {
    startMessageId: number      // 触发该流程的用户消息ID
    endMessageId: number        // agent响应消息ID
    messageIds: number[]        // 所有相关消息ID
  }

  // 流程数据
  skillPlan: SkillStep[]
  pipelineEdges: PipelineEdge[]

  // 状态
  status: 'pending' | 'running' | 'completed' | 'paused' | 'error'
  progress: { completed: number; total: number }

  // UI状态
  isExpanded: boolean
  isSaved: boolean
}

interface Skill {
  id: string  // UUID
  name: string
  icon: string
  description: string
  tags: string[]
  author: string
  version: string
}

const props = defineProps<{
  skills: Skill[]
}>()

const emit = defineEmits<{
  gotoSkills: [skillName: string, mode: 'create' | 'upload']
  saveWorkflow: [workflow: { name: string; description: string; nodes: any[]; edges: any[] }]
}>()

const messages = ref<Message[]>([
  {
    id: 1,
    type: 'agent',
    content: '你好！我是 AI Agent，可以帮你编排和执行各种技能来完成复杂任务。试着告诉我你想做什么？',
    timestamp: new Date()
  }
])

const inputText = ref('')
const isProcessing = ref(false)
const chatContainer = ref<HTMLElement | null>(null)
const pendingExecution = ref<{ messageId: number; skills: SkillStep[] } | null>(null)
const showContinueDialog = ref(false)
const addedSkillName = ref('')

// Workflow 执行
const pendingWorkflow = ref<any>(null)
const workflowContext = ref('')

// 暂停/继续执行控制
const isPaused = ref(false)
const pausedMessageId = ref<number | null>(null)
// 被删除的 skill 的 ID 列表（用于跳过其上下文）
const deletedSkillIds = ref<Set<string>>(new Set())
// 干净执行模式：记录哪个 messageId 的流水线需要忽略之前的运行结果
// 只对指定的 messageId 生效，不影响其他流水线
const cleanExecutionMessageId = ref<number | null>(null)

// 文件上传
interface UploadedFile {
  id: string
  name: string
  type: string
  size: number
  url?: string  // 预览URL
  file: File
  serverPath?: string  // 服务器上的文件路径
  uploading?: boolean  // 是否正在上传
  uploadError?: string  // 上传错误
}
const uploadedFiles = ref<UploadedFile[]>([])
const fileInputRef = ref<HTMLInputElement | null>(null)

// 数据便签（用于"/"补全和保存）
const dataNotesForSlash = ref<DataNote[]>([])

// "/" 补全弹窗
const slashPopupRef = ref<InstanceType<typeof SlashCommandPopup> | null>(null)
const showSlashPopup = ref(false)
const slashQuery = ref('')
const slashPopupPosition = ref({ x: 0, y: 0 })

// 加载便签数据（用于"/"补全，只加载根目录）
const loadDataNotesForSlash = async () => {
  try {
    dataNotesForSlash.value = await dataNotesApi.getAll({ parentId: null })
  } catch (e) {
    console.error('Failed to load data notes:', e)
  }
}

// 保存文件到便签
const saveToDataNotes = async (outputFile: OutputFile, skillName?: string) => {
  try {
    await dataNotesApi.create({
      name: outputFile.name,
      description: `由技能 ${skillName || '未知'} 生成`,
      file_type: outputFile.type,
      file_url: outputFile.url,
      file_size: outputFile.size,
      source_skill: skillName
    })
    // 刷新便签列表供"/"补全使用
    loadDataNotesForSlash()
  } catch (e) {
    console.error('Failed to save to data notes:', e)
  }
}

// 检测 "/" 命令输入
const handleInputKeydown = (e: KeyboardEvent) => {
  // 处理 "/" 补全的键盘导航
  if (showSlashPopup.value) {
    const navKeys = ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Enter', 'Escape', 'Backspace']
    if (navKeys.includes(e.key)) {
      // Backspace 在有查询时允许正常删除
      if (e.key === 'Backspace' && slashQuery.value) {
        return
      }
      e.preventDefault()
      e.stopPropagation()
      slashPopupRef.value?.handleKeydown(e)
      return
    }
  }

  // 回车发送消息（弹窗不显示时）
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessage()
  }
}

// 输入框内容变化时检测 "/"
const handleInputChange = () => {
  const text = inputText.value
  const lastSlashIndex = text.lastIndexOf('/')

  if (lastSlashIndex >= 0) {
    // 检查 "/" 前是否是空格或行首
    const charBefore = lastSlashIndex > 0 ? text[lastSlashIndex - 1] : ' '
    if (charBefore === ' ' || charBefore === '\n' || lastSlashIndex === 0) {
      const query = text.slice(lastSlashIndex + 1)
      // 只在查询没有空格时显示弹窗
      if (!query.includes(' ') && !query.includes('\n')) {
        // 如果弹窗之前没显示，加载根目录数据
        if (!showSlashPopup.value) {
          loadDataNotesForSlash()
        }
        slashQuery.value = query
        showSlashPopup.value = true
        // 计算弹窗位置（在输入框上方）
        const textarea = document.querySelector('.chat-input textarea')
        if (textarea) {
          const rect = textarea.getBoundingClientRect()
          slashPopupPosition.value = { x: rect.left + 10, y: rect.top }
        }
        return
      }
    }
  }

  // 关闭弹窗
  if (showSlashPopup.value) {
    closeSlashPopup()
  }
}

// 待发送的数据引用（通过 "/" 选择的）
interface PendingRef {
  id: string
  name: string
  type: string
  file_url: string
  isFolder: boolean
  folderId?: string
}
const pendingRefs = ref<PendingRef[]>([])

// 选择 "/" 补全项（文件直接添加，文件夹显示为文件夹标签，发送时展开）
const handleSlashSelect = (note: DataNote, isFolder: boolean) => {
  const text = inputText.value
  const lastSlashIndex = text.lastIndexOf('/')

  // 移除 "/" 及其后的查询
  if (lastSlashIndex >= 0) {
    inputText.value = text.slice(0, lastSlashIndex)
  }

  if (isFolder) {
    // 文件夹：显示文件夹标签，发送时再展开
    pendingRefs.value.push({
      id: `ref-${Date.now()}`,
      name: note.name,
      type: 'folder',
      file_url: '',
      isFolder: true,
      folderId: note.id
    })
  } else if (note.file_url) {
    // 普通文件：直接添加
    pendingRefs.value.push({
      id: `ref-${Date.now()}`,
      name: note.name,
      type: note.file_type,
      file_url: note.file_url,
      isFolder: false
    })
  }

  // 关闭弹窗
  closeSlashPopup()
}

// 移除待发送引用
const removePendingRef = (id: string) => {
  pendingRefs.value = pendingRefs.value.filter(r => r.id !== id)
}

// blur 延迟关闭的 timer
let blurCloseTimer: number | null = null

// 关闭 "/" 弹窗
const closeSlashPopup = () => {
  if (blurCloseTimer) {
    clearTimeout(blurCloseTimer)
    blurCloseTimer = null
  }
  showSlashPopup.value = false
}

// 输入框失去焦点时延迟关闭弹窗（允许点击弹窗中的选项）
const handleInputBlur = () => {
  blurCloseTimer = window.setTimeout(() => {
    if (showSlashPopup.value) {
      closeSlashPopup()
    }
    blurCloseTimer = null
  }, 300)  // 延迟稍长一点，让级联菜单有时间响应
}

// 停止控制器
let abortController: AbortController | null = null

// 强制停止
const stopProcessing = () => {
  if (abortController) {
    abortController.abort()
    abortController = null
  }
  isProcessing.value = false
}

// 清空对话（新建会话）
const clearConversation = () => {
  // 停止任何进行中的处理
  stopProcessing()

  // 重置消息
  messages.value = [{
    id: Date.now(),
    type: 'agent',
    content: '你好！我是 AI Agent，可以帮你编排和执行各种技能来完成复杂任务。试着告诉我你想做什么？',
    timestamp: new Date()
  }]

  // 清空上传的文件和待发送引用
  uploadedFiles.value = []
  pendingRefs.value = []

  // 重置流程相关状态
  collapsedGroups.value.clear()
  savedGroups.value.clear()
  activeGroupId.value = null
  pendingExecution.value = null

  // 关闭所有对话框
  showContinueDialog.value = false
  showSaveDialog.value = false
  showDeleteConfirm.value = false
  showSkillExecution.value = false

  // 重置暂停状态
  isPaused.value = false
  pausedMessageId.value = null
  pendingWorkflow.value = null
  workflowContext.value = ''
  deletedSkillIds.value.clear()
  cleanExecutionMessageId.value = null

  scrollToBottom()
}

// 文件上传处理
const handleFileSelect = (event: Event) => {
  const input = event.target as HTMLInputElement
  if (input.files) {
    addFiles(Array.from(input.files))
  }
  // 重置 input 以便可以再次选择相同文件
  input.value = ''
}

const addFiles = async (files: File[]) => {
  const newFiles: UploadedFile[] = files.map(file => ({
    id: `file-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    name: file.name,
    type: file.type,
    size: file.size,
    url: file.type.startsWith('image/') ? URL.createObjectURL(file) : undefined,
    file,
    uploading: true
  }))
  uploadedFiles.value.push(...newFiles)

  // 上传文件到服务器
  for (const uploadedFile of newFiles) {
    try {
      const response = await agentApi.upload(uploadedFile.file)
      // 更新文件信息
      const idx = uploadedFiles.value.findIndex(f => f.id === uploadedFile.id)
      if (idx !== -1) {
        uploadedFiles.value[idx] = {
          ...uploadedFiles.value[idx],
          serverPath: response.path,
          uploading: false
        }
      }
    } catch (error: any) {
      console.error('File upload failed:', error)
      const idx = uploadedFiles.value.findIndex(f => f.id === uploadedFile.id)
      if (idx !== -1) {
        uploadedFiles.value[idx] = {
          ...uploadedFiles.value[idx],
          uploading: false,
          uploadError: error.message || '上传失败'
        }
      }
    }
  }
}

const removeFile = (fileId: string) => {
  const file = uploadedFiles.value.find(f => f.id === fileId)
  if (file?.url) {
    URL.revokeObjectURL(file.url)
  }
  uploadedFiles.value = uploadedFiles.value.filter(f => f.id !== fileId)
}

const triggerFileUpload = () => {
  fileInputRef.value?.click()
}

// 拖拽上传
const handleDrop = (e: DragEvent) => {
  e.preventDefault()
  if (e.dataTransfer?.files) {
    addFiles(Array.from(e.dataTransfer.files))
  }
}

// 格式化文件大小
const formatFileSize = (bytes: number): string => {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

// 获取文件图标
const getFileIcon = (type: string): string => {
  if (type.startsWith('image/')) return '🖼️'
  if (type.includes('pdf')) return '📕'
  if (type.includes('word') || type.includes('document')) return '📄'
  if (type.includes('excel') || type.includes('spreadsheet')) return '📊'
  if (type.includes('powerpoint') || type.includes('presentation')) return '📽️'
  if (type.includes('video')) return '🎬'
  if (type.includes('audio')) return '🎵'
  if (type.includes('text') || type.includes('markdown')) return '📝'
  if (type.includes('zip') || type.includes('archive')) return '📦'
  return '📎'
}

// 保存流程对话框
const showSaveDialog = ref(false)
const saveWorkflowName = ref('')
const saveWorkflowDesc = ref('')
const pendingSaveSkillPlan = ref<SkillStep[] | null>(null)
const pendingSaveEdges = ref<PipelineEdge[] | null>(null)

// 多流程管理
const collapsedGroups = ref<Set<string>>(new Set())  // 已折叠的流程组（默认展开）
const savedGroups = ref<Set<string>>(new Set())  // 已保存的流程组
const activeGroupId = ref<string | null>(null)  // 当前选中的流程组
const showDeleteConfirm = ref(false)
const pendingDeleteGroupId = ref<string | null>(null)
const pendingSaveGroup = ref<PipelineGroup | null>(null)

// 技能执行面板状态
const showSkillExecution = ref(false)
const executingSkill = ref<{ name: string; icon: string; description: string } | null>(null)
const executionContext = ref<string>('')
const executingStepInfo = ref<{ messageId: number; stepId: number; fromPaused?: boolean } | null>(null)
const skillSidePanelRef = ref<HTMLElement | null>(null)

// 面板宽度拖拽调整
const panelWidth = ref(380)  // 默认宽度
const isResizing = ref(false)
const resizeDirection = ref('')  // 调整方向: n, s, e, w, ne, nw, se, sw
const minPanelWidth = 300
const maxPanelWidth = 800
const minPanelHeight = 200
const maxPanelHeight = 800

// 浮动面板状态
const isFloating = ref(false)
const floatPosition = ref({ x: 0, y: 0 })
const floatSize = ref({ width: 480, height: 600 })  // 4:5 比例
const resizeStartPos = ref({ x: 0, y: 0 })
const resizeStartSize = ref({ width: 0, height: 0 })
const resizeStartPosition = ref({ x: 0, y: 0 })
const isDraggingPanel = ref(false)
const dragOffset = ref({ x: 0, y: 0 })
const magnetDistance = 80  // 磁吸距离
const hasLeftDockArea = ref(false)  // 是否已经离开过停靠区域

// 面板文件上传状态
const panelFileInputRef = ref<HTMLInputElement | null>(null)
const panelUploadedFiles = ref<UploadedFile[]>([])
const panelIsDragging = ref(false)
const panelCollectedFilePaths = ref<string[]>([])  // 收集的文件路径，执行时传递

// 开始拖拽移动面板（通过头部拖拽）
const startDragPanel = (e: MouseEvent) => {
  e.preventDefault()
  isDraggingPanel.value = true
  hasLeftDockArea.value = false  // 重置

  const panel = skillSidePanelRef.value
  if (!panel) return

  const rect = panel.getBoundingClientRect()

  if (!isFloating.value) {
    // 第一次拖拽，变成浮动状态
    isFloating.value = true
    // 初始位置设置为面板中心跟随鼠标
    floatPosition.value = {
      x: e.clientX - floatSize.value.width / 2,
      y: e.clientY - 20
    }
  }

  dragOffset.value = {
    x: e.clientX - floatPosition.value.x,
    y: e.clientY - floatPosition.value.y
  }

  document.addEventListener('mousemove', onDragPanel)
  document.addEventListener('mouseup', stopDragPanel)
  document.body.style.cursor = 'move'
  document.body.style.userSelect = 'none'
}

const onDragPanel = (e: MouseEvent) => {
  if (!isDraggingPanel.value) return

  let newX = e.clientX - dragOffset.value.x
  let newY = e.clientY - dragOffset.value.y

  // 边界限制
  const maxX = window.innerWidth - floatSize.value.width
  const maxY = window.innerHeight - floatSize.value.height
  newX = Math.max(0, Math.min(maxX, newX))
  newY = Math.max(0, Math.min(maxY, newY))

  const rightEdge = window.innerWidth - newX - floatSize.value.width

  // 检测是否离开过停靠区域（需要先拖离右侧才能触发磁吸）
  if (rightEdge > magnetDistance * 2) {
    hasLeftDockArea.value = true
  }

  // 只有离开过停靠区域后，再靠近右侧才触发磁吸
  if (hasLeftDockArea.value && rightEdge < magnetDistance) {
    isFloating.value = false
    panelWidth.value = 380
    hasLeftDockArea.value = false
    // 停止拖拽
    isDraggingPanel.value = false
    document.removeEventListener('mousemove', onDragPanel)
    document.removeEventListener('mouseup', stopDragPanel)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
    return
  }

  floatPosition.value = { x: newX, y: newY }
}

const stopDragPanel = () => {
  isDraggingPanel.value = false
  document.removeEventListener('mousemove', onDragPanel)
  document.removeEventListener('mouseup', stopDragPanel)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
}

// 面板样式计算
const panelStyle = computed(() => {
  if (isFloating.value) {
    return {
      position: 'fixed',
      top: floatPosition.value.y + 'px',
      left: floatPosition.value.x + 'px',
      right: 'auto',
      width: floatSize.value.width + 'px',
      height: floatSize.value.height + 'px',
      borderRadius: '12px',
      boxShadow: '0 8px 32px rgba(0, 0, 0, 0.15)'
    }
  }
  return {
    width: panelWidth.value + 'px'
  }
})

const startResize = (e: MouseEvent, direction?: string) => {
  e.preventDefault()
  e.stopPropagation()
  isResizing.value = true
  resizeDirection.value = direction || 'w'
  resizeStartPos.value = { x: e.clientX, y: e.clientY }
  resizeStartSize.value = { ...floatSize.value }
  resizeStartPosition.value = { ...floatPosition.value }

  document.addEventListener('mousemove', onResize)
  document.addEventListener('mouseup', stopResize)

  // 设置光标
  const cursorMap: Record<string, string> = {
    n: 'ns-resize', s: 'ns-resize',
    e: 'ew-resize', w: 'ew-resize',
    ne: 'nesw-resize', sw: 'nesw-resize',
    nw: 'nwse-resize', se: 'nwse-resize'
  }
  document.body.style.cursor = cursorMap[direction || 'w'] || 'col-resize'
  document.body.style.userSelect = 'none'
}

const onResize = (e: MouseEvent) => {
  if (!isResizing.value) return

  const dir = resizeDirection.value
  const dx = e.clientX - resizeStartPos.value.x
  const dy = e.clientY - resizeStartPos.value.y

  if (isFloating.value) {
    // 浮动模式：多方向调整
    let newWidth = resizeStartSize.value.width
    let newHeight = resizeStartSize.value.height
    let newX = resizeStartPosition.value.x
    let newY = resizeStartPosition.value.y

    // 水平方向
    if (dir.includes('e')) {
      newWidth = resizeStartSize.value.width + dx
    } else if (dir.includes('w')) {
      newWidth = resizeStartSize.value.width - dx
      newX = resizeStartPosition.value.x + dx
    }

    // 垂直方向
    if (dir.includes('s')) {
      newHeight = resizeStartSize.value.height + dy
    } else if (dir.includes('n')) {
      newHeight = resizeStartSize.value.height - dy
      newY = resizeStartPosition.value.y + dy
    }

    // 应用限制
    newWidth = Math.min(maxPanelWidth, Math.max(minPanelWidth, newWidth))
    newHeight = Math.min(maxPanelHeight, Math.max(minPanelHeight, newHeight))

    // 如果尺寸被限制，调整位置
    if (dir.includes('w') && newWidth !== resizeStartSize.value.width - dx) {
      newX = resizeStartPosition.value.x + resizeStartSize.value.width - newWidth
    }
    if (dir.includes('n') && newHeight !== resizeStartSize.value.height - dy) {
      newY = resizeStartPosition.value.y + resizeStartSize.value.height - newHeight
    }

    // 边界限制
    newX = Math.max(0, Math.min(window.innerWidth - newWidth, newX))
    newY = Math.max(0, Math.min(window.innerHeight - newHeight, newY))

    floatSize.value = { width: newWidth, height: newHeight }
    floatPosition.value = { x: newX, y: newY }
  } else {
    // 停靠模式：只调整宽度
    const newWidth = window.innerWidth - e.clientX
    panelWidth.value = Math.min(maxPanelWidth, Math.max(minPanelWidth, newWidth))
  }
}

const stopResize = () => {
  isResizing.value = false
  resizeDirection.value = ''
  document.removeEventListener('mousemove', onResize)
  document.removeEventListener('mouseup', stopResize)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
}

// 点击面板外部时关闭面板
const handleClickOutsidePanel = (e: MouseEvent) => {
  if (!showSkillExecution.value) return
  if (!skillSidePanelRef.value) return
  if (isResizing.value) return  // 拖拽调整宽度时不关闭
  if (isDraggingPanel.value) return  // 拖拽移动面板时不关闭

  // 检查点击是否在面板外部
  if (!skillSidePanelRef.value.contains(e.target as Node)) {
    closeSkillExecution(true)
  }
}

// 监听面板显示状态，添加/移除点击外部关闭的事件监听
watch(showSkillExecution, (isShow) => {
  if (isShow) {
    // 延迟添加监听，避免打开面板的点击事件立即触发关闭
    setTimeout(() => {
      document.addEventListener('click', handleClickOutsidePanel)
    }, 100)
  } else {
    document.removeEventListener('click', handleClickOutsidePanel)
  }
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutsidePanel)
  window.removeEventListener('data-notes-changed', handleDataNotesChange)
  showSlashPopup.value = false  // 关闭 "/" 弹窗
})

// 监听数据便签变化
const handleDataNotesChange = () => {
  loadDataNotesForSlash()
}

onMounted(() => {
  loadDataNotesForSlash()
  window.addEventListener('data-notes-changed', handleDataNotesChange)
})

// 监听输入框变化检测 "/" 命令
watch(inputText, handleInputChange)

// 监听路由变化，关闭弹窗
const route = useRoute()
watch(() => route.path, () => {
  showSlashPopup.value = false
})

// 右侧技能面板相关状态
interface SkillPanelMessage {
  id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: Date
  isExecuting?: boolean
  isConfirmation?: boolean  // 是否是确认消息
}
const skillPanelMessages = ref<SkillPanelMessage[]>([])
const skillPanelInput = ref('')
const skillPanelProcessing = ref(false)
const skillPanelComplete = ref(false)
const skillPanelParams = ref<Record<string, any>>({})
const skillPanelChatRef = ref<HTMLElement | null>(null)
const skillPanelInputRef = ref<HTMLTextAreaElement | null>(null)
const skillPanelWaitingConfirm = ref(false)  // 等待用户确认
const skillPanelSummary = ref('')  // AI 总结的内容

// 需要交互的技能列表（可配置）
const interactiveSkills = new Set([
  'frontend-design',
  'image-analyzer',
  'data-visualizer',
  'smart-translator',
  'doc-parser',
  'code-reviewer'
])

// 检查技能是否需要交互
const needsInteraction = (skillName: string): boolean => {
  return interactiveSkills.has(skillName)
}

// 已创建的 Blob URL 列表，用于清理
const createdBlobUrls: string[] = []

// 生成输出文件 - 当后端没有返回文件时，创建一个基于输出内容的本地文件
const generateOutputFile = (
  skillName: string,
  description: string,
  output?: string
): OutputFile | undefined => {
  // 如果没有输出内容，返回 undefined
  if (!output) return undefined

  const timestamp = new Date().toLocaleString('zh-CN')
  const shortName = skillName.length > 12 ? skillName.substring(0, 12) + '...' : skillName
  const nameLower = skillName.toLowerCase()

  // 检测输出内容是否是完整的 HTML
  const trimmedOutput = output.trim().toLowerCase()
  const isHtmlContent = trimmedOutput.startsWith('<!doctype') || trimmedOutput.startsWith('<html')

  // 检测技能名称是否与 HTML/前端相关
  const isHtmlSkill = nameLower.includes('html') || nameLower.includes('frontend') ||
                      nameLower.includes('design') || nameLower.includes('页面') ||
                      nameLower.includes('前端')

  // 如果是 HTML 内容或 HTML 相关技能，生成 HTML 文件
  if (isHtmlContent || isHtmlSkill) {
    let htmlContent: string
    if (isHtmlContent) {
      // 输出已经是完整 HTML，直接使用
      htmlContent = output
    } else {
      // 包装成 HTML
      htmlContent = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${skillName} - 执行结果</title>
  <style>
    body { font-family: -apple-system, sans-serif; padding: 40px; background: #f5f5f5; }
    .container { max-width: 800px; margin: 0 auto; background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); }
    h1 { color: #1e293b; margin-bottom: 20px; }
    pre { background: #f8fafc; padding: 16px; border-radius: 8px; overflow-x: auto; }
    .meta { margin-top: 30px; color: #94a3b8; font-size: 12px; }
  </style>
</head>
<body>
  <div class="container">
    <h1>${skillName}</h1>
    <p>${description}</p>
    <pre>${output}</pre>
    <div class="meta">生成时间: ${timestamp}</div>
  </div>
</body>
</html>`
    }

    const blob = new Blob([htmlContent], { type: 'text/html;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    createdBlobUrls.push(url)

    return {
      type: 'html',
      name: `${shortName}-结果.html`,
      url: url,
      size: `${(blob.size / 1024).toFixed(1)} KB`
    }
  }

  // 默认生成 Markdown 文件
  const content = `# ${skillName} 执行结果

## 任务描述
${description}

## 执行输出
${output}

---
生成时间: ${timestamp}
`

  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  createdBlobUrls.push(url)

  return {
    type: 'markdown',
    name: `${shortName}-结果.md`,
    url: url,
    size: `${(blob.size / 1024).toFixed(1)} KB`
  }
}

// 清理 Blob URL（在组件卸载时调用）
onUnmounted(() => {
  createdBlobUrls.forEach(url => URL.revokeObjectURL(url))
})

// 打开技能执行面板
const openSkillExecution = (
  skill: { name: string; icon: string; description: string },
  context?: string,
  messageId?: number,
  stepId?: number
) => {
  executingSkill.value = skill
  executionContext.value = context || ''
  executingStepInfo.value = messageId && stepId ? { messageId, stepId } : null

  // 初始化面板状态
  skillPanelMessages.value = []
  skillPanelInput.value = ''
  skillPanelProcessing.value = false
  skillPanelComplete.value = false
  skillPanelParams.value = {}

  showSkillExecution.value = true

  // 生成初始问候消息
  nextTick(() => {
    const greeting = generatePanelGreeting(skill, context)
    skillPanelMessages.value.push({
      id: 1,
      role: 'assistant',
      content: greeting,
      timestamp: new Date()
    })
    skillPanelInputRef.value?.focus()
  })
}

// 生成面板问候语
const generatePanelGreeting = (skill: { name: string; description: string }, context?: string) => {
  if (context) {
    if (context.includes('画') || context.includes('设计') || context.includes('图')) {
      return `收到！我来帮你「${context}」\n\n请告诉我更多细节：\n• 风格偏好（简约/华丽/科技感...）\n• 配色要求\n• 其他特殊需求\n\n我会根据你的要求生成方案供你确认。`
    }
    return `好的，关于「${context}」\n\n请补充说明你的具体需求，我会总结后请你确认。`
  }
  return `Hi! 我是 **${skill.name}**\n\n${skill.description}\n\n请告诉我你的具体需求，我会整理后请你确认再执行。`
}

// 关闭技能执行面板
const closeSkillExecution = (cancelled = false) => {
  // 如果是取消关闭，恢复 configuring 状态的步骤
  if (cancelled && executingStepInfo.value) {
    const { messageId, stepId, fromPaused } = executingStepInfo.value
    const msg = messages.value.find(m => m.id === messageId)
    if (msg?.skillPlan) {
      const stepIndex = msg.skillPlan.findIndex(s => s.id === stepId)
      if (stepIndex !== -1) {
        const currentStep = msg.skillPlan[stepIndex]

        if (fromPaused) {
          // 从暂停状态取消，恢复为 running（暂停状态）
          currentStep.status = 'running'
          // 不需要重置 pendingExecution，保持暂停状态
        } else {
          // 从完成状态重跑取消，恢复历史状态
          for (let i = stepIndex; i < msg.skillPlan.length; i++) {
            const s = msg.skillPlan[i]
            if (s.outputHistory?.length) {
              const lastHistory = s.outputHistory.pop()
              s.status = 'completed'
              s.output = lastHistory?.output
              s.outputFile = lastHistory?.outputFile
              s.userInput = lastHistory?.userInput
            } else {
              s.status = 'pending'
            }
          }
          pendingExecution.value = null
        }
      }
    }
  }

  showSkillExecution.value = false
  executingSkill.value = null
  executionContext.value = ''
  executingStepInfo.value = null
  skillPanelMessages.value = []
  skillPanelInput.value = ''
  skillPanelProcessing.value = false
  skillPanelComplete.value = false
  skillPanelWaitingConfirm.value = false
  skillPanelSummary.value = ''
  // 重置浮动状态
  isFloating.value = false
  panelWidth.value = 380
  // 清理面板上传的文件
  panelUploadedFiles.value.forEach(f => {
    if (f.url) URL.revokeObjectURL(f.url)
  })
  panelUploadedFiles.value = []
  panelCollectedFilePaths.value = []
}

// 面板文件上传处理
const panelHandleFileSelect = (event: Event) => {
  const input = event.target as HTMLInputElement
  if (input.files) {
    panelAddFiles(Array.from(input.files))
  }
  input.value = ''
}

const panelAddFiles = async (files: File[]) => {
  console.log('[panelAddFiles] 开始添加文件:', files.map(f => f.name))

  const newFiles: UploadedFile[] = files.map(file => ({
    id: `panel-file-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    name: file.name,
    type: file.type,
    size: file.size,
    url: file.type.startsWith('image/') ? URL.createObjectURL(file) : undefined,
    file,
    uploading: true
  }))
  panelUploadedFiles.value = [...panelUploadedFiles.value, ...newFiles]
  console.log('[panelAddFiles] 当前文件列表:', panelUploadedFiles.value.length)

  // 上传文件到服务器
  for (const uploadedFile of newFiles) {
    try {
      console.log('[panelAddFiles] 开始上传:', uploadedFile.name)
      const response = await agentApi.upload(uploadedFile.file)
      console.log('[panelAddFiles] 上传成功:', uploadedFile.name, '-> serverPath:', response.path)

      // 使用新数组触发响应式更新
      panelUploadedFiles.value = panelUploadedFiles.value.map(f =>
        f.id === uploadedFile.id
          ? { ...f, serverPath: response.path, uploading: false }
          : f
      )
      console.log('[panelAddFiles] 更新后的文件列表:', panelUploadedFiles.value.map(f => ({ name: f.name, serverPath: f.serverPath, uploading: f.uploading })))
    } catch (error: any) {
      console.error('[panelAddFiles] 上传失败:', uploadedFile.name, error)
      panelUploadedFiles.value = panelUploadedFiles.value.map(f =>
        f.id === uploadedFile.id
          ? { ...f, uploading: false, uploadError: error.message || '上传失败' }
          : f
      )
    }
  }
  console.log('[panelAddFiles] 所有文件处理完成, 文件列表:', panelUploadedFiles.value.map(f => ({ name: f.name, serverPath: f.serverPath })))
}

const panelRemoveFile = (fileId: string) => {
  const file = panelUploadedFiles.value.find(f => f.id === fileId)
  if (file?.url) {
    URL.revokeObjectURL(file.url)
  }
  panelUploadedFiles.value = panelUploadedFiles.value.filter(f => f.id !== fileId)
}

const panelTriggerFileUpload = () => {
  panelFileInputRef.value?.click()
}

// 面板拖拽上传事件
const panelHandleDragEnter = (e: DragEvent) => {
  e.preventDefault()
  e.stopPropagation()
  panelIsDragging.value = true
}

const panelHandleDragLeave = (e: DragEvent) => {
  e.preventDefault()
  e.stopPropagation()
  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
  const x = e.clientX
  const y = e.clientY
  if (x < rect.left || x > rect.right || y < rect.top || y > rect.bottom) {
    panelIsDragging.value = false
  }
}

const panelHandleDragOver = (e: DragEvent) => {
  e.preventDefault()
  e.stopPropagation()
}

const panelHandleDrop = (e: DragEvent) => {
  e.preventDefault()
  e.stopPropagation()
  panelIsDragging.value = false

  const files = e.dataTransfer?.files
  if (files && files.length > 0) {
    panelAddFiles(Array.from(files))
  }
}

// 发送面板消息 - 多轮对话
const sendSkillPanelMessage = async () => {
  const hasText = skillPanelInput.value.trim()
  const hasFiles = panelUploadedFiles.value.length > 0

  if ((!hasText && !hasFiles) || skillPanelProcessing.value) return

  let userMessage = skillPanelInput.value.trim()
  skillPanelInput.value = ''
  skillPanelWaitingConfirm.value = false

  // 如果有文件，添加文件信息到消息
  if (hasFiles) {
    const fileNames = panelUploadedFiles.value.map(f => f.name).join(', ')
    const fileInfo = `[上传文件: ${fileNames}]`
    userMessage = userMessage ? `${userMessage}\n${fileInfo}` : fileInfo

    // 收集服务器路径，保存到状态中供执行时使用
    panelUploadedFiles.value.forEach(f => {
      if (f.serverPath && !panelCollectedFilePaths.value.includes(f.serverPath)) {
        panelCollectedFilePaths.value.push(f.serverPath)
      }
    })

    // 清理文件预览
    panelUploadedFiles.value.forEach(f => {
      if (f.url) URL.revokeObjectURL(f.url)
    })
    panelUploadedFiles.value = []
  }

  // 添加用户消息
  skillPanelMessages.value.push({
    id: Date.now(),
    role: 'user',
    content: userMessage,
    timestamp: new Date()
  })

  scrollSkillPanelToBottom()
  skillPanelProcessing.value = true

  // AI 回复占位
  const aiMsgId = Date.now() + 1
  skillPanelMessages.value.push({
    id: aiMsgId,
    role: 'assistant',
    content: '',
    timestamp: new Date()
  })

  try {
    // 收集所有用户输入作为上下文
    const userInputs = skillPanelMessages.value
      .filter(m => m.role === 'user')
      .map(m => m.content)

    const history = skillPanelMessages.value
      .filter(m => m.role !== 'system' && m.id !== aiMsgId)
      .map(m => ({ role: m.role as 'user' | 'assistant', content: m.content }))

    let fullContent = ''
    for await (const chunk of agentApi.chatStream({
      message: `用户需求：${userMessage}\n\n请根据用户的需求，总结一下你理解的要点，然后询问用户是否确认执行。如果用户之前有提过其他要求，也要整合进来。`,
      history: history
    })) {
      fullContent += chunk
      const msgIndex = skillPanelMessages.value.findIndex(m => m.id === aiMsgId)
      if (msgIndex !== -1) {
        skillPanelMessages.value[msgIndex] = {
          ...skillPanelMessages.value[msgIndex],
          content: fullContent
        }
      }
      scrollSkillPanelToBottom()
    }

    // 生成总结并等待确认
    skillPanelSummary.value = userInputs.join('；')
    skillPanelWaitingConfirm.value = true

  } catch (error: any) {
    // 如果 API 调用失败，使用模拟回复
    const userInputs = skillPanelMessages.value
      .filter(m => m.role === 'user')
      .map(m => m.content)

    const summary = generateAISummary(userInputs, executingSkill.value?.name || '')

    const msgIndex = skillPanelMessages.value.findIndex(m => m.id === aiMsgId)
    if (msgIndex !== -1) {
      skillPanelMessages.value[msgIndex] = {
        ...skillPanelMessages.value[msgIndex],
        content: summary,
        isConfirmation: true
      }
    }

    skillPanelSummary.value = userInputs.join('；')
    skillPanelWaitingConfirm.value = true
    scrollSkillPanelToBottom()
  } finally {
    skillPanelProcessing.value = false
  }
}

// 生成 AI 总结（模拟）
const generateAISummary = (userInputs: string[], skillName: string): string => {
  const requirements = userInputs.join('、')
  return `好的，我来确认一下你的需求：\n\n**任务**：${skillName}\n**要求**：${requirements}\n\n请确认以上信息是否正确？\n• 确认无误 → 点击「确认执行」\n• 需要修改 → 继续输入补充`
}

// 确认执行
const confirmExecuteSkill = () => {
  skillPanelWaitingConfirm.value = false

  // 添加确认消息
  skillPanelMessages.value.push({
    id: Date.now(),
    role: 'user',
    content: '✓ 确认执行',
    timestamp: new Date()
  })

  scrollSkillPanelToBottom()

  // 执行 skill
  executeSkillPanel()
}

// 继续补充
const continueAddDetails = () => {
  skillPanelWaitingConfirm.value = false
  skillPanelMessages.value.push({
    id: Date.now(),
    role: 'assistant',
    content: '好的，请继续补充你的要求：',
    timestamp: new Date()
  })
  scrollSkillPanelToBottom()
  nextTick(() => {
    skillPanelInputRef.value?.focus()
  })
}

// 取消执行
const cancelSkillExecution = () => {
  closeSkillExecution(true)  // 传入 true 表示取消，需要恢复状态
}

// 执行技能 - 传递用户输入内容
const executeSkillPanel = async () => {
  skillPanelProcessing.value = true

  // 添加执行中消息
  skillPanelMessages.value.push({
    id: Date.now(),
    role: 'assistant',
    content: '正在调用后端执行技能，请稍候...',
    timestamp: new Date(),
    isExecuting: true
  })
  scrollSkillPanelToBottom()

  // 收集用户在面板中的所有输入（排除"确认执行"）
  const userInputs = skillPanelMessages.value
    .filter(m => m.role === 'user' && !m.content.includes('确认执行'))
    .map(m => m.content)

  // 合并原始上下文和用户补充的需求
  const combinedContext = [
    executionContext.value,  // 原始上下文（如 "帮我生成一个卖花的商城网页"）
    ...userInputs            // 用户在交互面板中补充的需求
  ].filter(Boolean).join('\n\n补充需求：\n')

  // 返回结果，包含用户的输入内容
  const finalParams = {
    userRequirements: userInputs,           // 用户的所有要求
    summary: skillPanelSummary.value,       // AI 总结
    context: combinedContext,               // 合并后的完整上下文
    skillName: executingSkill.value?.name,
    filePaths: panelCollectedFilePaths.value.length > 0 ? [...panelCollectedFilePaths.value] : undefined,  // 上传的文件路径
    conversationHistory: skillPanelMessages.value
      .filter(m => m.role !== 'system')
      .map(m => ({ role: m.role, content: m.content }))
  }

  console.log('[executeSkillPanel] Final params:', finalParams)

  // 直接调用 handleSkillComplete，它会：
  // 1. 关闭面板
  // 2. 调用后端 API 执行技能
  // 3. 更新步骤状态
  await handleSkillComplete({
    success: true,
    output: userInputs.join('\n'),
    params: finalParams
  })

  // handleSkillComplete 完成后，面板已关闭，这里不需要额外操作
}

// 直接执行 - 跳过面板AI对话，直接带输入和文件执行
const quickExecuteSkillPanel = async () => {
  console.log('========== [quickExecuteSkillPanel] 开始直接执行 ==========')

  // 设置干净执行模式，只对当前流水线（messageId）生效
  const stepInfo = executingStepInfo.value
  if (stepInfo) {
    cleanExecutionMessageId.value = stepInfo.messageId
  }

  // 先复制一份文件列表，防止被清空
  const currentFiles = [...panelUploadedFiles.value]
  console.log('[quickExecuteSkillPanel] 当前面板文件数量:', currentFiles.length)
  console.log('[quickExecuteSkillPanel] 当前面板文件详情:', JSON.stringify(currentFiles.map(f => ({
    name: f.name,
    serverPath: f.serverPath,
    uploading: f.uploading
  })), null, 2))
  console.log('[quickExecuteSkillPanel] 输入框内容:', skillPanelInput.value)

  // 检查是否有文件正在上传
  const uploadingFiles = currentFiles.filter(f => f.uploading)
  if (uploadingFiles.length > 0) {
    console.log('[quickExecuteSkillPanel] 还有文件在上传中:', uploadingFiles.length)
    alert('请等待文件上传完成')
    return
  }

  // 收集输入框内容
  const inputText = skillPanelInput.value.trim()
  skillPanelInput.value = ''

  // 收集上传的文件路径（从复制的列表中）
  const filePaths: string[] = []
  currentFiles.forEach(f => {
    if (f.serverPath) {
      filePaths.push(f.serverPath)
      console.log('[quickExecuteSkillPanel] ✓ 收集文件:', f.name, '->', f.serverPath)
    } else {
      console.log('[quickExecuteSkillPanel] ✗ 文件没有serverPath:', f.name)
    }
  })

  // 清理文件预览
  panelUploadedFiles.value.forEach(f => {
    if (f.url) URL.revokeObjectURL(f.url)
  })
  panelUploadedFiles.value = []

  console.log('[quickExecuteSkillPanel] 收集到的文件路径:', JSON.stringify(filePaths))

  // 直接执行时：保留原始上下文 + 面板新输入，但明确告知 AI 忽略之前的运行结果
  // executionContext.value = 原始用户请求（如"帮我生成一个卖花的商城网页"）
  const cleanExecutionHint = '【重要提示】这是一次全新的独立执行，请完全忽略之前任何执行产生的数据、JSON、文件或结果。只使用本次提供的输入文件和参数。'

  const combinedContext = [
    cleanExecutionHint,      // 添加清洁执行提示
    executionContext.value,  // 保留原始上下文
    inputText                // 面板新输入
  ].filter(Boolean).join('\n\n')

  // 构建参数
  const finalParams = {
    userRequirements: inputText ? [inputText] : [],
    context: combinedContext,
    skillName: executingSkill.value?.name,
    filePaths: filePaths.length > 0 ? filePaths : undefined,
    quickExecute: true,  // 标记为直接执行
    cleanExecution: true // 标记为干净执行，忽略之前的结果
  }

  console.log('[quickExecuteSkillPanel] finalParams:', JSON.stringify(finalParams, null, 2))
  console.log('[quickExecuteSkillPanel] finalParams.filePaths:', JSON.stringify(finalParams.filePaths))

  // 保存到全局变量供调试
  ;(window as any).__quickExecuteParams = finalParams
  ;(window as any).__quickExecuteFilePaths = filePaths

  console.log('[quickExecuteSkillPanel] 即将调用 handleSkillComplete...')

  // 直接调用 handleSkillComplete，跳过面板AI对话
  await handleSkillComplete({
    success: true,
    output: inputText || '直接执行',
    params: finalParams
  })

  console.log('[quickExecuteSkillPanel] handleSkillComplete 调用完成')
}

// 滚动面板到底部
const scrollSkillPanelToBottom = () => {
  nextTick(() => {
    if (skillPanelChatRef.value) {
      skillPanelChatRef.value.scrollTop = skillPanelChatRef.value.scrollHeight
    }
  })
}

// 渲染面板 Markdown
const renderPanelMarkdown = (text: string): string => {
  return text
    .replace(/```(\w*)\n?([\s\S]*?)```/g, '<pre class="code-block"><code>$2</code></pre>')
    .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
    .replace(/\n/g, '<br>')
    .replace(/• /g, '<span class="bullet">•</span> ')
}

// 技能执行完成 - 更新步骤状态并继续执行
const handleSkillComplete = async (result: { success: boolean; output?: string; params?: Record<string, any> }) => {
  console.log('========== [handleSkillComplete] 开始 ==========')
  console.log('[handleSkillComplete] 接收到的 result:', JSON.stringify(result, null, 2))
  console.log('[handleSkillComplete] result.params:', result.params)
  console.log('[handleSkillComplete] result.params?.filePaths:', result.params?.filePaths)

  const stepInfo = executingStepInfo.value
  console.log('[handleSkillComplete] stepInfo:', stepInfo)

  if (!stepInfo) {
    console.error('[handleSkillComplete] ⚠️ stepInfo 为空！无法执行技能。请确保从主对话框的技能步骤点击进入面板。')
  }

  closeSkillExecution()

  if (result.success && stepInfo) {
    const { messageId, stepId } = stepInfo
    const msg = messages.value.find(m => m.id === messageId)
    if (msg?.skillPlan) {
      const step = msg.skillPlan.find(s => s.id === stepId)
      if (step) {
        // 保存用户输入的参数
        step.userInput = result.params ? JSON.stringify(result.params) : '{}'
        step.status = 'running'
        step.output = '正在执行...'
        scrollToBottom()

        // 调用后端 API 实际执行 skill
        try {
          if (step.skillId) {
            // 文件路径：只使用面板上传的文件，不再使用主对话框的旧文件
            const panelFilePaths = result.params?.filePaths || []
            // 直接执行时不使用上下文文件（之前生成的文档不算上下文）
            const isQuickExecute = result.params?.quickExecute === true
            const finalFilePaths = panelFilePaths  // 只用面板文件

            // 优先使用交互面板中的 context，其次使用用户查询，最后使用技能描述
            const contextValue = result.params?.context || lastUserQuery.value || step.description || ''

            // 构建参数，不包含旧的文件
            const params: Record<string, any> = {
              context: contextValue,
              skillDescription: step.description,
              userRequirements: result.params?.userRequirements
            }

            // 只有面板有文件时才添加文件参数
            if (finalFilePaths.length > 0) {
              params.file_path = finalFilePaths[0]
              params.file_paths = finalFilePaths
            }

            console.log(`[handleSkillComplete] Executing skill "${step.skillName}"`)
            console.log(`[handleSkillComplete] isQuickExecute:`, isQuickExecute)
            console.log(`[handleSkillComplete] Context value:`, contextValue)
            console.log(`[handleSkillComplete] Panel files (only these will be used):`, JSON.stringify(panelFilePaths))
            console.log(`[handleSkillComplete] Final files:`, JSON.stringify(finalFilePaths))
            console.log(`[handleSkillComplete] params.file_path:`, params.file_path)
            console.log(`[handleSkillComplete] params.file_paths:`, JSON.stringify(params.file_paths))
            console.log(`[handleSkillComplete] 发送到API的完整 params:`, JSON.stringify(params, null, 2))
            console.log('========== [handleSkillComplete] 调用API ==========')

            // 调试：保存到全局变量
            ;(window as any).__lastSkillParams = params
            ;(window as any).__lastPanelFiles = panelFilePaths

            const response = await agentApi.execute({
              skill_id: step.skillId,
              params
            })

            console.log(`[handleSkillComplete] Response:`, response)

            if (response.success) {
              step.status = 'completed'
              step.output = response.output || `✓ ${step.description} 完成`
              if (response.output_file) {
                step.outputFile = {
                  type: response.output_file.type as OutputFile['type'],
                  name: response.output_file.name,
                  url: response.output_file.url,
                  size: response.output_file.size
                }
              } else {
                step.outputFile = generateOutputFile(step.skillName, step.description, step.output)
              }
            } else {
              step.status = 'error'
              // 构建完整的错误信息
              const errorParts: string[] = []
              if (response.error) {
                errorParts.push(`错误: ${response.error}`)
              }
              if (response.output) {
                errorParts.push(`输出: ${response.output}`)
              }
              step.output = '结果可能不符合预期'
              step.errorDetails = {
                error: response.error,
                output: response.output
              }
            }
          } else {
            // 没有 skillId，模拟执行
            step.status = 'completed'
            step.output = `⚠️ 技能 "${step.skillName}" 未关联，已模拟执行`
            step.outputFile = generateOutputFile(step.skillName, step.description, step.output)
          }
        } catch (error: any) {
          console.error(`[handleSkillComplete] Error:`, error)
          step.status = 'error'
          step.output = `结果可能不符合预期`
          step.errorDetails = {
            error: error.message || '未知错误'
          }
        }

        scrollToBottom()
      }

      // 如果是"直接执行"（cleanExecution），清除后续节点的 userInput
      // 这样后续节点不会使用旧的上下文数据
      if (result.params?.cleanExecution && msg.pipelineEdges && step.nodeId) {
        const clearSuccessorUserInput = (nodeId: string) => {
          // 找到所有从当前节点出发的边
          msg.pipelineEdges!.forEach(e => {
            if (e.from === nodeId) {
              const successorStep = msg.skillPlan!.find(s => s.nodeId === e.to)
              if (successorStep && successorStep.status === 'pending') {
                // 清除后续节点的 userInput，让它使用新的上下文
                successorStep.userInput = undefined
                console.log(`[handleSkillComplete] 清除后续节点 "${successorStep.skillName}" 的 userInput`)
                // 递归清除更后面的节点
                clearSuccessorUserInput(e.to)
              }
            }
          })
        }
        clearSuccessorUserInput(step.nodeId)
      }

      // 继续执行后续步骤
      setTimeout(() => {
        const hasPending = msg.skillPlan!.some(s => s.status === 'pending')
        if (hasPending && pendingExecution.value) {
          isProcessing.value = true
          executeSkillsParallel(messageId)
        } else {
          pendingExecution.value = null
        }
      }, 300)
    }
  }
}

// 当前任务的流程（用于顶部流程条显示）
const currentPipeline = computed(() => {
  // 找到最后一个有 skillPlan 的 agent 消息
  for (let i = messages.value.length - 1; i >= 0; i--) {
    const msg = messages.value[i]
    if (msg && msg.type === 'agent' && msg.skillPlan && msg.skillPlan.length > 0) {
      return msg.skillPlan
    }
  }
  return []
})

// 当前流程的边关系
const currentPipelineEdges = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i--) {
    const msg = messages.value[i]
    if (msg && msg.type === 'agent' && msg.pipelineEdges) {
      return msg.pipelineEdges
    }
  }
  return []
})

// 按拓扑层级分组的流程（用于分叉显示）
const pipelineLevels = computed(() => {
  const steps = currentPipeline.value
  const edges = currentPipelineEdges.value

  if (steps.length === 0) return []

  // 如果没有edges或者没有nodeId，直接按顺序返回每个节点为一层
  if (edges.length === 0 || !steps[0]?.nodeId) {
    return steps.map(s => [s])
  }

  // 构建邻接表和入度表
  const adj: Record<string, string[]> = {}
  const inDegree: Record<string, number> = {}

  steps.forEach(s => {
    if (s.nodeId) {
      adj[s.nodeId] = []
      inDegree[s.nodeId] = 0
    }
  })

  edges.forEach(e => {
    const fromAdj = adj[e.from]
    if (fromAdj) {
      // 源节点是技能节点，添加邻接关系并增加目标节点入度
      fromAdj.push(e.to)
      const toDegree = inDegree[e.to]
      if (toDegree !== undefined) {
        inDegree[e.to] = toDegree + 1
      }
    }
    // 数据节点不在 adj 中，其出边不增加目标节点入度
  })

  // 拓扑排序分层
  const levels: SkillStep[][] = []
  const nodeToStep = new Map(steps.filter(s => s.nodeId).map(s => [s.nodeId, s]))
  const remaining = new Set(steps.filter(s => s.nodeId).map(s => s.nodeId))

  while (remaining.size > 0) {
    // 找到当前入度为0的节点
    const currentLevel: SkillStep[] = []
    const toRemove: string[] = []

    remaining.forEach(nodeId => {
      if (inDegree[nodeId] === 0) {
        const step = nodeToStep.get(nodeId)
        if (step) currentLevel.push(step)
        toRemove.push(nodeId)
      }
    })

    if (currentLevel.length === 0) {
      // 防止死循环（有环或其他问题）
      remaining.forEach(nodeId => {
        const step = nodeToStep.get(nodeId)
        if (step) currentLevel.push(step)
      })
      remaining.clear()
    } else {
      // 移除这些节点，更新入度
      toRemove.forEach(nodeId => {
        remaining.delete(nodeId)
        const children = adj[nodeId]
        if (children) {
          children.forEach(child => {
            if (inDegree[child] !== undefined) {
              inDegree[child]--
            }
          })
        }
      })
    }

    if (currentLevel.length > 0) {
      levels.push(currentLevel)
    }
  }

  return levels
})

// 删除流程中的节点
const deleteStepFromPipeline = (stepId: number) => {
  // 找到最后一个有 skillPlan 的 agent 消息
  for (let i = messages.value.length - 1; i >= 0; i--) {
    const msg = messages.value[i]
    if (msg && msg.type === 'agent' && msg.skillPlan && msg.skillPlan.length > 0) {
      const idx = msg.skillPlan.findIndex(s => s.id === stepId)
      if (idx !== -1) {
        // 获取被删除节点的信息
        const deletedStep = msg.skillPlan[idx]
        const deletedNodeId = deletedStep?.nodeId
        const wasRunning = deletedStep?.status === 'running'
        const messageId = msg.id

        // 记录被删除的 skill（用于跳过其上下文）
        if (deletedStep?.skillId) {
          deletedSkillIds.value.add(deletedStep.skillId)
        }

        // 创建新的 skillPlan（删除指定节点）
        const newSkillPlan = msg.skillPlan.filter((_, index) => index !== idx)

        // 如果删除后 skillPlan 为空，删除整个对话回合
        if (newSkillPlan.length === 0) {
          const groupId = `pg-${msg.id}`
          // 找到对应的用户消息
          let userMsgId: number | null = null
          for (let j = i - 1; j >= 0; j--) {
            const prevMsg = messages.value[j]
            if (prevMsg && prevMsg.type === 'user') {
              userMsgId = prevMsg.id
              break
            }
          }
          // 删除用户消息和 agent 消息
          const messageIdsToDelete = new Set<number>([msg.id])
          if (userMsgId !== null) {
            messageIdsToDelete.add(userMsgId)
          }
          messages.value = messages.value.filter(m => !messageIdsToDelete.has(m.id))
          // 清理流程栏状态
          collapsedGroups.value.delete(groupId)
          savedGroups.value.delete(groupId)
          if (activeGroupId.value === groupId) {
            activeGroupId.value = null
          }
          // 重置暂停状态
          if (isPaused.value && pausedMessageId.value === messageId) {
            isPaused.value = false
            pausedMessageId.value = null
            pendingExecution.value = null
            isProcessing.value = false
          }
          return
        }

        // 重新编号
        newSkillPlan.forEach((step, index) => {
          step.id = index + 1
        })

        // 同步删除 pipelineEdges 中与该节点相关的边
        let newEdges = msg.pipelineEdges || []
        if (deletedNodeId) {
          newEdges = newEdges.filter(
            e => e.from !== deletedNodeId && e.to !== deletedNodeId
          )
        }

        // 替换整个消息对象以触发 Vue 响应式更新
        messages.value[i] = {
          ...msg,
          skillPlan: newSkillPlan,
          pipelineEdges: newEdges
        }

        // 如果删除的是正在运行（已暂停）的 skill，继续执行下一个
        if (wasRunning && isPaused.value && pausedMessageId.value === messageId) {
          // 更新 pendingExecution 的 skills
          if (pendingExecution.value) {
            pendingExecution.value.skills = newSkillPlan
          }
          // 自动恢复执行
          nextTick(() => {
            resumeExecution()
          })
        }
      }
      break
    }
  }
}

// 最后一个有效的用户查询（跳过无意义的内容）
const lastUserQuery = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i--) {
    const msg = messages.value[i]
    if (msg && msg.type === 'user') {
      const content = msg.content?.trim() || ''
      // 跳过只有附件描述或运行工作流的消息
      if (content.startsWith('[上传了') || content.startsWith('运行工作流：')) {
        continue
      }
      if (content) {
        return content
      }
    }
  }
  return ''
})

// 获取最近用户消息中的文件路径（用于传递给技能执行）
const getContextFilePaths = (): string[] => {
  for (let i = messages.value.length - 1; i >= 0; i--) {
    const msg = messages.value[i]
    if (msg && msg.type === 'user' && msg.attachments?.length) {
      return msg.attachments
        .filter(a => a.serverPath)
        .map(a => a.serverPath!)
    }
  }
  return []
}

// 提取流程组名称（从用户消息）
const extractGroupName = (content: string): string => {
  // 截取前20个字符作为名称
  const name = content.trim().replace(/^运行工作流：/, '')
  return name.length > 20 ? name.slice(0, 20) + '...' : name
}

// 计算流程组的状态
const computeGroupStatus = (skillPlan: SkillStep[]): PipelineGroup['status'] => {
  if (skillPlan.length === 0) return 'pending'

  const hasRunning = skillPlan.some(s => s.status === 'running')
  const hasError = skillPlan.some(s => s.status === 'error')
  const hasMissing = skillPlan.some(s => s.status === 'missing')
  const allCompleted = skillPlan.every(s => s.status === 'completed')

  if (hasRunning) return 'running'
  if (hasError) return 'error'
  if (hasMissing) return 'paused'
  if (allCompleted) return 'completed'
  return 'pending'
}

// 判断流程是否正在运行（用于禁用点击）
const isPipelineRunning = (messageId: number): boolean => {
  const msg = messages.value.find(m => m.id === messageId)
  if (!msg?.skillPlan) return false
  return msg.skillPlan.some(s => s.status === 'running') || isProcessing.value
}

// 点击 skill 打开侧边栏配置（流程完成后可重新配置并执行）
const openSkillForRerun = (messageId: number, stepId: number) => {
  const msg = messages.value.find(m => m.id === messageId)
  if (!msg?.skillPlan) return

  // 如果流程正在运行（非暂停状态），不允许点击
  if (isPipelineRunning(messageId) && !isPaused.value) return

  // 找到步骤索引
  const startIndex = msg.skillPlan.findIndex(s => s.id === stepId)
  if (startIndex === -1) return

  const step = msg.skillPlan[startIndex]

  // 保存当前结果到历史记录（如果有结果的话）
  for (let i = startIndex; i < msg.skillPlan.length; i++) {
    const s = msg.skillPlan[i]
    if (s.status === 'completed' || s.status === 'error') {
      if (s.output || s.outputFile) {
        if (!s.outputHistory) s.outputHistory = []
        s.outputHistory.push({
          id: Date.now() + i,
          timestamp: new Date(),
          output: s.output,
          outputFile: s.outputFile ? { ...s.outputFile } : undefined,
          userInput: s.userInput
        })
      }
    }
    // 重置状态：当前配置的设为 configuring，后续的设为 pending
    if (i === startIndex) {
      s.status = 'configuring'
    } else {
      s.status = 'pending'
    }
    s.output = undefined
    s.outputFile = undefined
  }

  // 保存待执行状态
  pendingExecution.value = {
    messageId,
    skills: msg.skillPlan
  }

  // 打开侧边栏配置
  openSkillExecution(
    { name: step.skillName, icon: step.skillIcon, description: step.description },
    lastUserQuery.value,
    messageId,
    step.id
  )
}

// 暂停时打开配置侧边栏（可编辑后继续执行）
const openPausedSkillConfig = (messageId: number, step: SkillStep) => {
  // 将当前 running 的 skill 设为 configuring
  step.status = 'configuring'

  // 保存待执行状态
  const msg = messages.value.find(m => m.id === messageId)
  if (msg?.skillPlan) {
    pendingExecution.value = {
      messageId,
      skills: msg.skillPlan
    }
  }

  // 设置 executingStepInfo 并标记来自暂停状态
  executingStepInfo.value = { messageId, stepId: step.id, fromPaused: true }

  // 打开侧边栏配置（不用调用 openSkillExecution，直接设置状态）
  executingSkill.value = { name: step.skillName, icon: step.skillIcon, description: step.description }
  executionContext.value = lastUserQuery.value
  skillPanelMessages.value = []
  skillPanelInput.value = ''
  skillPanelProcessing.value = false
  skillPanelComplete.value = false
  skillPanelParams.value = {}
  showSkillExecution.value = true

  // 生成初始问候消息
  nextTick(() => {
    const greeting = `正在编辑 **${step.skillName}** 的配置\n\n当前任务：${step.description}\n\n请输入新的要求或修改，确认后将继续执行。`
    skillPanelMessages.value.push({
      id: 1,
      role: 'assistant',
      content: greeting,
      timestamp: new Date()
    })
    skillPanelInputRef.value?.focus()
  })
}

// 删除单个历史结果
const deleteHistoryItem = (messageId: number, stepId: number, historyId: number) => {
  const msg = messages.value.find(m => m.id === messageId)
  if (!msg?.skillPlan) return

  const step = msg.skillPlan.find(s => s.id === stepId)
  if (!step?.outputHistory) return

  step.outputHistory = step.outputHistory.filter(h => h.id !== historyId)
}

// 按拓扑层级分组（用于单个流程组的渲染）
const getPipelineLevelsForGroup = (steps: SkillStep[], edges: PipelineEdge[]) => {
  if (steps.length === 0) return []

  // 如果没有edges或者没有nodeId，直接按顺序返回每个节点为一层
  if (edges.length === 0 || !steps[0]?.nodeId) {
    return steps.map(s => [s])
  }

  // 构建邻接表和入度表
  const adj: Record<string, string[]> = {}
  const inDegree: Record<string, number> = {}

  steps.forEach(s => {
    if (s.nodeId) {
      adj[s.nodeId] = []
      inDegree[s.nodeId] = 0
    }
  })

  edges.forEach(e => {
    const fromAdj = adj[e.from]
    if (fromAdj) {
      // 源节点是技能节点，添加邻接关系并增加目标节点入度
      fromAdj.push(e.to)
      const toDegree = inDegree[e.to]
      if (toDegree !== undefined) {
        inDegree[e.to] = toDegree + 1
      }
    }
    // 数据节点不在 adj 中，其出边不增加目标节点入度
  })

  // 拓扑排序分层
  const levels: SkillStep[][] = []
  const nodeToStep = new Map(steps.filter(s => s.nodeId).map(s => [s.nodeId, s]))
  const remaining = new Set(steps.filter(s => s.nodeId).map(s => s.nodeId))

  while (remaining.size > 0) {
    // 找到当前入度为0的节点
    const currentLevel: SkillStep[] = []
    const toRemove: string[] = []

    remaining.forEach(nodeId => {
      if (inDegree[nodeId] === 0) {
        const step = nodeToStep.get(nodeId)
        if (step) currentLevel.push(step)
        toRemove.push(nodeId)
      }
    })

    if (currentLevel.length === 0) {
      // 防止死循环（有环或其他问题）
      remaining.forEach(nodeId => {
        const step = nodeToStep.get(nodeId)
        if (step) currentLevel.push(step)
      })
      remaining.clear()
    } else {
      // 移除这些节点，更新入度
      toRemove.forEach(nodeId => {
        remaining.delete(nodeId)
        const children = adj[nodeId]
        if (children) {
          children.forEach(child => {
            if (inDegree[child] !== undefined) {
              inDegree[child]--
            }
          })
        }
      })
    }

    if (currentLevel.length > 0) {
      levels.push(currentLevel)
    }
  }

  return levels
}

// 计算多个流程组
const pipelineGroups = computed<PipelineGroup[]>(() => {
  const groups: PipelineGroup[] = []

  // 遍历消息，找到所有带 skillPlan 的 agent 响应
  for (let i = 0; i < messages.value.length; i++) {
    const msg = messages.value[i]
    if (msg && msg.type === 'agent' && msg.skillPlan && msg.skillPlan.length > 0) {
      // 找到对应的用户消息（前一条用户消息）
      let userMsg: Message | null = null
      for (let j = i - 1; j >= 0; j--) {
        const prevMsg = messages.value[j]
        if (prevMsg && prevMsg.type === 'user') {
          userMsg = prevMsg
          break
        }
      }

      if (userMsg) {
        const groupId = `pg-${msg.id}`
        const skillPlan = msg.skillPlan
        const edges = msg.pipelineEdges || []
        const completed = skillPlan.filter(s => s.status === 'completed').length

        // 默认展开：如果没有明确折叠过，就是展开状态
        // 使用 collapsedGroups 逻辑反转：不在折叠集合中 = 展开
        const isExpanded = !collapsedGroups.value.has(groupId)

        groups.push({
          id: groupId,
          name: extractGroupName(userMsg.content),
          description: userMsg.content,
          createdAt: msg.timestamp,
          messageRange: {
            startMessageId: userMsg.id,
            endMessageId: msg.id,
            messageIds: [userMsg.id, msg.id]
          },
          skillPlan,
          pipelineEdges: edges,
          status: computeGroupStatus(skillPlan),
          progress: { completed, total: skillPlan.length },
          isExpanded,
          isSaved: savedGroups.value.has(groupId)
        })
      }
    }
  }

  return groups
})

// 切换流程组展开/折叠，并滚动到对应消息
const toggleGroupExpanded = (groupId: string) => {
  // 设置为当前选中
  activeGroupId.value = groupId

  if (collapsedGroups.value.has(groupId)) {
    collapsedGroups.value.delete(groupId)  // 展开
  } else {
    collapsedGroups.value.add(groupId)  // 折叠
  }

  // 滚动到对应的消息
  const group = pipelineGroups.value.find(g => g.id === groupId)
  if (group) {
    scrollToMessage(group.messageRange.startMessageId)
  }
}

// 折叠/展开全部
const collapseAllGroups = () => {
  const allExpanded = pipelineGroups.value.every(g => !collapsedGroups.value.has(g.id))
  if (allExpanded) {
    // 全部折叠
    pipelineGroups.value.forEach(g => collapsedGroups.value.add(g.id))
  } else {
    // 全部展开
    collapsedGroups.value.clear()
  }
}

// 删除流程组
const confirmDeleteGroup = (groupId: string) => {
  pendingDeleteGroupId.value = groupId
  showDeleteConfirm.value = true
}

const deletePipelineGroup = () => {
  if (!pendingDeleteGroupId.value) return

  const group = pipelineGroups.value.find(g => g.id === pendingDeleteGroupId.value)
  if (group) {
    // 删除关联的消息
    const messageIdsToDelete = new Set(group.messageRange.messageIds)
    messages.value = messages.value.filter(m => !messageIdsToDelete.has(m.id))

    // 清理状态集合
    collapsedGroups.value.delete(group.id)
    savedGroups.value.delete(group.id)

    // 如果删除的是当前选中的，清除选中状态
    if (activeGroupId.value === group.id) {
      activeGroupId.value = null
    }
  }

  showDeleteConfirm.value = false
  pendingDeleteGroupId.value = null
}

const cancelDeleteGroup = () => {
  showDeleteConfirm.value = false
  pendingDeleteGroupId.value = null
}

// 保存单个流程组为工作流
const openSaveGroupDialog = (group: PipelineGroup) => {
  pendingSaveGroup.value = group
  pendingSaveSkillPlan.value = group.skillPlan
  pendingSaveEdges.value = group.pipelineEdges
  saveWorkflowName.value = group.name
  saveWorkflowDesc.value = `基于对话生成：${group.description}`
  showSaveDialog.value = true
}

// 删除流程组中的节点
const deleteStepFromGroup = (groupId: string, stepId: number) => {
  // 找到对应的消息
  const group = pipelineGroups.value.find(g => g.id === groupId)
  if (!group) return

  const msgIndex = messages.value.findIndex(m => m.id === group.messageRange.endMessageId)
  if (msgIndex === -1) return

  const msg = messages.value[msgIndex]
  if (msg?.skillPlan) {
    const idx = msg.skillPlan.findIndex(s => s.id === stepId)
    if (idx !== -1) {
      // 获取被删除节点的信息
      const deletedStep = msg.skillPlan[idx]
      const deletedNodeId = deletedStep?.nodeId
      const wasRunning = deletedStep?.status === 'running'
      const messageId = msg.id

      // 记录被删除的 skill（用于跳过其上下文）
      if (deletedStep?.skillId) {
        deletedSkillIds.value.add(deletedStep.skillId)
      }

      // 创建新的 skillPlan（删除指定节点）
      const newSkillPlan = msg.skillPlan.filter((_, i) => i !== idx)

      // 如果删除后 skillPlan 为空，删除整个对话回合
      if (newSkillPlan.length === 0) {
        // 删除关联的消息
        const messageIdsToDelete = new Set(group.messageRange.messageIds)
        messages.value = messages.value.filter(m => !messageIdsToDelete.has(m.id))
        // 清理流程栏状态
        collapsedGroups.value.delete(groupId)
        savedGroups.value.delete(groupId)
        if (activeGroupId.value === groupId) {
          activeGroupId.value = null
        }
        // 重置暂停状态
        if (isPaused.value && pausedMessageId.value === messageId) {
          isPaused.value = false
          pausedMessageId.value = null
          pendingExecution.value = null
          isProcessing.value = false
        }
        return
      }

      // 重新编号
      newSkillPlan.forEach((step, index) => {
        step.id = index + 1
      })

      // 同步删除 pipelineEdges 中与该节点相关的边
      let newEdges = msg.pipelineEdges || []
      if (deletedNodeId) {
        newEdges = newEdges.filter(
          e => e.from !== deletedNodeId && e.to !== deletedNodeId
        )
      }

      // 替换整个消息对象以触发 Vue 响应式更新
      messages.value[msgIndex] = {
        ...msg,
        skillPlan: newSkillPlan,
        pipelineEdges: newEdges
      }

      // 如果删除的是正在运行（已暂停）的 skill，继续执行下一个
      if (wasRunning && isPaused.value && pausedMessageId.value === messageId) {
        // 更新 pendingExecution 的 skills
        if (pendingExecution.value) {
          pendingExecution.value.skills = newSkillPlan
        }
        // 自动恢复执行
        nextTick(() => {
          resumeExecution()
        })
      }
    }
  }
}

// 所有可能用到的技能定义
const allPossibleSkills = [
  { name: 'data-visualizer', icon: '📊', desc: '数据可视化分析' },
  { name: 'code-reviewer', icon: '🔍', desc: '代码审查优化' },
  { name: 'doc-parser', icon: '📑', desc: '文档解析提取' },
  { name: 'api-integrator', icon: '🔗', desc: 'API 集成调用' },
  { name: 'smart-translator', icon: '🌍', desc: '智能翻译' },
  { name: 'sql-helper', icon: '🗃️', desc: 'SQL 查询优化' },
  { name: 'test-generator', icon: '🧪', desc: '测试用例生成' },
  { name: 'image-analyzer', icon: '🖼️', desc: '图像分析识别' },
]

// 检查技能是否已安装
const isSkillInstalled = (skillName: string): boolean => {
  return props.skills.some(s => s.name === skillName)
}

// 根据名称获取技能对象
const getSkillByName = (skillName: string) => {
  return props.skills.find(s => s.name === skillName)
}

// 可用技能数量
const installedSkillCount = computed(() => props.skills.length)

const scrollToBottom = () => {
  nextTick(() => {
    if (chatContainer.value) {
      chatContainer.value.scrollTop = chatContainer.value.scrollHeight
    }
  })
}

// 滚动到指定消息
const scrollToMessage = (messageId: number) => {
  nextTick(() => {
    const messageEl = document.querySelector(`[data-message-id="${messageId}"]`)
    if (messageEl && chatContainer.value) {
      messageEl.scrollIntoView({ behavior: 'smooth', block: 'center' })
      // 添加高亮效果
      messageEl.classList.add('message-highlight')
      setTimeout(() => {
        messageEl.classList.remove('message-highlight')
      }, 1500)
    }
  })
}

// 模拟 AI 规划技能
const planSkills = (userInput: string): { steps: SkillStep[], edges: PipelineEdge[] } => {
  // 根据用户输入模拟选择技能
  const keywords = userInput.toLowerCase()
  const plan: SkillStep[] = []
  let stepId = 1

  const addSkillToPlan = (name: string, icon: string, desc: string) => {
    const installed = isSkillInstalled(name)
    const nodeId = `node-${stepId}`
    plan.push({
      id: stepId++,
      nodeId,
      skillName: name,
      skillIcon: icon,
      description: desc,
      status: installed ? 'pending' : 'missing'
    })
  }

  if (keywords.includes('数据') || keywords.includes('分析') || keywords.includes('报表')) {
    addSkillToPlan('data-visualizer', '📊', '分析数据并生成可视化图表')
  }
  if (keywords.includes('代码') || keywords.includes('审查') || keywords.includes('优化')) {
    addSkillToPlan('code-reviewer', '🔍', '审查代码质量并提供优化建议')
  }
  if (keywords.includes('文档') || keywords.includes('解析') || keywords.includes('提取')) {
    addSkillToPlan('doc-parser', '📑', '解析文档内容并提取关键信息')
  }
  if (keywords.includes('api') || keywords.includes('接口') || keywords.includes('集成')) {
    addSkillToPlan('api-integrator', '🔗', '调用相关 API 获取数据')
  }
  if (keywords.includes('翻译') || keywords.includes('英文') || keywords.includes('中文')) {
    addSkillToPlan('smart-translator', '🌍', '翻译内容到目标语言')
  }
  if (keywords.includes('sql') || keywords.includes('数据库') || keywords.includes('查询')) {
    addSkillToPlan('sql-helper', '🗃️', '构建并优化 SQL 查询语句')
  }
  if (keywords.includes('测试') || keywords.includes('用例')) {
    addSkillToPlan('test-generator', '🧪', '生成测试用例')
  }
  if (keywords.includes('图片') || keywords.includes('图像') || keywords.includes('识别')) {
    addSkillToPlan('image-analyzer', '🖼️', '分析图像内容')
  }

  // 如果没有匹配，随机选择 2-3 个技能演示
  if (plan.length === 0) {
    const shuffled = [...allPossibleSkills].sort(() => Math.random() - 0.5).slice(0, 3)
    shuffled.forEach((skill) => {
      addSkillToPlan(skill.name, skill.icon, `执行 ${skill.desc}`)
    })
  }

  // 生成顺序边（AI规划的任务默认是顺序执行的）
  const edges: PipelineEdge[] = []
  for (let i = 0; i < plan.length - 1; i++) {
    const currentNode = plan[i]
    const nextNode = plan[i + 1]
    if (currentNode?.nodeId && nextNode?.nodeId) {
      edges.push({
        from: currentNode.nodeId,
        to: nextNode.nodeId
      })
    }
  }

  return { steps: plan, edges }
}

// 模拟执行技能
const executeSkills = async (messageId: number, skills: SkillStep[], startIndex: number = 0) => {
  for (let i = startIndex; i < skills.length; i++) {
    // 检查是否暂停
    if (isPaused.value) {
      pausedMessageId.value = messageId
      pendingExecution.value = { messageId, skills }
      isProcessing.value = false
      return
    }

    const msg = messages.value.find(m => m.id === messageId)
    if (!msg?.skillPlan) continue

    const step = msg.skillPlan[i]
    if (!step) continue

    // 检查技能是否缺失
    if (step.status === 'missing' || !isSkillInstalled(step.skillName)) {
      step.status = 'missing'
      msg.waitingForSkill = step.skillName
      // 保存待执行状态
      pendingExecution.value = {
        messageId,
        skills: skills
      }
      isProcessing.value = false
      scrollToBottom()
      return // 暂停执行，等待用户添加技能
    }

    // 设置当前步骤为 running
    step.status = 'running'
    scrollToBottom()

    // 调用真实 API 执行技能
    try {
      if (step.skillId) {
        // 构建参数：包含用户输入、原始上下文和文件路径
        let filePaths = getContextFilePaths()

        // 【关键】检查消息中的数据节点，获取文件路径
        const dataNodesMap = msg?.dataNodes || {}
        const edges = msg?.pipelineEdges || []
        if (step.nodeId && Object.keys(dataNodesMap).length > 0) {
          console.log(`[Skill Seq] Checking data nodes for "${step.skillName}"`)
          edges.forEach((e: any) => {
            if (e.to === step.nodeId) {
              const dataNode = dataNodesMap[e.from]
              if (dataNode?.dataNote?.file_url) {
                const fileUrl = dataNode.dataNote.file_url
                let extractedPath = ''
                const filesMatch = fileUrl.match(/\/(files\/[^?]+)/) || fileUrl.match(/\/(uploads\/[^?]+)/)
                if (filesMatch) {
                  extractedPath = filesMatch[1]
                } else if (fileUrl.startsWith('/')) {
                  extractedPath = fileUrl.substring(1)
                } else {
                  extractedPath = fileUrl
                }
                if (extractedPath) {
                  filePaths = [extractedPath, ...filePaths]
                  console.log(`[Skill Seq] ✓ Found data node file for "${step.skillName}": ${extractedPath}`)
                }
              }
            }
          })
        }

        // 安全解析 userInput
        let baseParams: Record<string, any> = {}

        // 如果是干净执行模式，忽略旧的 userInput，使用全新的上下文
        const isCleanMode = cleanExecutionMessageId.value === messageId

        if (!isCleanMode && step.userInput) {
          try {
            baseParams = JSON.parse(step.userInput)
          } catch (e) {
            console.warn(`[Skill Seq] Failed to parse userInput for "${step.skillName}":`, e)
          }
        }

        // 获取上下文：干净模式只用用户查询，否则优先 baseParams.context
        let contextValue = isCleanMode
          ? (lastUserQuery.value || step.description || '')
          : (baseParams.context || lastUserQuery.value || step.description || '')

        // 如果是干净执行模式，在 context 前面添加提示
        if (isCleanMode) {
          const cleanHint = '【重要提示】这是一次全新的独立执行，请完全忽略之前任何执行产生的数据、JSON、文件或结果。只使用本次提供的输入文件和参数。\n\n'
          contextValue = cleanHint + contextValue
        }

        const params = {
          ...baseParams,
          // 添加上下文（userInput 的 context 优先）
          context: contextValue,
          skillDescription: step.description,
          ...(filePaths.length > 0 ? {
            file_path: filePaths[0],
            file_paths: filePaths
          } : {})
        }

        console.log(`[Skill Seq] Executing "${step.skillName}" with context:`, contextValue)

        const response = await agentApi.execute({
          skill_id: step.skillId,
          params
        })

        // 调试日志
        console.log(`[Skill Seq] Response for "${step.skillName}":`, response)

        if (response.success) {
          step.status = 'completed'
          step.output = response.output || `✓ ${step.description} 完成`
          // 使用 API 返回的真实输出文件
          if (response.output_file) {
            console.log(`[Skill Seq] Using backend output_file`)
            step.outputFile = {
              type: response.output_file.type as OutputFile['type'],
              name: response.output_file.name,
              url: response.output_file.url,
              size: response.output_file.size
            }
          } else {
            console.log(`[Skill Seq] No output_file, generating local md`)
            step.outputFile = generateOutputFile(step.skillName, step.description, step.output)
          }
        } else {
          step.status = 'error'
          // 构建完整的错误信息
          const errorParts: string[] = []
          if (response.error) {
            errorParts.push(`错误: ${response.error}`)
          }
          if (response.output) {
            errorParts.push(`输出: ${response.output}`)
          }
          step.output = '结果可能不符合预期'
          step.errorDetails = {
            error: response.error,
            output: response.output
          }
        }
      } else {
        // 没有 skillId，说明技能未找到
        console.warn(`[Skill Seq] No skillId for "${step.skillName}", simulating...`)
        await new Promise(resolve => setTimeout(resolve, 1200 + Math.random() * 800))
        step.status = 'completed'
        step.output = `⚠️ 技能 "${step.skillName}" 未找到 skillId，已模拟执行`
        step.outputFile = generateOutputFile(step.skillName, step.description, step.output)
      }
    } catch (error: any) {
      console.error('Skill execution failed:', error)
      // API 失败
      step.status = 'error'
      step.output = `结果可能不符合预期`
      step.errorDetails = {
        error: error.message || '未知错误'
      }
    }
  }

  // 全部完成
  const msg = messages.value.find(m => m.id === messageId)
  if (msg) {
    msg.waitingForSkill = undefined
  }
  pendingExecution.value = null
  isProcessing.value = false
  // 重置干净执行模式（只重置当前 messageId 的）
  if (cleanExecutionMessageId.value === messageId) {
    cleanExecutionMessageId.value = null
  }
}

// 按拓扑层级并行执行技能
const executeSkillsParallel = async (messageId: number) => {
  const msg = messages.value.find(m => m.id === messageId)
  console.log('========================================')
  console.log('[executeSkillsParallel] Starting execution')
  console.log('[executeSkillsParallel] messageId:', messageId)
  console.log('[executeSkillsParallel] msg.dataNodes:', msg?.dataNodes)
  console.log('[executeSkillsParallel] msg.pipelineEdges:', msg?.pipelineEdges)
  console.log('[executeSkillsParallel] msg.skillPlan:', msg?.skillPlan?.map(s => ({ id: s.id, nodeId: s.nodeId, skillName: s.skillName })))
  console.log('========================================')

  if (!msg?.skillPlan || !msg.pipelineEdges) {
    // 没有边信息，回退到顺序执行
    console.log('[executeSkillsParallel] No edges, falling back to sequential execution')
    if (msg?.skillPlan) {
      await executeSkills(messageId, msg.skillPlan)
    }
    return
  }

  const steps = msg.skillPlan
  const edges = msg.pipelineEdges

  // 如果没有nodeId，回退到顺序执行
  if (!steps[0]?.nodeId) {
    console.log('[executeSkillsParallel] No nodeId, falling back to sequential execution')
    await executeSkills(messageId, steps)
    return
  }

  // 构建邻接表和入度表
  const adj: Record<string, string[]> = {}
  const inDegree: Record<string, number> = {}
  const nodeToStep = new Map(steps.filter(s => s.nodeId).map(s => [s.nodeId!, s]))

  steps.forEach(s => {
    if (s.nodeId) {
      adj[s.nodeId] = []
      inDegree[s.nodeId] = 0
    }
  })

  edges.forEach(e => {
    const fromAdj = adj[e.from]
    if (fromAdj) {
      // 源节点是技能节点，添加邻接关系并增加目标节点入度
      fromAdj.push(e.to)
      const toDegree = inDegree[e.to]
      if (toDegree !== undefined) {
        inDegree[e.to] = toDegree + 1
      }
    }
    // 如果源节点是数据节点（不在 adj 中），不增加目标节点入度
    // 这样数据节点后的第一个技能节点入度为 0，可以立即执行
  })

  const remaining = new Set(steps.filter(s => s.nodeId).map(s => s.nodeId!))

  while (remaining.size > 0) {
    // 检查是否暂停
    if (isPaused.value) {
      pausedMessageId.value = messageId
      pendingExecution.value = { messageId, skills: steps }
      isProcessing.value = false
      return
    }

    // 找到当前入度为0的节点（可以并行执行）
    const currentBatch: SkillStep[] = []
    const toProcess: string[] = []

    remaining.forEach(nodeId => {
      if (inDegree[nodeId] === 0) {
        const step = nodeToStep.get(nodeId)
        if (step) {
          // 只有 pending 状态的才需要执行，已完成的跳过但仍要更新入度
          if (step.status === 'pending') {
            currentBatch.push(step)
          }
          // 所有入度为0的都要加入 toProcess，以便更新后续节点的入度
          toProcess.push(nodeId)
        }
      }
    })

    if (toProcess.length === 0) {
      // 没有任何可处理的节点，防止死循环
      break
    }

    // 如果有需要执行的步骤
    if (currentBatch.length > 0) {
      // 检查是否有缺失的技能
      const missingStep = currentBatch.find(step => step.status === 'missing' || !isSkillInstalled(step.skillName))
      if (missingStep) {
        missingStep.status = 'missing'
        msg.waitingForSkill = missingStep.skillName
        pendingExecution.value = { messageId, skills: steps }
        isProcessing.value = false
        scrollToBottom()
        return
      }

      // 并行执行当前批次
      currentBatch.forEach(step => {
        step.status = 'running'
      })
      scrollToBottom()

      // 并行执行技能（调用真实 API）
      await Promise.all(currentBatch.map(async (step) => {
      try {
        if (step.skillId) {
          // 构建参数：包含用户输入、原始上下文和文件路径
          const filePaths = getContextFilePaths()

          // 【关键】获取前驱节点的输出文件作为当前节点的输入
          const predecessorFiles: string[] = []
          const dataNodesMap = msg.dataNodes || {}
          console.log(`[Skill Parallel] ========== Processing "${step.skillName}" ==========`)
          console.log(`[Skill Parallel] step.nodeId:`, step.nodeId)
          console.log(`[Skill Parallel] dataNodesMap keys:`, Object.keys(dataNodesMap))
          console.log(`[Skill Parallel] dataNodesMap full:`, JSON.stringify(dataNodesMap, null, 2))
          console.log(`[Skill Parallel] edges:`, edges)
          if (step.nodeId) {
            // 找到所有指向当前节点的边
            edges.forEach(e => {
              if (e.to === step.nodeId) {
                console.log(`[Skill Parallel] Found incoming edge: ${e.from} -> ${e.to}`)
                // 首先检查前驱节点是否是数据节点
                const dataNode = dataNodesMap[e.from]
                console.log(`[Skill Parallel] Looking for dataNode with key "${e.from}":`, dataNode ? 'FOUND' : 'NOT FOUND')
                if (dataNode) {
                  console.log(`[Skill Parallel] dataNode content:`, JSON.stringify(dataNode, null, 2))
                }
                if (dataNode?.dataNote?.file_url) {
                  const fileUrl = dataNode.dataNote.file_url
                  console.log(`[Skill Parallel] Raw file_url:`, fileUrl)
                  // 提取服务器路径 - 支持多种格式
                  let extractedPath = ''
                  const filesMatch = fileUrl.match(/\/(files\/[^?]+)/) || fileUrl.match(/\/(uploads\/[^?]+)/)
                  if (filesMatch) {
                    extractedPath = filesMatch[1]
                  } else if (fileUrl.startsWith('http')) {
                    // 完整 URL，提取路径部分
                    try {
                      const url = new URL(fileUrl)
                      extractedPath = url.pathname.substring(1) // 去掉开头的 /
                    } catch (e) {
                      extractedPath = fileUrl
                    }
                  } else if (fileUrl.startsWith('/')) {
                    extractedPath = fileUrl.substring(1)
                  } else {
                    extractedPath = fileUrl
                  }
                  if (extractedPath) {
                    predecessorFiles.push(extractedPath)
                    console.log(`[Skill Parallel] ✓ Extracted file path for "${step.skillName}": ${extractedPath}`)
                  }
                  return // 已找到数据节点，跳过后续检查
                } else {
                  console.log(`[Skill Parallel] ✗ No file_url in dataNode for ${e.from}`)
                }

                // 找到前驱节点的 step（技能节点）
                const predStep = nodeToStep.get(e.from)
                if (predStep?.outputFile?.url) {
                  // 从 URL 提取服务器路径
                  const url = predStep.outputFile.url
                  // URL 格式: /outputs/xxx.json 或 http://xxx/outputs/xxx.json
                  const outputMatch = url.match(/\/outputs\/([^/]+)$/)
                  if (outputMatch) {
                    const serverPath = `outputs/${outputMatch[1]}`
                    predecessorFiles.push(serverPath)
                    console.log(`[Skill Parallel] Found predecessor output for "${step.skillName}": ${serverPath}`)
                  } else {
                    // 其他格式的 URL
                    const filesMatch = url.match(/\/(files\/[^?]+)/) || url.match(/\/(uploads\/[^?]+)/)
                    if (filesMatch) {
                      predecessorFiles.push(filesMatch[1])
                      console.log(`[Skill Parallel] Found predecessor file for "${step.skillName}": ${filesMatch[1]}`)
                    } else if (url.startsWith('/')) {
                      predecessorFiles.push(url.substring(1))
                      console.log(`[Skill Parallel] Found predecessor path for "${step.skillName}": ${url.substring(1)}`)
                    }
                  }
                }
              }
            })
          }

          // 安全解析 userInput
          let baseParams: Record<string, any> = {}

          // 如果是干净执行模式，忽略旧的 userInput，使用全新的上下文
          const isCleanMode = cleanExecutionMessageId.value === messageId

          if (!isCleanMode && step.userInput) {
            try {
              baseParams = JSON.parse(step.userInput)
            } catch (e) {
              console.warn(`[Skill Parallel] Failed to parse userInput for "${step.skillName}":`, e)
            }
          }

          // 获取上下文：干净模式只用用户查询，否则优先 baseParams.context
          let contextValue = isCleanMode
            ? (lastUserQuery.value || step.description || '')
            : (baseParams.context || lastUserQuery.value || step.description || '')

          // 如果是干净执行模式，在 context 前面添加提示
          if (isCleanMode) {
            const cleanHint = '【重要提示】这是一次全新的独立执行，请完全忽略之前任何执行产生的数据、JSON、文件或结果。只使用本次提供的输入文件和参数。\n\n'
            contextValue = cleanHint + contextValue
          }
          console.log(`[Skill Parallel] isCleanMode:`, isCleanMode)
          console.log(`[Skill Parallel] Context for "${step.skillName}":`, contextValue)

          // 合并文件路径：
          // - 如果有前驱输出，优先使用前驱输出（不需要用户上传的原始文件）
          // - 如果没有前驱输出，才使用用户上传的文件
          const allFilePaths = predecessorFiles.length > 0 ? predecessorFiles : filePaths
          console.log(`[Skill Parallel] All file paths for "${step.skillName}":`, allFilePaths)
          console.log(`[Skill Parallel] Using predecessor files only:`, predecessorFiles.length > 0)

          const params = {
            ...baseParams,
            // 添加用户原始查询作为上下文
            context: contextValue,
            skillDescription: step.description,
            // 传递文件路径（前驱输出 + 用户上传）
            ...(allFilePaths.length > 0 ? {
              file_path: allFilePaths[0],  // 主文件（优先前驱输出）
              file_paths: allFilePaths,    // 所有文件
              files: allFilePaths          // 兼容不同参数名
            } : {})
          }

          console.log(`[Skill Parallel] Executing "${step.skillName}" with params:`, params)

          const response = await agentApi.execute({
            skill_id: step.skillId,
            params
          })

          // 调试日志 - 打印完整响应结构
          console.log(`[Skill Parallel] Response for "${step.skillName}":`, JSON.stringify(response, null, 2))
          console.log(`[Skill Parallel] Response keys:`, Object.keys(response))
          console.log(`[Skill Parallel] output_file present:`, 'output_file' in response)
          console.log(`[Skill Parallel] output_file value:`, response.output_file)

          if (response.success) {
            step.status = 'completed'
            step.output = response.output || `✓ ${step.description} 完成`
            if (response.output_file) {
              console.log(`[Skill Parallel] Using backend output_file:`, response.output_file)
              const outputFile = {
                type: response.output_file.type as OutputFile['type'],
                name: response.output_file.name,
                url: response.output_file.url,
                size: response.output_file.size
              }
              step.outputFile = outputFile
              console.log(`[Skill Parallel] step.outputFile after assignment:`, step.outputFile)
            } else {
              // 后端没有返回文件时，基于输出内容创建本地文件
              console.log(`[Skill Parallel] No output_file in response, generating local md`)
              step.outputFile = generateOutputFile(step.skillName, step.description, step.output)
            }
            console.log(`[Skill Parallel] Step ${step.id} final state: status=${step.status}, hasOutputFile=${!!step.outputFile}`)
          } else {
            step.status = 'error'
            // 构建完整的错误信息
            const errorParts: string[] = []
            if (response.error) {
              errorParts.push(`错误: ${response.error}`)
            }
            if (response.output) {
              errorParts.push(`输出: ${response.output}`)
            }
            step.output = '结果可能不符合预期'
            step.errorDetails = {
              error: response.error,
              output: response.output
            }
          }
        } else {
          // 没有 skillId，说明技能未找到
          console.warn(`[Skill Execution] No skillId for "${step.skillName}", simulating...`)
          await new Promise(resolve => setTimeout(resolve, 1200 + Math.random() * 800))
          step.status = 'completed'
          step.output = `⚠️ 技能 "${step.skillName}" 未找到 skillId，已模拟执行`
          step.outputFile = generateOutputFile(step.skillName, step.description, step.output)
        }
      } catch (error: any) {
        // API 调用失败
        console.error(`[Skill Execution] API error for "${step.skillName}":`, error)
        step.status = 'error'
        step.output = `结果可能不符合预期`
        step.errorDetails = {
          error: error.message || '未知错误'
        }
      }
      }))
      scrollToBottom()
    }

    // 移除已处理的节点，更新入度（无论是否执行了技能都要更新）
    toProcess.forEach(nodeId => {
      remaining.delete(nodeId)
      const children = adj[nodeId]
      if (children) {
        children.forEach(child => {
          if (inDegree[child] !== undefined) {
            inDegree[child]--
          }
        })
      }
    })
  }

  // 全部完成
  if (msg) {
    msg.waitingForSkill = undefined
  }
  pendingExecution.value = null
  isProcessing.value = false
  // 重置干净执行模式（只重置当前 messageId 的）
  if (cleanExecutionMessageId.value === messageId) {
    cleanExecutionMessageId.value = null
  }
}

// 跳转到 Skills 页面添加技能
const gotoAddSkill = (skillName: string, mode: 'create' | 'upload') => {
  emit('gotoSkills', skillName, mode)
}

// 技能添加完成后显示确认对话框
const onSkillAdded = (skillName: string) => {
  addedSkillName.value = skillName
  showContinueDialog.value = true

  // 更新技能状态
  if (pendingExecution.value) {
    const msg = messages.value.find(m => m.id === pendingExecution.value!.messageId)
    if (msg?.skillPlan) {
      msg.skillPlan.forEach(step => {
        if (step.status === 'missing' && isSkillInstalled(step.skillName)) {
          step.status = 'pending'
        }
      })
      msg.waitingForSkill = undefined
    }
  }
  scrollToBottom()
}

// 用户确认继续执行
const confirmContinue = () => {
  showContinueDialog.value = false
  if (!pendingExecution.value) return

  const { messageId } = pendingExecution.value
  const msg = messages.value.find(m => m.id === messageId)
  if (!msg?.skillPlan) return

  // 检查是否还有 pending 的步骤
  const hasPending = msg.skillPlan.some(s => s.status === 'pending')
  if (hasPending) {
    isProcessing.value = true
    executeSkillsParallel(messageId)
  } else {
    pendingExecution.value = null
  }
}

// 用户取消继续执行
const cancelContinue = () => {
  showContinueDialog.value = false
  pendingExecution.value = null
}

// 暂停执行
const pauseExecution = (messageId: number) => {
  isPaused.value = true
  pausedMessageId.value = messageId
  // 将当前 running 的步骤标记为 paused（保持 running 状态但显示暂停图标）
  const msg = messages.value.find(m => m.id === messageId)
  if (msg?.skillPlan) {
    msg.skillPlan.forEach(step => {
      if (step.status === 'running') {
        // 保持 running 状态，但 isPaused 会影响 UI 显示
      }
    })
  }
}

// 继续执行
const resumeExecution = () => {
  isPaused.value = false
  const messageId = pausedMessageId.value
  pausedMessageId.value = null

  if (messageId && pendingExecution.value) {
    isProcessing.value = true
    executeSkillsParallel(messageId)
  }
}

// 切换暂停/继续状态
const togglePauseExecution = (messageId: number) => {
  if (isPaused.value) {
    resumeExecution()
  } else {
    pauseExecution(messageId)
  }
}

// 打开保存流程对话框
const openSaveDialog = (skillPlan: SkillStep[], userQuery: string) => {
  pendingSaveSkillPlan.value = skillPlan
  pendingSaveEdges.value = currentPipelineEdges.value
  saveWorkflowName.value = userQuery.length > 20 ? userQuery.slice(0, 20) + '...' : userQuery
  saveWorkflowDesc.value = `基于对话生成：${userQuery}`
  showSaveDialog.value = true
}

// 确认保存流程
const confirmSaveWorkflow = () => {
  if (!pendingSaveSkillPlan.value) return

  // 将 skillPlan 转换为 workflow 格式
  const nodes = pendingSaveSkillPlan.value.map((step, index) => ({
    id: step.nodeId || `node-${index + 1}`,
    type: 'skill' as const,
    name: step.skillName,
    icon: step.skillIcon,
    description: step.description,
    position: { x: 50 + index * 200, y: 100 }
  }))

  // 使用保存的edges，如果没有则创建顺序边
  let edges: { id: string; from: string; to: string }[]
  if (pendingSaveEdges.value && pendingSaveEdges.value.length > 0) {
    edges = pendingSaveEdges.value.map((e, index) => ({
      id: `edge-${index + 1}`,
      from: e.from,
      to: e.to
    }))
  } else {
    const planSteps = pendingSaveSkillPlan.value
    edges = planSteps.slice(0, -1).map((step, index) => {
      const nextStep = planSteps[index + 1]
      return {
        id: `edge-${index + 1}`,
        from: step.nodeId || `node-${index + 1}`,
        to: nextStep?.nodeId || `node-${index + 2}`
      }
    })
  }

  emit('saveWorkflow', {
    name: saveWorkflowName.value || '新建流程',
    description: saveWorkflowDesc.value,
    nodes,
    edges
  })

  // 标记流程组为已保存
  if (pendingSaveGroup.value) {
    savedGroups.value.add(pendingSaveGroup.value.id)
  }

  // 关闭对话框
  showSaveDialog.value = false
  pendingSaveSkillPlan.value = null
  pendingSaveEdges.value = null
  pendingSaveGroup.value = null
}

// 取消保存
const cancelSaveWorkflow = () => {
  showSaveDialog.value = false
  pendingSaveSkillPlan.value = null
  pendingSaveEdges.value = null
  pendingSaveGroup.value = null
}

// 检查节点名是否匹配某个数据笔记（用于兼容没有正确保存 type 的旧数据）
const isDataNodeByName = (nodeName: string): boolean => {
  if (!nodeName) return false
  // 精确匹配
  if (dataNotesForSlash.value.find(n => n.name === nodeName)) return true
  // 去掉扩展名匹配
  const nameWithoutExt = nodeName.replace(/\.[^.]+$/, '')
  if (dataNotesForSlash.value.find(n => n.name === nameWithoutExt || n.name.replace(/\.[^.]+$/, '') === nameWithoutExt)) return true
  return false
}

// 展开工作流节点（递归处理子流程）
const expandWorkflowNodes = (nodes: any[], edges: any[] = []): { steps: SkillStep[], edges: PipelineEdge[], dataNodes: Map<string, any> } => {
  const steps: SkillStep[] = []
  const resultEdges: PipelineEdge[] = []
  let stepId = 1

  // 记录数据节点，供后续技能获取输入文件
  const dataNodes = new Map<string, any>()

  const processNode = (node: any) => {
    console.log(`[expandWorkflowNodes] Processing node:`, {
      id: node.id,
      name: node.name,
      type: node.type,
      hasDataNote: !!node.dataNote,
      dataNote_file_url: node.dataNote?.file_url
    })

    if (node.type === 'workflow' && node.workflowData) {
      // 子流程：递归展开其所有节点
      const subResult = expandWorkflowNodes(node.workflowData.nodes, node.workflowData.edges || [])
      subResult.steps.forEach(step => {
        steps.push({
          ...step,
          id: stepId++,
          description: `[${node.name}] ${step.description}`
        })
      })
      resultEdges.push(...subResult.edges)
      // 合并子流程的数据节点
      subResult.dataNodes.forEach((v, k) => dataNodes.set(k, v))
    } else if (node.type === 'data' || node.dataNote || isDataNodeByName(node.name)) {
      // 数据节点：不作为执行步骤，只记录数据信息
      // 兼容：检查 type === 'data' 或者有 dataNote 字段，或者名字匹配某个数据笔记
      // 数据节点的文件会在执行时传递给连接的技能
      let dataNote = node.dataNote
      console.log(`[expandWorkflowNodes] Data node "${node.name}" (id=${node.id}, type=${node.type}):`, {
        hasDataNote: !!dataNote,
        dataNote_file_url: dataNote?.file_url,
        node_dataNote: node.dataNote,
        matchedByName: !node.dataNote && !node.type && isDataNodeByName(node.name)
      })

      // 兼容性处理：如果 dataNote 不完整（没有 file_url），尝试从 dataNotesForSlash 查找
      if (!dataNote?.file_url) {
        console.log(`[expandWorkflowNodes] dataNote missing file_url, searching in dataNotesForSlash (count=${dataNotesForSlash.value.length})`)
        let found: DataNote | undefined

        // 1. 先尝试按 ID 匹配（最准确）
        if (dataNote?.id) {
          found = dataNotesForSlash.value.find(n => n.id === dataNote!.id)
          if (found) console.log(`[expandWorkflowNodes] Found by ID: ${found.id}`)
        }

        // 2. 尝试按名字精确匹配
        if (!found && node.name) {
          found = dataNotesForSlash.value.find(n => n.name === node.name)
          if (found) console.log(`[expandWorkflowNodes] Found by exact name: ${found.name}`)
        }

        // 3. 尝试去掉扩展名匹配
        if (!found && node.name) {
          const nameWithoutExt = node.name.replace(/\.[^.]+$/, '')
          found = dataNotesForSlash.value.find(n =>
            n.name === nameWithoutExt ||
            n.name.replace(/\.[^.]+$/, '') === nameWithoutExt
          )
          if (found) console.log(`[expandWorkflowNodes] Found by name without extension: ${found.name}`)
        }

        if (found) {
          console.log(`[expandWorkflowNodes] ✓ Found complete dataNote for "${node.name}": file_url=${found.file_url}`)
          dataNote = found
        } else {
          console.warn(`[expandWorkflowNodes] ✗ NOT FOUND: "${node.name}" (id=${dataNote?.id}) in dataNotesForSlash`)
          console.warn(`[expandWorkflowNodes] Available notes:`, dataNotesForSlash.value.map(n => ({ id: n.id, name: n.name, file_url: n.file_url?.substring(0, 50) })))
        }
      }

      dataNodes.set(node.id, {
        nodeId: node.id,
        name: node.name,
        icon: node.icon,
        dataNote: dataNote
      })
      console.log(`[expandWorkflowNodes] Added to dataNodes:`, node.id, dataNote?.file_url)
    } else {
      // 普通 Skill 节点
      const skill = getSkillByName(node.name)
      steps.push({
        id: stepId++,
        nodeId: node.id,
        skillId: skill?.id,  // 添加 skillId 用于后端执行
        skillName: node.name,
        skillIcon: node.icon,
        description: node.description,
        status: skill ? 'pending' as const : 'missing' as const
      })
    }
  }

  nodes.forEach(processNode)

  // 添加边
  edges.forEach((e: any) => {
    resultEdges.push({ from: e.from, to: e.to })
  })

  return { steps, edges: resultEdges, dataNodes }
}

// 运行工作流 - 从 SkillsView 传入直接执行
const runWorkflow = (workflow: any) => {
  pendingWorkflow.value = workflow
  workflowContext.value = workflow.userContext || ''
  confirmRunWorkflow()
}

// 确认执行工作流
const confirmRunWorkflow = () => {
  const workflow = pendingWorkflow.value
  if (!workflow) return

  const context = workflowContext.value.trim()

  // 获取传入的文件路径（如果有）
  const externalFilePaths: string[] = workflow.filePaths || []

  // 将工作流转换为技能执行计划（递归展开子流程）
  console.log('[confirmRunWorkflow] workflow.nodes:', workflow.nodes)
  // 详细打印每个节点的数据
  workflow.nodes.forEach((node: any, idx: number) => {
    console.log(`[confirmRunWorkflow] Node ${idx}:`, {
      id: node.id,
      type: node.type,
      name: node.name,
      hasDataNote: !!node.dataNote,
      dataNote: node.dataNote ? {
        file_url: node.dataNote.file_url,
        file_type: node.dataNote.file_type,
        name: node.dataNote.name
      } : null
    })
  })
  const { steps: skillPlan, edges: pipelineEdges, dataNodes } = expandWorkflowNodes(workflow.nodes, workflow.edges || [])

  // 把用户上下文传递给每个 skill，避免执行时再次弹出交互面板
  if (context) {
    skillPlan.forEach(step => {
      step.userInput = JSON.stringify({ context })
    })
  }

  // 检查是否有缺失的技能
  const missingSkills = skillPlan.filter(s => s.status === 'missing')
  if (missingSkills.length > 0) {
    const missingNames = missingSkills.map(s => s.skillName).join('、')
    // 添加用户消息
    const userMessage: Message = {
      id: Date.now(),
      type: 'user',
      content: context ? `${context}\n\n运行工作流：${workflow.name}` : `运行工作流：${workflow.name}`,
      timestamp: new Date()
    }
    messages.value.push(userMessage)

    // 添加错误提示
    setTimeout(() => {
      const agentMessage: Message = {
        id: Date.now(),
        type: 'agent',
        content: `无法执行工作流「${workflow.name}」，以下技能尚未安装：**${missingNames}**\n\n请先前往技能库安装这些技能后再试。`,
        timestamp: new Date()
      }
      messages.value.push(agentMessage)
      scrollToBottom()
    }, 300)

    pendingWorkflow.value = null
    workflowContext.value = ''
    return
  }

  // 构建附件信息（如果有外部传入的文件）
  const attachments: MessageAttachment[] = externalFilePaths.map((path, idx) => ({
    id: `wf-file-${idx}`,
    name: path.split('/').pop() || path.split('\\').pop() || `文件${idx + 1}`,
    type: 'file',
    size: 0,
    serverPath: path
  }))

  // 构建消息内容
  let messageContent = context ? `${context}\n\n运行工作流：${workflow.name}` : `运行工作流：${workflow.name}`
  if (attachments.length > 0) {
    messageContent = `${context || '处理这些文件'}\n\n[附带 ${attachments.length} 个文件]\n\n运行工作流：${workflow.name}`
  }

  // 添加用户消息（包含上下文和附件）
  const userMessage: Message = {
    id: Date.now(),
    type: 'user',
    content: messageContent,
    timestamp: new Date(),
    attachments: attachments.length > 0 ? attachments : undefined
  }
  messages.value.push(userMessage)
  scrollToBottom()

  // 添加 Agent 响应
  const dataNodesObj = Object.fromEntries(dataNodes)
  console.log('[confirmRunWorkflow] dataNodes to store:', dataNodesObj)
  console.log('[confirmRunWorkflow] pipelineEdges:', pipelineEdges)
  setTimeout(() => {
    const agentMessage: Message = {
      id: Date.now(),
      type: 'agent',
      content: context
        ? `好的，我来帮你处理：「${context}」\n\n将使用工作流「${workflow.name}」，包含 ${skillPlan.length} 个步骤：`
        : `好的，开始执行工作流「${workflow.name}」。这个流程包含 ${skillPlan.length} 个步骤：`,
      timestamp: new Date(),
      skillPlan,
      pipelineEdges,
      // 存储数据节点信息，供执行时获取输入文件
      dataNodes: dataNodesObj
    }
    messages.value.push(agentMessage)
    scrollToBottom()

    // 开始执行（按拓扑顺序，支持并行）
    setTimeout(() => {
      isProcessing.value = true
      isPaused.value = false
      executeSkillsParallel(agentMessage.id)
    }, 400)
  }, 600)

  pendingWorkflow.value = null
  workflowContext.value = ''
}

// 暴露方法给父组件
defineExpose({
  onSkillAdded,
  runWorkflow
})

const sendMessage = async () => {
  // 如果 "/" 弹窗打开，Enter 应该选择项目，不发送消息
  if (showSlashPopup.value) return
  if ((!inputText.value.trim() && uploadedFiles.value.length === 0 && pendingRefs.value.length === 0) || isProcessing.value) return

  // 处理待发送的数据引用（展开文件夹）
  const refAttachments: MessageAttachment[] = []
  for (const ref of pendingRefs.value) {
    if (ref.isFolder && ref.folderId) {
      // 文件夹：获取所有文件
      try {
        const files = await dataNotesApi.getFolderFiles(ref.folderId)
        for (const f of files) {
          refAttachments.push({
            id: `ref-${Date.now()}-${Math.random().toString(36).slice(2)}`,
            name: f.name,
            type: f.file_type,
            size: parseInt(f.file_size || '0') || 0,
            serverPath: f.file_url
          })
        }
      } catch (e) {
        console.error('Failed to get folder files:', e)
      }
    } else {
      // 普通文件
      refAttachments.push({
        id: ref.id,
        name: ref.name,
        type: ref.type,
        size: 0,
        serverPath: ref.file_url
      })
    }
  }
  pendingRefs.value = []

  // 收集附件信息（包含服务器路径）
  const attachments: MessageAttachment[] = [
    ...uploadedFiles.value
      .filter(f => !f.uploading && !f.uploadError)
      .map(f => ({
        id: f.id,
        name: f.name,
        type: f.type,
        size: f.size,
        url: f.url,
        serverPath: f.serverPath
      })),
    ...refAttachments
  ]

  // 构建消息内容（包含文件描述）
  let messageContent = inputText.value.trim()
  if (attachments.length > 0 && !messageContent) {
    messageContent = `[上传了 ${attachments.length} 个文件]`
  }

  const userMessage: Message = {
    id: Date.now(),
    type: 'user',
    content: messageContent,
    timestamp: new Date(),
    attachments: attachments.length > 0 ? attachments : undefined
  }
  messages.value.push(userMessage)

  // 构建发送给AI的内容（包含文件信息）
  let userInput = inputText.value.trim()
  if (attachments.length > 0) {
    const fileDesc = attachments.map(f => `[文件: ${f.name} (${f.type})]`).join(', ')
    userInput = userInput ? `${userInput}\n\n附件: ${fileDesc}` : `请处理这些文件: ${fileDesc}`
  }

  inputText.value = ''
  uploadedFiles.value = []  // 清空已上传文件
  isProcessing.value = true
  scrollToBottom()

  // 创建 AbortController
  abortController = new AbortController()

  // 构建聊天历史（排除刚添加的用户消息）
  const history: ChatMessage[] = messages.value
    .filter(m => m.type === 'user' || m.type === 'agent')
    .slice(0, -1) // 排除当前用户消息
    .slice(-10) // 保留最近10条消息
    .map(m => ({
      role: m.type === 'user' ? 'user' as const : 'assistant' as const,
      content: m.content
    }))

  // 获取可用技能ID
  const skillIds = props.skills.map(s => s.id)

  // 创建占位的 Agent 响应消息（用于流式更新）
  // 需要初始化 skillPlan 和 pipelineEdges 以确保 Vue 响应式
  const agentMessage: Message = {
    id: Date.now() + 1,
    type: 'agent',
    content: '',
    timestamp: new Date(),
    skillPlan: undefined,
    pipelineEdges: undefined
  }
  messages.value.push(agentMessage)
  scrollToBottom()

  try {
    // 调用后端 AI 聊天接口（流式）+ 打字机效果
    for await (const chunk of agentApi.chatStream(
      {
        message: userInput,
        history,
        skill_ids: skillIds
      },
      abortController.signal
    )) {
      if (abortController?.signal.aborted) break

      // 打字机效果：逐字符添加
      for (const char of chunk) {
        if (abortController?.signal.aborted) break
        agentMessage.content += char
        // 每隔几个字符滚动一次，减少性能开销
        if (agentMessage.content.length % 5 === 0) {
          scrollToBottom()
        }
      }
      // 每个 chunk 后小延迟，让动画更自然
      await new Promise(r => setTimeout(r, 10))
    }
    scrollToBottom()

    // 如果被中止，显示提示
    if (abortController?.signal.aborted) {
      if (!agentMessage.content) {
        agentMessage.content = '(已停止)'
      }
      isProcessing.value = false
      return
    }

    // 如果没有内容（可能是 API 错误），使用本地模拟
    if (!agentMessage.content.trim()) {
      throw new Error('No response from API')
    }

    // 解析 AI 回复中的技能规划
    const skillPlanMatch = agentMessage.content.match(/<!--SKILL_PLAN:(\[.*?\])-->/)
    if (skillPlanMatch) {
      try {
        const planData = JSON.parse(skillPlanMatch[1])
        // 移除内容中的 SKILL_PLAN 标记
        agentMessage.content = agentMessage.content.replace(/<!--SKILL_PLAN:\[.*?\]-->/, '').trim()

        // 转换为 skillPlan 格式
        console.log('[Skill Plan] Available skills:', props.skills.map(s => ({ id: s.id, name: s.name })))
        console.log('[Skill Plan] Plan data from AI:', planData)
        console.log('[Skill Plan] Skills count:', props.skills.length)

        const skillPlan: SkillStep[] = planData.map((item: any, index: number) => {
          // 检查技能是否存在 - 支持精确匹配和包含匹配
          const skillNameFromAI = item.skill.toLowerCase().trim()
          let existingSkill = props.skills.find(
            s => s.name.toLowerCase() === skillNameFromAI
          )
          // 如果精确匹配失败，尝试包含匹配
          if (!existingSkill) {
            existingSkill = props.skills.find(
              s => s.name.toLowerCase().includes(skillNameFromAI) ||
                   skillNameFromAI.includes(s.name.toLowerCase())
            )
          }
          console.log(`[Skill Plan] Matching "${item.skill}" (normalized: "${skillNameFromAI}") -> found:`, existingSkill ? { id: existingSkill.id, name: existingSkill.name } : 'NOT FOUND')

          return {
            id: index + 1,
            skillId: existingSkill?.id,  // 数据库中的技能ID
            nodeId: `node-${index + 1}`,
            skillName: item.skill,
            skillIcon: existingSkill?.icon || (item.exists ? '⚡' : '❓'),
            description: item.action,
            status: item.exists && existingSkill ? 'pending' : 'missing'
          }
        })

        if (skillPlan.length > 0) {
          // 生成简单的线性边
          const edges = skillPlan.slice(0, -1).map((_, i) => ({
            from: `node-${i + 1}`,
            to: `node-${i + 2}`
          }))

          // 强制触发 Vue 响应式更新：找到消息索引并替换
          const msgIndex = messages.value.findIndex(m => m.id === agentMessage.id)
          if (msgIndex !== -1) {
            messages.value[msgIndex] = {
              ...agentMessage,
              skillPlan,
              pipelineEdges: edges
            }
          }
          scrollToBottom()

          // 自动开始执行技能流程
          await new Promise(resolve => setTimeout(resolve, 500))
          executeSkillsParallel(agentMessage.id)
          return // 执行过程中会设置 isProcessing
        }
      } catch (e) {
        console.error('Failed to parse skill plan:', e)
      }
    }

    isProcessing.value = false
  } catch (error: any) {
    // 如果是用户主动取消，不处理
    if (error.name === 'AbortError') {
      if (!agentMessage.content) {
        agentMessage.content = '(已停止)'
      }
      isProcessing.value = false
      return
    }

    console.error('Chat API error:', error)

    // API 调用失败时，回退到本地技能规划模式
    const { steps: skillPlan, edges: pipelineEdges } = planSkills(userInput)

    if (skillPlan.length > 0) {
      // 强制触发 Vue 响应式更新
      const msgIndex = messages.value.findIndex(m => m.id === agentMessage.id)
      if (msgIndex !== -1) {
        messages.value[msgIndex] = {
          ...agentMessage,
          content: `好的，我来帮你处理这个任务。我规划了以下 ${skillPlan.length} 个技能的执行流程：`,
          skillPlan,
          pipelineEdges
        }
      }
      scrollToBottom()

      // 开始执行技能
      await new Promise(resolve => setTimeout(resolve, 400))
      executeSkillsParallel(messages.value[msgIndex]?.id || agentMessage.id)
    } else {
      agentMessage.content = '抱歉，我暂时无法连接到 AI 服务。请稍后再试。'
      isProcessing.value = false
    }
  } finally {
    abortController = null
  }
}

// Markdown 渲染函数
const renderMarkdown = (text: string): string => {
  if (!text) return ''

  let html = text
    // 转义 HTML 特殊字符（防止 XSS）
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    // 代码块 ```code```
    .replace(/```(\w*)\n?([\s\S]*?)```/g, '<pre class="code-block"><code>$2</code></pre>')
    // 行内代码 `code`
    .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
    // 粗体 **text**
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    // 斜体 *text*
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
    // 标题 ###
    .replace(/^### (.+)$/gm, '<h4>$1</h4>')
    .replace(/^## (.+)$/gm, '<h3>$1</h3>')
    .replace(/^# (.+)$/gm, '<h2>$1</h2>')
    // 无序列表 - item
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    // 有序列表 1. item
    .replace(/^\d+\. (.+)$/gm, '<li>$1</li>')
    // 链接 [text](url)
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>')
    // 换行
    .replace(/\n/g, '<br>')

  // 包装连续的 li 标签
  html = html.replace(/(<li>.*?<\/li>)(<br>)?/g, '$1')

  return html
}

const formatTime = (date: Date) => {
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

// 获取执行结果文本（友好展示）
const getExecutionResultText = (step: SkillStep): string => {
  if (!step.errorDetails?.error) {
    return '执行未能产生预期的结果'
  }

  const error = step.errorDetails.error

  // 语法错误
  if (error.includes('SyntaxError')) {
    return '技能代码在解析时遇到了问题，可能需要调整代码格式'
  }

  // 类型错误
  if (error.includes('TypeError')) {
    return '数据类型不匹配，输入的内容格式可能需要调整'
  }

  // 键错误
  if (error.includes('KeyError')) {
    return '找不到需要的数据字段，输入数据的结构可能不符合预期'
  }

  // 文件错误
  if (error.includes('FileNotFoundError') || error.includes('No such file')) {
    return '找不到需要处理的文件'
  }

  // 值错误
  if (error.includes('ValueError')) {
    return '输入的值格式不正确'
  }

  // 导入错误
  if (error.includes('ImportError') || error.includes('ModuleNotFoundError')) {
    return '技能需要的某些依赖还没有安装'
  }

  // 默认
  return '执行过程中遇到了一些问题'
}

// 获取执行思考/建议
const getExecutionThinking = (step: SkillStep): string => {
  if (!step.errorDetails?.error) {
    return '建议检查输入内容是否正确，或者尝试修改技能代码'
  }

  const error = step.errorDetails.error

  if (error.includes('SyntaxError')) {
    return '这通常是代码格式问题，比如引号、括号不匹配等。可以尝试修改技能代码。'
  }

  if (error.includes('TypeError')) {
    return '输入的数据类型和技能期望的不一致。比如期望数字却收到了文字，可以检查输入格式。'
  }

  if (error.includes('KeyError')) {
    return '输入的 JSON 数据缺少必要的字段。请确认输入数据包含技能需要的所有字段。'
  }

  if (error.includes('FileNotFoundError')) {
    return '需要先上传文件，或者检查文件路径是否正确。'
  }

  if (error.includes('ValueError')) {
    return '输入值的格式不对，比如日期格式、数字格式等。请检查并调整输入内容。'
  }

  if (error.includes('ImportError') || error.includes('ModuleNotFoundError')) {
    return '技能代码使用了未安装的库，需要在服务器上安装相应的依赖。'
  }

  return '可以尝试重新输入，或者修改技能代码来适应当前的输入。'
}

// 重试技能
const retrySkill = (step: SkillStep) => {
  // 重置状态，让用户可以重新输入
  step.status = 'pending'
  step.output = undefined
  step.errorDetails = undefined
  step.userInput = undefined
}

// 修改技能（跳转到技能编辑）
const modifySkill = (step: SkillStep) => {
  if (step.skillId) {
    emit('gotoSkills', step.skillName, 'create')
  }
}

// 获取文件类型图标和颜色
const getFileTypeInfo = (type: OutputFile['type']) => {
  const typeMap: Record<OutputFile['type'], { icon: string; color: string; label: string }> = {
    ppt: { icon: '📊', color: '#D24726', label: 'PPT 演示文稿' },
    word: { icon: '📄', color: '#2B579A', label: 'Word 文档' },
    markdown: { icon: '📝', color: '#083FA1', label: 'Markdown' },
    pdf: { icon: '📕', color: '#F40F02', label: 'PDF 文档' },
    png: { icon: '🖼️', color: '#4CAF50', label: 'PNG 图片' },
    jpg: { icon: '🖼️', color: '#FF9800', label: 'JPG 图片' },
    video: { icon: '🎬', color: '#9C27B0', label: '视频文件' },
    html: { icon: '🌐', color: '#E44D26', label: 'HTML 页面' },
    excel: { icon: '📊', color: '#217346', label: 'Excel 表格' },
    code: { icon: '💻', color: '#6366F1', label: '代码包' },
    file: { icon: '📎', color: '#8B5CF6', label: '输出文件' },
    other: { icon: '📎', color: '#607D8B', label: '文件' }
  }
  return typeMap[type] || typeMap.other
}

// 下载并打开输出文件
const openOutputFile = async (file: OutputFile) => {
  // 如果是 blob URL，直接下载
  if (file.url.startsWith('blob:')) {
    const link = document.createElement('a')
    link.href = file.url
    link.download = file.name
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    return
  }

  // 构建完整URL（后端根地址，不含 /api）
  const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'
  const baseUrl = apiBaseUrl.replace(/\/api$/, '')  // 移除 /api 后缀
  const fullUrl = file.url.startsWith('http') ? file.url : `${baseUrl}${file.url}`

  try {
    // 下载文件
    const response = await fetch(fullUrl)
    if (!response.ok) {
      throw new Error('下载失败')
    }

    const blob = await response.blob()
    const blobUrl = URL.createObjectURL(blob)

    // 创建下载链接
    const link = document.createElement('a')
    link.href = blobUrl
    link.download = file.name

    // 触发下载
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)

    // 同时在新窗口打开预览（对于可预览的文件类型）
    if (['html', 'pdf', 'png', 'jpg', 'markdown'].includes(file.type)) {
      window.open(blobUrl, '_blank')
    }

    // 延迟释放 URL
    setTimeout(() => URL.revokeObjectURL(blobUrl), 5000)
  } catch (error) {
    console.error('下载文件失败:', error)
    // 降级：直接在新窗口打开
    window.open(fullUrl, '_blank')
  }
}
</script>

<template>
  <div class="agent-chat">
    <!-- 聊天头部 -->
    <header class="chat-header">
      <div class="header-left">
        <div class="agent-avatar">
          <span class="avatar-icon">🤖</span>
          <span class="status-dot"></span>
        </div>
        <div class="agent-info">
          <h3>AI Agent</h3>
          <span class="agent-status">在线 · 随时为您服务</span>
        </div>
      </div>
      <div class="header-right">
        <button class="header-action-btn" @click="clearConversation" title="新建会话">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
            <line x1="12" y1="8" x2="12" y2="14"/>
            <line x1="9" y1="11" x2="15" y2="11"/>
          </svg>
          <span>新会话</span>
        </button>
        <div class="skill-count">
          <span class="count-number">{{ installedSkillCount }}</span>
          <span class="count-label">可用技能</span>
        </div>
      </div>
    </header>

    <!-- 主体区域：流程条 + 对话 -->
    <div class="chat-body">
      <!-- 垂直业务流程条 - 多流程管理 -->
      <div class="pipeline-sidebar">
        <div class="pipeline-sidebar-header">
          <svg class="header-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3"/>
            <path d="M12 2v4m0 12v4M2 12h4m12 0h4"/>
          </svg>
          <span class="sidebar-title">流程</span>
          <span v-if="pipelineGroups.length > 0" class="group-counter">({{ pipelineGroups.length }})</span>
          <button
            v-if="pipelineGroups.length > 1"
            class="collapse-all-btn"
            @click="collapseAllGroups"
            :title="pipelineGroups.every(g => !collapsedGroups.has(g.id)) ? '折叠全部' : '展开全部'"
          >
            <svg v-if="pipelineGroups.every(g => !collapsedGroups.has(g.id))" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="4 14 10 14 10 20"/>
              <polyline points="20 10 14 10 14 4"/>
              <line x1="14" y1="10" x2="21" y2="3"/>
              <line x1="3" y1="21" x2="10" y2="14"/>
            </svg>
            <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="15 3 21 3 21 9"/>
              <polyline points="9 21 3 21 3 15"/>
              <line x1="21" y1="3" x2="14" y2="10"/>
              <line x1="3" y1="21" x2="10" y2="14"/>
            </svg>
          </button>
        </div>
        <div class="pipeline-sidebar-content">
          <!-- 有流程组时显示列表 -->
          <div v-if="pipelineGroups.length > 0" class="pipeline-groups">
            <div
              v-for="group in pipelineGroups"
              :key="group.id"
              class="pipeline-group"
              :class="{
                'is-expanded': group.isExpanded,
                'is-active': activeGroupId === group.id
              }"
            >
              <!-- 流程组头部 -->
              <div
                class="group-header"
                :class="[`status-${group.status}`]"
                @click="toggleGroupExpanded(group.id)"
              >
                <div class="group-expand-icon">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline :points="group.isExpanded ? '6 9 12 15 18 9' : '9 6 15 12 9 18'"/>
                  </svg>
                </div>
                <div class="group-info">
                  <span class="group-name" :title="group.description">{{ group.name }}</span>
                  <span class="group-progress" :class="[`progress-${group.status}`]">
                    <template v-if="group.status === 'running'">
                      <span class="mini-spinner"></span>
                    </template>
                    <template v-else-if="group.status === 'completed'">✓</template>
                    <template v-else-if="group.status === 'paused'">⏸</template>
                    <template v-else-if="group.status === 'error'">✗</template>
                    <template v-else>●</template>
                    {{ group.progress.completed }}/{{ group.progress.total }}
                  </span>
                </div>
                <!-- 保存按钮 - 有流程规划时就显示（小星星样式） -->
                <Transition name="save-btn">
                  <button
                    v-if="group.skillPlan && group.skillPlan.length > 0"
                    class="group-save-star"
                    :class="{ 'is-saved': group.isSaved, 'is-pending': group.status !== 'completed' }"
                    @click.stop="openSaveGroupDialog(group)"
                    :title="group.isSaved ? '已保存（点击重新保存）' : '保存为工作流'"
                  >
                    <span class="star-prism"></span>
                    <span class="star-surface">
                      <svg viewBox="0 0 20 20" :fill="group.isSaved ? 'currentColor' : 'none'">
                        <path d="M10 2L12.5 7.5L18 8.5L14 12.5L15 18L10 15.5L5 18L6 12.5L2 8.5L7.5 7.5L10 2Z"
                              stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
                      </svg>
                    </span>
                  </button>
                </Transition>
              </div>

              <!-- 展开的流程节点 -->
              <Transition name="group-expand">
                <div v-if="group.isExpanded" class="group-content">
                  <div class="pipeline-vertical">
                    <template v-for="(level, levelIndex) in getPipelineLevelsForGroup(group.skillPlan, group.pipelineEdges)" :key="levelIndex">
                      <!-- 单节点层 -->
                      <template v-if="level.length === 1">
                        <div v-for="step in level" :key="step.id" class="pipeline-node-group">
                          <div
                            class="pipeline-node"
                            :class="[`node-${step.status}`]"
                            :title="`${step.skillName}: ${step.description}`"
                          >
                            <span class="node-icon">{{ step.skillIcon }}</span>
                            <span v-if="step.status === 'running'" class="node-pulse"></span>
                            <span v-if="step.status === 'completed'" class="node-check">
                              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                                <polyline points="20 6 9 17 4 12"/>
                              </svg>
                            </span>
                            <!-- 节点删除按钮 - 暂停时也可删除 -->
                            <button
                              v-if="step.status !== 'running' || isPaused"
                              class="node-delete"
                              @click.stop="deleteStepFromGroup(group.id, step.id)"
                              :title="step.status === 'running' && isPaused ? '删除并继续下一个' : '删除节点'"
                            >×</button>
                          </div>
                          <span class="node-label" :class="[`label-${step.status}`]" :title="`${step.skillName}: ${step.description}`">{{ step.skillName.split('-')[0] }}</span>
                        </div>
                      </template>
                      <!-- 多节点层（并行分叉） -->
                      <div v-else class="pipeline-parallel-group">
                        <div class="parallel-bracket top"></div>
                        <div class="parallel-nodes">
                          <div
                            v-for="step in level"
                            :key="step.id"
                            class="pipeline-node-group parallel"
                          >
                            <div
                              class="pipeline-node"
                              :class="[`node-${step.status}`]"
                              :title="`${step.skillName}: ${step.description}`"
                            >
                              <span class="node-icon">{{ step.skillIcon }}</span>
                              <span v-if="step.status === 'running'" class="node-pulse"></span>
                              <span v-if="step.status === 'completed'" class="node-check">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                                  <polyline points="20 6 9 17 4 12"/>
                                </svg>
                              </span>
                              <!-- 节点删除按钮 - 暂停时也可删除 -->
                              <button
                                v-if="step.status !== 'running' || isPaused"
                                class="node-delete"
                                @click.stop="deleteStepFromGroup(group.id, step.id)"
                                :title="step.status === 'running' && isPaused ? '删除并继续下一个' : '删除节点'"
                              >×</button>
                            </div>
                            <span class="node-label" :class="[`label-${step.status}`]" :title="`${step.skillName}: ${step.description}`">{{ step.skillName.split('-')[0] }}</span>
                          </div>
                        </div>
                        <div class="parallel-bracket bottom"></div>
                      </div>
                      <!-- 层之间的连接线 -->
                      <div
                        v-if="levelIndex < getPipelineLevelsForGroup(group.skillPlan, group.pipelineEdges).length - 1"
                        class="pipeline-connector"
                        :class="{
                          'completed': level.every(s => s.status === 'completed'),
                          'running': level.some(s => s.status === 'running')
                        }"
                      ></div>
                    </template>
                  </div>
                  <!-- 流程组操作按钮 -->
                  <div class="group-actions">
                    <button
                      class="group-action-btn delete"
                      @click.stop="confirmDeleteGroup(group.id)"
                      title="删除流程"
                    >
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="3 6 5 6 21 6"/>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                      </svg>
                    </button>
                  </div>
                </div>
              </Transition>
            </div>
          </div>
          <!-- 空状态 -->
          <div v-else class="pipeline-empty">
            <div class="empty-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                <path d="M12 2v4m0 12v4M2 12h4m12 0h4"/>
                <circle cx="12" cy="12" r="3" stroke-dasharray="2 2"/>
              </svg>
            </div>
            <span class="empty-text">等待任务</span>
            <span class="empty-hint">发送消息开始</span>
          </div>
        </div>
      </div>

      <!-- 对话区域 -->
      <div
        class="chat-main"
        @dragover.prevent
        @drop="handleDrop"
      >
        <!-- 消息区域 -->
        <div class="chat-messages" ref="chatContainer">
      <div class="messages-inner">
        <template v-for="message in messages" :key="message.id">
          <!-- 用户消息 -->
          <div v-if="message.type === 'user'" class="message message-user" :data-message-id="message.id">
            <div class="message-content">
              <!-- 附件预览 -->
              <div v-if="message.attachments && message.attachments.length > 0" class="message-attachments">
                <div
                  v-for="att in message.attachments"
                  :key="att.id"
                  class="attachment-item"
                >
                  <img v-if="att.url" :src="att.url" class="attachment-img" />
                  <div v-else class="attachment-file">
                    <span class="attachment-icon">{{ getFileIcon(att.type) }}</span>
                    <span class="attachment-name">{{ att.name }}</span>
                  </div>
                </div>
              </div>
              <p v-if="message.content && !message.content.startsWith('[上传了')">{{ message.content }}</p>
              <span class="message-time">{{ formatTime(message.timestamp) }}</span>
            </div>
            <div class="user-avatar">👤</div>
          </div>

          <!-- Agent 消息 -->
          <div v-else class="message message-agent" :data-message-id="message.id">
            <div class="agent-msg-avatar">🤖</div>
            <div class="message-content">
              <!-- 打字中指示器：当消息为空且正在处理时显示 -->
              <div v-if="!message.content && isProcessing && message.id === messages[messages.length - 1]?.id" class="typing-indicator">
                <span></span>
                <span></span>
                <span></span>
              </div>
              <!-- 消息内容：使用 Markdown 渲染 -->
              <div
                v-else-if="message.content"
                class="markdown-content"
                :class="{ 'typing-cursor': isProcessing && message.id === messages[messages.length - 1]?.id }"
                v-html="renderMarkdown(message.content)"
              ></div>

              <!-- 技能编排流程 -->
              <div v-if="message.skillPlan" class="skill-pipeline">
                <div class="pipeline-header">
                  <span class="pipeline-icon">⚡</span>
                  <span class="pipeline-title">技能执行流程</span>
                </div>
                <div class="pipeline-steps">
                  <div
                    v-for="(step, index) in message.skillPlan"
                    :key="step.id"
                    class="pipeline-step"
                    :class="[`status-${step.status}`]"
                  >
                    <div class="step-connector" v-if="index > 0">
                      <div class="connector-line"></div>
                    </div>
                    <div
                      class="step-node"
                      :class="{
                        'clickable': (!isPipelineRunning(message.id) || isPaused) && step.status !== 'running' && step.status !== 'configuring',
                        'disabled': isPipelineRunning(message.id) && !isPaused
                      }"
                      @click="((!isPipelineRunning(message.id) || isPaused) && step.status !== 'running' && step.status !== 'configuring') && openSkillForRerun(message.id, step.id)"
                      :title="isPipelineRunning(message.id) && !isPaused ? '流程运行中，请等待完成或暂停' : '点击配置并重新执行'"
                    >
                      <div class="step-number">{{ index + 1 }}</div>
                      <div class="step-icon">{{ step.skillIcon }}</div>
                      <div class="step-info">
                        <span class="step-name">{{ step.skillName }}</span>
                        <div class="step-desc-wrapper">
                          <span class="step-desc">{{ step.description.length > 20 ? step.description.slice(0, 20) + '...' : step.description }}</span>
                          <div v-if="step.description.length > 20" class="step-tooltip">{{ step.description }}</div>
                        </div>
                      </div>
                      <div class="step-status">
                        <!-- 配置中 -->
                        <span v-if="step.status === 'configuring'" class="status-badge configuring">
                          <span class="config-pulse"></span>
                          配置中...
                        </span>
                        <!-- 等待中 -->
                        <span v-else-if="step.status === 'pending'" class="status-badge pending">
                          等待中
                        </span>
                        <!-- 运行中/已暂停 -->
                        <div v-else-if="step.status === 'running'" class="running-actions">
                          <span
                            class="status-badge running pausable"
                            :class="{ 'is-paused': isPaused }"
                            @click.stop="togglePauseExecution(message.id)"
                            :title="isPaused ? '点击继续执行' : '点击暂停'"
                          >
                            <span v-if="isPaused" class="pause-icon">▶</span>
                            <span v-else class="spinner"></span>
                            {{ isPaused ? '已暂停' : '执行中' }}
                          </span>
                          <!-- 暂停时显示编辑按钮 -->
                          <button
                            v-if="isPaused"
                            class="paused-edit-btn"
                            @click.stop="openPausedSkillConfig(message.id, step)"
                            title="编辑配置后继续执行"
                          >
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                            </svg>
                            编辑
                          </button>
                        </div>
                        <span v-else-if="step.status === 'completed'" class="status-badge completed rerunnable">
                          <span class="completed-text">已完成</span>
                          <span class="rerun-text">重跑</span>
                          <svg class="rerun-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M1 4v6h6"/>
                            <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>
                          </svg>
                        </span>
                        <span v-else-if="step.status === 'missing'" class="step-missing-actions">
                          <span class="status-badge missing">未安装</span>
                          <button class="mini-action-btn create-btn" @click.stop="gotoAddSkill(step.skillName, 'create')">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                              <line x1="12" y1="5" x2="12" y2="19"/>
                              <line x1="5" y1="12" x2="19" y2="12"/>
                            </svg>
                            创建
                          </button>
                          <button class="mini-action-btn upload-btn" @click.stop="gotoAddSkill(step.skillName, 'upload')">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                              <polyline points="17 8 12 3 7 8"/>
                              <line x1="12" y1="3" x2="12" y2="15"/>
                            </svg>
                            上传
                          </button>
                        </span>
                        <span v-else class="status-badge error">失败</span>
                      </div>
                      <!-- 节点删除按钮 - 暂停时也可以删除正在运行的节点 -->
                      <button
                        v-if="step.status !== 'running' || isPaused"
                        class="step-delete-btn"
                        @click.stop="deleteStepFromPipeline(step.id)"
                        :title="step.status === 'running' && isPaused ? '删除并继续执行下一个' : '删除节点'"
                      >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <path d="M18 6L6 18M6 6l12 12"/>
                        </svg>
                      </button>
                    </div>
                    <!-- 输出信息（当前结果 + 历史结果） -->
                    <div v-if="step.status === 'completed' || step.outputHistory?.length" class="step-output-area">
                      <!-- 所有结果（历史 + 当前）排成一排 -->
                      <div class="output-files-row">
                        <!-- 历史结果 -->
                        <div
                          v-for="hist in (step.outputHistory || [])"
                          :key="hist.id"
                          class="output-file-item history"
                        >
                          <button
                            v-if="hist.outputFile"
                            class="output-file-link-mini"
                            :style="{ '--file-color': getFileTypeInfo(hist.outputFile.type).color }"
                            @click.stop="openOutputFile(hist.outputFile)"
                            :title="hist.outputFile.name"
                          >
                            <span class="file-icon">{{ getFileTypeInfo(hist.outputFile.type).icon }}</span>
                            <span class="file-name">{{ hist.outputFile.name.length > 12 ? hist.outputFile.name.slice(0, 10) + '...' : hist.outputFile.name }}</span>
                          </button>
                          <span v-else-if="hist.output" class="history-text-mini">{{ hist.output.slice(0, 15) }}...</span>
                          <button
                            v-if="!isPipelineRunning(message.id) || step.status === 'configuring'"
                            class="file-delete-btn"
                            @click.stop="deleteHistoryItem(message.id, step.id, hist.id)"
                            title="删除"
                          >×</button>
                        </div>
                        <!-- 当前结果 -->
                        <div
                          v-if="step.status === 'completed' && step.outputFile"
                          class="output-file-item current"
                        >
                          <button
                            class="output-file-link-mini current"
                            :style="{ '--file-color': getFileTypeInfo(step.outputFile.type).color }"
                            @click.stop="openOutputFile(step.outputFile)"
                            :title="step.outputFile.name"
                          >
                            <span class="file-icon">{{ getFileTypeInfo(step.outputFile.type).icon }}</span>
                            <span class="file-name">{{ step.outputFile.name.length > 12 ? step.outputFile.name.slice(0, 10) + '...' : step.outputFile.name }}</span>
                            <span class="current-tag">新</span>
                          </button>
                          <button
                            class="save-to-notes-btn"
                            @click.stop="saveToDataNotes(step.outputFile, step.skillName)"
                            title="保存到便签"
                          >📌</button>
                        </div>
                        <span v-if="step.status === 'completed' && step.output && !step.outputFile" class="step-output-text-mini">
                          {{ step.output }}
                        </span>
                      </div>
                    </div>
                    <!-- 执行结果（包括不符合预期的情况） -->
                    <div v-if="step.status === 'error'" class="step-result-area">
                      <div class="result-section">
                        <div class="result-header">
                          <span class="result-icon">📋</span>
                          <span class="result-title">执行结果</span>
                        </div>
                        <div class="result-content">
                          <p class="result-text">{{ getExecutionResultText(step) }}</p>
                        </div>
                      </div>
                      <div class="thinking-section">
                        <div class="thinking-header">
                          <span class="thinking-icon">💭</span>
                          <span class="thinking-title">分析</span>
                        </div>
                        <div class="thinking-content">
                          <p class="thinking-text">{{ getExecutionThinking(step) }}</p>
                          <div v-if="step.errorDetails?.output" class="execution-log">
                            <details>
                              <summary>查看执行日志</summary>
                              <pre>{{ step.errorDetails.output }}</pre>
                            </details>
                          </div>
                        </div>
                      </div>
                      <div class="result-actions">
                        <button class="action-btn retry" @click.stop="retrySkill(step)">重试</button>
                        <button class="action-btn modify" @click.stop="modifySkill(step)">修改技能</button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <span class="message-time">{{ formatTime(message.timestamp) }}</span>
            </div>
          </div>
        </template>

        <!-- 加载指示器已移动到消息内部，这里不再需要 -->
        </div>
      </div>

        <!-- 继续执行确认对话框 -->
        <Transition name="dialog">
          <div v-if="showContinueDialog" class="continue-dialog-overlay" @click.self="cancelContinue">
            <div class="continue-dialog">
              <div class="dialog-icon">✅</div>
              <h3 class="dialog-title">技能添加成功</h3>
              <p class="dialog-desc">
                <strong>{{ addedSkillName }}</strong> 已添加，是否继续执行任务？
              </p>
              <div class="dialog-actions">
                <button class="dialog-btn cancel" @click="cancelContinue">取消</button>
                <button class="dialog-btn confirm" @click="confirmContinue">继续执行</button>
              </div>
            </div>
          </div>
        </Transition>

        <!-- 保存流程对话框 -->
        <Transition name="dialog">
          <div v-if="showSaveDialog" class="continue-dialog-overlay" @click.self="cancelSaveWorkflow">
            <div class="continue-dialog save-dialog">
              <div class="dialog-icon">💾</div>
              <h3 class="dialog-title">保存为工作流</h3>
              <div class="save-form">
                <label class="form-label">流程名称</label>
                <input
                  v-model="saveWorkflowName"
                  class="form-input"
                  placeholder="输入流程名称..."
                />
                <label class="form-label">描述</label>
                <textarea
                  v-model="saveWorkflowDesc"
                  class="form-textarea"
                  placeholder="输入流程描述..."
                  rows="2"
                ></textarea>
              </div>
              <div class="dialog-actions">
                <button class="dialog-btn cancel" @click="cancelSaveWorkflow">取消</button>
                <button class="dialog-btn confirm save" @click="confirmSaveWorkflow">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="20 6 9 17 4 12"/>
                  </svg>
                  保存
                </button>
              </div>
            </div>
          </div>
        </Transition>

        <!-- 删除流程确认对话框 -->
        <Transition name="dialog">
          <div v-if="showDeleteConfirm" class="continue-dialog-overlay" @click.self="cancelDeleteGroup">
            <div class="continue-dialog delete-dialog">
              <div class="dialog-icon">🗑️</div>
              <h3 class="dialog-title">确认删除流程</h3>
              <p class="dialog-desc">
                删除后，该流程及其相关的对话消息将被永久移除。此操作不可撤销。
              </p>
              <div class="dialog-actions">
                <button class="dialog-btn cancel" @click="cancelDeleteGroup">取消</button>
                <button class="dialog-btn confirm delete" @click="deletePipelineGroup">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="3 6 5 6 21 6"/>
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                  </svg>
                  删除
                </button>
              </div>
            </div>
          </div>
        </Transition>


        <!-- 输入区域 -->
        <div class="chat-input">
          <!-- 待发送的数据引用 -->
          <div v-if="pendingRefs.length > 0" class="pending-refs">
            <div
              v-for="ref in pendingRefs"
              :key="ref.id"
              class="pending-ref"
              :class="{ folder: ref.isFolder }"
            >
              <span class="ref-icon">{{ ref.isFolder ? '📁' : '📎' }}</span>
              <span class="ref-name">{{ ref.name }}</span>
              <button class="ref-remove" @click="removePendingRef(ref.id)">×</button>
            </div>
          </div>

          <!-- 已上传文件预览 -->
          <div v-if="uploadedFiles.length > 0" class="uploaded-files">
            <div
              v-for="file in uploadedFiles"
              :key="file.id"
              class="uploaded-file"
              :class="{ 'uploading': file.uploading, 'upload-error': file.uploadError }"
            >
              <img v-if="file.url" :src="file.url" class="file-preview-img" />
              <span v-else class="file-preview-icon">{{ getFileIcon(file.type) }}</span>
              <div class="file-details">
                <span class="file-name">{{ file.name }}</span>
                <span v-if="file.uploading" class="file-status uploading">上传中...</span>
                <span v-else-if="file.uploadError" class="file-status error">{{ file.uploadError }}</span>
                <span v-else-if="file.serverPath" class="file-status success">✓ 已上传</span>
                <span v-else class="file-size">{{ formatFileSize(file.size) }}</span>
              </div>
              <button class="file-remove" @click="removeFile(file.id)">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M18 6L6 18M6 6l12 12"/>
                </svg>
              </button>
            </div>
          </div>

          <div class="input-wrapper">
            <!-- 隐藏的文件输入 -->
            <input
              ref="fileInputRef"
              type="file"
              multiple
              accept="image/*,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.md,.json,.csv"
              style="display: none"
              @change="handleFileSelect"
            />
            <!-- 上传按钮 -->
            <button
              class="upload-btn"
              @click="triggerFileUpload"
              :disabled="isProcessing"
              title="上传文件"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
              </svg>
            </button>
            <textarea
              v-model="inputText"
              placeholder="描述你想完成的任务，或拖拽文件到这里... 输入 / 插入数据"
              @keydown="handleInputKeydown"
              @blur="handleInputBlur"
              :disabled="isProcessing"
              rows="1"
            ></textarea>
            <!-- 停止按钮 -->
            <button
              v-if="isProcessing"
              class="stop-btn"
              @click="stopProcessing"
              title="停止"
            >
              <svg viewBox="0 0 24 24" fill="currentColor">
                <rect x="6" y="6" width="12" height="12" rx="2"/>
              </svg>
            </button>
            <!-- 发送按钮 -->
            <button
              v-else
              class="send-btn"
              @click="sendMessage"
              :disabled="!inputText.trim() && uploadedFiles.length === 0 && pendingRefs.length === 0"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="22" y1="2" x2="11" y2="13"></line>
                <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
              </svg>
            </button>
          </div>
          <div class="input-hint">
            <template v-if="isProcessing">
              <span class="processing-hint">AI 正在思考中... 点击红色按钮可停止</span>
            </template>
            <template v-else>
              按 Enter 发送 · 点击 📎 或拖拽文件上传
            </template>
          </div>
        </div>

      </div>

    </div>

    <!-- "/" 补全弹窗（级联菜单） -->
    <SlashCommandPopup
      ref="slashPopupRef"
      :notes="dataNotesForSlash"
      :query="slashQuery"
      :visible="showSlashPopup"
      :position="slashPopupPosition"
      @select="handleSlashSelect"
      @close="closeSlashPopup"
    />

    <!-- 右侧技能执行面板 -->
    <Transition name="slide-panel">
      <div
        v-if="showSkillExecution && executingSkill"
        ref="skillSidePanelRef"
        class="skill-side-panel"
        :class="{ 'is-floating': isFloating }"
        :style="panelStyle"
      >
        <!-- 左侧拖拽手柄（非浮动时显示） -->
        <div
          v-if="!isFloating"
          class="panel-resize-handle"
          @mousedown="startResize($event, 'w')"
          :class="{ 'is-resizing': isResizing }"
        ></div>

        <!-- 浮动时的8方向拖拽手柄 -->
        <template v-if="isFloating">
          <div class="float-resize-handle float-resize-n" @mousedown="startResize($event, 'n')"></div>
          <div class="float-resize-handle float-resize-s" @mousedown="startResize($event, 's')"></div>
          <div class="float-resize-handle float-resize-e" @mousedown="startResize($event, 'e')"></div>
          <div class="float-resize-handle float-resize-w" @mousedown="startResize($event, 'w')"></div>
          <div class="float-resize-handle float-resize-ne" @mousedown="startResize($event, 'ne')"></div>
          <div class="float-resize-handle float-resize-nw" @mousedown="startResize($event, 'nw')"></div>
          <div class="float-resize-handle float-resize-se" @mousedown="startResize($event, 'se')"></div>
          <div class="float-resize-handle float-resize-sw" @mousedown="startResize($event, 'sw')"></div>
        </template>

        <div class="side-panel-inner">
          <!-- 面板头部（可拖拽移动） -->
          <header
            class="panel-header"
            :class="{ 'is-draggable': true, 'is-floating': isFloating }"
            @mousedown="startDragPanel"
          >
            <div class="panel-skill-info">
              <div class="panel-skill-avatar">
                <span>{{ executingSkill.icon }}</span>
              </div>
              <div class="panel-skill-meta">
                <h3 class="panel-skill-name">{{ executingSkill.name }}</h3>
                <Transition name="status-fade" mode="out-in">
                  <span v-if="skillPanelComplete" class="panel-status complete">
                    <svg viewBox="0 0 16 16" fill="none">
                      <path d="M13.5 4.5L6 12L2.5 8.5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                    已完成
                  </span>
                  <span v-else-if="skillPanelProcessing" class="panel-status processing">
                    <span class="pulse-dot"></span>
                    处理中
                  </span>
                </Transition>
              </div>
            </div>
          </header>

          <!-- 对话区域（支持拖拽上传） -->
          <main
            class="panel-chat-area"
            ref="skillPanelChatRef"
            @dragenter="panelHandleDragEnter"
            @dragleave="panelHandleDragLeave"
            @dragover="panelHandleDragOver"
            @drop="panelHandleDrop"
            :class="{ 'is-drag-over': panelIsDragging }"
          >
            <!-- 拖拽上传提示 -->
            <div v-if="panelIsDragging" class="panel-drop-overlay">
              <div class="panel-drop-hint">
                <svg viewBox="0 0 24 24" fill="none">
                  <path d="M12 16V4M12 4l-4 4M12 4l4 4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                  <path d="M20 16v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                </svg>
                <span>释放文件以上传</span>
              </div>
            </div>
            <TransitionGroup name="msg-fade" tag="div" class="panel-messages">
              <div
                v-for="msg in skillPanelMessages"
                :key="msg.id"
                class="panel-message"
                :class="[`is-${msg.role}`, { 'is-executing': msg.isExecuting }]"
              >
                <!-- AI 消息 -->
                <template v-if="msg.role === 'assistant'">
                  <div class="panel-msg-avatar">
                    <span>{{ executingSkill.icon }}</span>
                  </div>
                  <div class="panel-msg-bubble">
                    <div v-if="msg.content" class="panel-bubble-text" v-html="renderPanelMarkdown(msg.content)"></div>
                    <div v-else class="panel-typing">
                      <span></span><span></span><span></span>
                    </div>
                  </div>
                </template>

                <!-- 用户消息 -->
                <template v-else-if="msg.role === 'user'">
                  <div class="panel-msg-bubble user">
                    <div class="panel-bubble-text">{{ msg.content }}</div>
                  </div>
                </template>

                <!-- 系统消息 -->
                <template v-else>
                  <div class="panel-system-msg">
                    <div v-if="msg.isExecuting" class="panel-executing">
                      <svg class="spin-icon" viewBox="0 0 24 24">
                        <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2" fill="none" stroke-dasharray="60 40"/>
                      </svg>
                      <span>{{ msg.content }}</span>
                    </div>
                    <span v-else>{{ msg.content }}</span>
                  </div>
                </template>
              </div>
            </TransitionGroup>
          </main>

          <!-- 底部输入区 -->
          <footer class="panel-footer">
            <Transition name="fade" mode="out-in">
              <!-- 完成状态 -->
              <div v-if="skillPanelComplete" key="complete" class="panel-complete-state">
                <div class="complete-icon">
                  <svg viewBox="0 0 24 24" fill="none">
                    <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="1.5"/>
                    <path d="M8 12l3 3 5-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                  </svg>
                </div>
                <span class="complete-text">执行完成，即将返回...</span>
              </div>

              <!-- 等待确认状态 -->
              <div v-else-if="skillPanelWaitingConfirm" key="confirm" class="panel-confirm-area">
                <div class="confirm-hint">请确认以上信息是否正确</div>
                <div class="confirm-actions">
                  <button class="confirm-btn primary" @click="confirmExecuteSkill">
                    <svg viewBox="0 0 24 24" fill="none">
                      <path d="M5 12l5 5L20 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                    确认执行
                  </button>
                  <button class="confirm-btn secondary" @click="continueAddDetails">
                    <svg viewBox="0 0 24 24" fill="none">
                      <path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                    </svg>
                    继续补充
                  </button>
                  <button class="confirm-btn cancel" @click="cancelSkillExecution">
                    <svg viewBox="0 0 24 24" fill="none">
                      <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                    </svg>
                    取消
                  </button>
                </div>
              </div>

              <!-- 输入状态 -->
              <div v-else key="input" class="panel-input-area">
                <!-- 隐藏的文件输入 -->
                <input
                  ref="panelFileInputRef"
                  type="file"
                  multiple
                  accept=".xlsx,.xls,.csv,.json,.txt,.png,.jpg,.jpeg,.gif,.pdf"
                  style="display: none"
                  @change="panelHandleFileSelect"
                />

                <!-- 已上传文件预览 -->
                <div v-if="panelUploadedFiles.length > 0" class="panel-files-preview">
                  <div
                    v-for="file in panelUploadedFiles"
                    :key="file.id"
                    class="panel-file-item"
                    :class="{ 'is-uploading': file.uploading, 'has-error': file.uploadError }"
                  >
                    <span class="panel-file-icon">{{ file.type.startsWith('image/') ? '🖼️' : '📄' }}</span>
                    <span class="panel-file-name">{{ file.name }}</span>
                    <button class="panel-file-remove" @click="panelRemoveFile(file.id)" title="移除">
                      <svg viewBox="0 0 16 16" fill="none">
                        <path d="M12 4L4 12M4 4l8 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                      </svg>
                    </button>
                  </div>
                </div>

                <div class="panel-input-row">
                  <!-- 跳过配置按钮 -->
                  <button
                    v-if="!skillPanelProcessing && skillPanelMessages.length <= 1"
                    class="panel-quick-btn"
                    @click="quickExecuteSkillPanel"
                    title="跳过配置，直接执行"
                  >
                    <svg viewBox="0 0 16 16" fill="none">
                      <path d="M8.5 1L3 9h4.5l-.5 6 5.5-8H8l.5-6z" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                  </button>

                  <!-- 上传按钮 -->
                  <button
                    class="panel-upload-btn"
                    @click="panelTriggerFileUpload"
                    :disabled="skillPanelProcessing"
                    title="上传文件"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
                    </svg>
                  </button>

                  <textarea
                    ref="skillPanelInputRef"
                    v-model="skillPanelInput"
                    placeholder="输入需求或拖拽文件..."
                    @keydown.enter.exact.prevent="sendSkillPanelMessage"
                    :disabled="skillPanelProcessing"
                    rows="1"
                  ></textarea>
                  <button
                    class="panel-send-btn"
                    @click="sendSkillPanelMessage"
                    :disabled="(!skillPanelInput.trim() && panelUploadedFiles.length === 0) || skillPanelProcessing"
                  >
                    <svg viewBox="0 0 24 24" fill="none">
                      <path d="M5 12h14M12 5l7 7-7 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                  </button>
                </div>
              </div>
            </Transition>
          </footer>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.agent-chat {
  position: relative;
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid #e5e7eb;
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
}

/* Header */
.chat-header {
  padding: 14px 20px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.agent-avatar {
  position: relative;
  width: 40px;
  height: 40px;
  background: rgba(255,255,255,0.2);
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.avatar-icon {
  font-size: 20px;
}

.status-dot {
  position: absolute;
  bottom: -2px;
  right: -2px;
  width: 10px;
  height: 10px;
  background: #10b981;
  border: 2px solid #667eea;
  border-radius: 50%;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.1); opacity: 0.8; }
}

.agent-info h3 {
  font-size: 14px;
  font-weight: 600;
  color: #fff;
  margin: 0 0 2px 0;
}

.agent-status {
  font-size: 11px;
  color: rgba(255,255,255,0.8);
}

.header-right {
  display: flex;
  align-items: center;
}

.skill-count {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 6px 14px;
  background: rgba(255,255,255,0.15);
  border-radius: 8px;
}

.count-number {
  font-size: 16px;
  font-weight: 700;
  color: #fff;
}

.count-label {
  font-size: 9px;
  color: rgba(255,255,255,0.8);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* Chat Body Layout */
.chat-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}

/* 垂直流程条 - 多流程管理面板 */
.pipeline-sidebar {
  width: 140px;
  background: #f8fafc;
  border-right: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  box-shadow: inset -1px 0 0 rgba(0,0,0,0.02);
}

.pipeline-sidebar-header {
  padding: 10px 8px;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  background: linear-gradient(180deg, #fff 0%, #f8fafc 100%);
}

.header-icon {
  width: 12px;
  height: 12px;
  color: #64748b;
}

.sidebar-title {
  font-size: 10px;
  font-weight: 600;
  color: #475569;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.step-counter {
  font-size: 9px;
  font-weight: 600;
  color: #6366f1;
  background: #eef2ff;
  padding: 2px 6px;
  border-radius: 10px;
  margin-left: 2px;
}

.group-counter {
  font-size: 10px;
  font-weight: 500;
  color: #64748b;
  margin-left: 2px;
}

.collapse-all-btn {
  width: 18px;
  height: 18px;
  padding: 0;
  background: transparent;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #94a3b8;
  transition: all 0.2s ease;
  margin-left: auto;
  border-radius: 4px;
}

.collapse-all-btn:hover {
  color: #6366f1;
  background: rgba(99, 102, 241, 0.1);
}

.collapse-all-btn svg {
  width: 12px;
  height: 12px;
}

/* 多流程组列表 */
.pipeline-groups {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px;
}

.pipeline-group {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  overflow: hidden;
  transition: all 0.2s ease;
}

.pipeline-group:hover {
  border-color: #cbd5e1;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.04);
}

.pipeline-group.is-expanded {
  border-color: #c7d2fe;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.08);
}

/* 选中状态 */
.pipeline-group.is-active {
  border-color: #6366f1;
  border-left: 3px solid #6366f1;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.04) 0%, rgba(139, 92, 246, 0.04) 100%);
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.12);
}

.pipeline-group.is-active .group-header {
  background: linear-gradient(90deg, rgba(99, 102, 241, 0.08) 0%, transparent 100%);
}

.pipeline-group.is-active .group-name {
  color: #4f46e5;
  font-weight: 700;
}

.pipeline-group.is-active .group-expand-icon {
  color: #6366f1;
}

.pipeline-group.is-active .group-progress {
  color: #6366f1;
}

/* 流程组头部 */
.group-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px;
  cursor: pointer;
  transition: background 0.15s ease;
}

.group-header:hover {
  background: #f8fafc;
}

.group-expand-icon {
  width: 14px;
  height: 14px;
  color: #94a3b8;
  flex-shrink: 0;
  transition: transform 0.2s ease;
}

.group-expand-icon svg {
  width: 100%;
  height: 100%;
}

.pipeline-group.is-expanded .group-expand-icon {
  color: #6366f1;
}

.group-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.group-name {
  font-size: 10px;
  font-weight: 600;
  color: #374151;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.group-progress {
  display: flex;
  align-items: center;
  gap: 3px;
  font-size: 9px;
  font-weight: 500;
  color: #94a3b8;
}

.group-progress.progress-completed {
  color: #10b981;
}

.group-progress.progress-running {
  color: #6366f1;
}

.group-progress.progress-paused {
  color: #f59e0b;
}

.group-progress.progress-error {
  color: #ef4444;
}

/* 流程组头部的小星星保存按钮 */
.group-save-star {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  width: 24px;
  height: 24px;
  background: none;
  border: none;
  cursor: pointer;
  overflow: visible;
  flex-shrink: 0;
  margin-left: auto;
}

.star-prism {
  position: absolute;
  inset: -3px;
  background: conic-gradient(
    from 0deg,
    rgba(99, 102, 241, 0.15),
    rgba(236, 72, 153, 0.12),
    rgba(251, 191, 36, 0.12),
    rgba(52, 211, 153, 0.12),
    rgba(99, 102, 241, 0.15)
  );
  border-radius: 50%;
  filter: blur(3px);
  opacity: 0.7;
  animation: prismRotate 8s linear infinite;
  z-index: 0;
}

.star-surface {
  position: relative;
  z-index: 1;
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(
    145deg,
    rgba(255, 255, 255, 0.95) 0%,
    rgba(248, 250, 252, 0.9) 100%
  );
  border-radius: 50%;
  border: 1px solid rgba(148, 163, 184, 0.25);
  box-shadow:
    0 1px 2px rgba(0, 0, 0, 0.04),
    0 2px 6px rgba(0, 0, 0, 0.03),
    inset 0 1px 0 rgba(255, 255, 255, 0.8);
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.star-surface svg {
  width: 12px;
  height: 12px;
  color: #6366f1;
  transition: all 0.3s ease;
  filter: drop-shadow(0 1px 1px rgba(99, 102, 241, 0.2));
}

.group-save-star:hover .star-surface {
  transform: translateY(-1px) scale(1.1);
  border-color: rgba(99, 102, 241, 0.3);
  box-shadow:
    0 3px 10px rgba(99, 102, 241, 0.15),
    0 2px 4px rgba(0, 0, 0, 0.04),
    inset 0 1px 0 rgba(255, 255, 255, 0.9);
}

.group-save-star:hover .star-prism {
  opacity: 1;
  filter: blur(4px);
}

.group-save-star:hover .star-surface svg {
  transform: scale(1.1);
  color: #4f46e5;
}

.group-save-star:active .star-surface {
  transform: translateY(0) scale(0.95);
  box-shadow:
    0 1px 2px rgba(0, 0, 0, 0.06),
    inset 0 1px 2px rgba(0, 0, 0, 0.04);
}

/* 已保存状态 - 金色填充 */
.group-save-star.is-saved .star-prism {
  background: conic-gradient(
    from 0deg,
    rgba(251, 191, 36, 0.2),
    rgba(245, 158, 11, 0.18),
    rgba(217, 119, 6, 0.18),
    rgba(251, 191, 36, 0.2)
  );
}

.group-save-star.is-saved .star-surface {
  background: linear-gradient(
    145deg,
    rgba(254, 243, 199, 0.95) 0%,
    rgba(253, 230, 138, 0.9) 100%
  );
  border-color: rgba(245, 158, 11, 0.4);
}

.group-save-star.is-saved .star-surface svg {
  color: #f59e0b;
  filter: drop-shadow(0 1px 2px rgba(245, 158, 11, 0.3));
}

.group-save-star.is-saved:hover .star-surface {
  border-color: rgba(217, 119, 6, 0.5);
  box-shadow:
    0 3px 10px rgba(245, 158, 11, 0.2),
    0 2px 4px rgba(0, 0, 0, 0.04),
    inset 0 1px 0 rgba(255, 255, 255, 0.9);
}

.group-save-star.is-saved:hover .star-surface svg {
  color: #d97706;
}

/* 未完成状态 - 虚线边框提示 */
.group-save-star.is-pending .star-surface {
  border-style: dashed;
  opacity: 0.7;
}

.group-save-star.is-pending:hover .star-surface {
  opacity: 1;
  border-style: solid;
}

.mini-spinner {
  width: 8px;
  height: 8px;
  border: 1.5px solid rgba(99, 102, 241, 0.2);
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

/* 流程组展开内容 */
.group-content {
  padding: 8px;
  padding-top: 0;
  border-top: 1px solid #e2e8f0;
  background: #f8fafc;
}

.group-content .pipeline-vertical {
  padding: 8px 0;
}

.group-content .pipeline-node {
  width: 36px;
  height: 36px;
  border-radius: 8px;
}

.group-content .node-icon {
  font-size: 14px;
}

.group-content .node-label {
  font-size: 8px;
  max-width: 60px;
}

.group-content .pipeline-connector {
  height: 10px;
  margin: 4px 0;
}

/* 流程组操作按钮 */
.group-actions {
  display: flex;
  justify-content: center;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px dashed #e2e8f0;
}

.group-action-btn {
  width: 28px;
  height: 28px;
  padding: 0;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #64748b;
  transition: all 0.2s ease;
}

.group-action-btn svg {
  width: 14px;
  height: 14px;
}

.group-action-btn.save:hover {
  background: rgba(16, 185, 129, 0.1);
  border-color: #10b981;
  color: #10b981;
}

.group-action-btn.delete:hover {
  background: rgba(239, 68, 68, 0.1);
  border-color: #ef4444;
  color: #ef4444;
}

/* 展开动画 */
.group-expand-enter-active {
  animation: expandIn 0.25s ease;
}

.group-expand-leave-active {
  animation: expandOut 0.2s ease forwards;
}

@keyframes expandIn {
  from {
    opacity: 0;
    max-height: 0;
    padding-top: 0;
    padding-bottom: 0;
  }
  to {
    opacity: 1;
    max-height: 400px;
    padding-top: 8px;
    padding-bottom: 8px;
  }
}

@keyframes expandOut {
  from {
    opacity: 1;
    max-height: 400px;
  }
  to {
    opacity: 0;
    max-height: 0;
    padding-top: 0;
    padding-bottom: 0;
  }
}

/* 侧边栏保存按钮 - Crystal Prism Style */
.sidebar-save-btn {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 10px auto;
  padding: 0;
  width: 36px;
  height: 36px;
  background: none;
  border: none;
  cursor: pointer;
  overflow: visible;
}

/* 棱镜折射光效 */
.save-btn-prism {
  position: absolute;
  inset: -4px;
  background: conic-gradient(
    from 0deg,
    rgba(99, 102, 241, 0.15),
    rgba(236, 72, 153, 0.12),
    rgba(251, 191, 36, 0.12),
    rgba(52, 211, 153, 0.12),
    rgba(99, 102, 241, 0.15)
  );
  border-radius: 50%;
  filter: blur(4px);
  opacity: 0.8;
  animation: prismRotate 8s linear infinite;
  z-index: 0;
}

@keyframes prismRotate {
  to { transform: rotate(360deg); }
}

/* 主按钮表面 */
.save-btn-surface {
  position: relative;
  z-index: 1;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(
    145deg,
    rgba(255, 255, 255, 0.95) 0%,
    rgba(248, 250, 252, 0.9) 100%
  );
  border-radius: 50%;
  border: 1px solid rgba(148, 163, 184, 0.25);
  box-shadow:
    0 1px 2px rgba(0, 0, 0, 0.04),
    0 2px 8px rgba(0, 0, 0, 0.03),
    inset 0 1px 0 rgba(255, 255, 255, 0.8);
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.save-icon {
  width: 16px;
  height: 16px;
  color: #6366f1;
  transition: all 0.3s ease;
  filter: drop-shadow(0 1px 1px rgba(99, 102, 241, 0.2));
}

/* Hover */
.sidebar-save-btn:hover .save-btn-surface {
  transform: translateY(-2px) scale(1.08);
  border-color: rgba(99, 102, 241, 0.3);
  box-shadow:
    0 4px 12px rgba(99, 102, 241, 0.15),
    0 2px 4px rgba(0, 0, 0, 0.04),
    inset 0 1px 0 rgba(255, 255, 255, 0.9);
}

.sidebar-save-btn:hover .save-btn-prism {
  opacity: 1;
  filter: blur(5px);
}

.sidebar-save-btn:hover .save-icon {
  transform: scale(1.1);
  color: #4f46e5;
}

/* Active */
.sidebar-save-btn:active .save-btn-surface {
  transform: translateY(0) scale(0.96);
  box-shadow:
    0 1px 2px rgba(0, 0, 0, 0.06),
    inset 0 1px 2px rgba(0, 0, 0, 0.04);
}

/* 入场动画 */
.save-btn-enter-active {
  animation: crystalAppear 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.save-btn-leave-active {
  animation: crystalDisappear 0.25s ease-out forwards;
}

@keyframes crystalAppear {
  0% {
    opacity: 0;
    transform: scale(0.5) rotate(-180deg);
  }
  60% {
    transform: scale(1.1) rotate(10deg);
  }
  100% {
    opacity: 1;
    transform: scale(1) rotate(0deg);
  }
}

@keyframes crystalDisappear {
  to {
    opacity: 0;
    transform: scale(0.6) rotate(90deg);
  }
}

.pipeline-sidebar-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px 0;
}

.pipeline-sidebar-content::-webkit-scrollbar {
  width: 4px;
}

.pipeline-sidebar-content::-webkit-scrollbar-track {
  background: transparent;
}

.pipeline-sidebar-content::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 2px;
}

.pipeline-vertical {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0;
}

/* 节点组合 */
.pipeline-node-group {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.pipeline-node-group.parallel {
  flex: 1;
}

/* 并行分叉组 */
.pipeline-parallel-group {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
  padding: 0 4px;
}

.parallel-nodes {
  display: flex;
  justify-content: center;
  gap: 6px;
  width: 100%;
}

.parallel-nodes .pipeline-node {
  width: 36px;
  height: 36px;
}

.parallel-nodes .node-icon {
  font-size: 14px;
}

.parallel-nodes .node-label {
  font-size: 8px;
  max-width: 36px;
}

/* 并行分叉括号 */
.parallel-bracket {
  width: 70%;
  height: 8px;
  position: relative;
}

.parallel-bracket.top {
  border-left: 2px solid #e2e8f0;
  border-right: 2px solid #e2e8f0;
  border-top: 2px solid #e2e8f0;
  border-radius: 4px 4px 0 0;
  margin-bottom: 4px;
}

.parallel-bracket.bottom {
  border-left: 2px solid #e2e8f0;
  border-right: 2px solid #e2e8f0;
  border-bottom: 2px solid #e2e8f0;
  border-radius: 0 0 4px 4px;
  margin-top: 4px;
}

.parallel-bracket.top::before,
.parallel-bracket.bottom::before {
  content: '';
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  width: 2px;
  height: 6px;
  background: #e2e8f0;
}

.parallel-bracket.top::before {
  top: -6px;
}

.parallel-bracket.bottom::before {
  bottom: -6px;
}

.node-label {
  font-size: 9px;
  font-weight: 500;
  color: #94a3b8;
  max-width: 76px;
  text-align: center;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: color 0.2s ease;
}

.node-label.label-running {
  color: #6366f1;
  font-weight: 600;
}

.node-label.label-completed {
  color: #10b981;
  font-weight: 600;
}

.node-label.label-missing {
  color: #f59e0b;
  font-weight: 600;
}

.node-label.label-error {
  color: #ef4444;
  font-weight: 600;
}

/* 垂直连接线 */
.pipeline-connector {
  width: 2px;
  height: 16px;
  background: #e2e8f0;
  flex-shrink: 0;
  margin: 6px 0;
  border-radius: 1px;
}

.pipeline-connector.completed {
  background: #10b981;
}

.pipeline-connector.running {
  background: linear-gradient(180deg, #10b981 0%, #6366f1 50%, #e2e8f0 100%);
  background-size: 100% 200%;
  animation: flowLineVertical 1.5s ease infinite;
}

@keyframes flowLineVertical {
  0% { background-position: 0 100%; }
  100% { background-position: 0 0; }
}

/* 节点 */
.pipeline-node {
  width: 46px;
  height: 46px;
  background: #fff;
  border: 2px solid #e2e8f0;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  position: relative;
  transition: all 0.3s ease;
  cursor: pointer;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}

.pipeline-node:hover {
  border-color: #a5b4fc;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.15);
}

.node-icon {
  font-size: 18px;
  line-height: 1;
}

/* 节点删除按钮 */
.node-delete {
  position: absolute;
  top: -6px;
  right: -6px;
  width: 16px;
  height: 16px;
  background: #ef4444;
  border: 2px solid #fff;
  border-radius: 50%;
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
  opacity: 0;
  transition: all 0.15s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  z-index: 10;
}

.pipeline-node:hover .node-delete {
  opacity: 1;
}

.node-delete:hover {
  background: #dc2626;
  transform: scale(1.1);
}

/* 节点输入标记 */
.node-input-badge {
  position: absolute;
  bottom: -4px;
  right: -4px;
  width: 16px;
  height: 16px;
  background: #10b981;
  border: 2px solid #fff;
  border-radius: 50%;
  color: #fff;
  font-size: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.pipeline-node.has-input {
  border-color: #10b981;
  cursor: pointer;
}

.pipeline-node.has-input:hover {
  box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.2);
}

/* 技能输入对话框样式 */
.skill-input-dialog .dialog-skill-name {
  font-size: 14px;
  font-weight: 600;
  color: #6366f1;
  margin: -8px 0 8px;
}

.skill-input-dialog .dialog-desc {
  font-size: 12px;
  color: #64748b;
  margin-bottom: 16px;
}

/* 状态样式 */
.pipeline-node.node-pending {
  background: #fff;
  border-color: #e2e8f0;
}

.pipeline-node.node-running {
  background: linear-gradient(135deg, rgba(99,102,241,0.1) 0%, rgba(139,92,246,0.1) 100%);
  border-color: #6366f1;
  box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.1), 0 2px 8px rgba(99, 102, 241, 0.15);
}

.pipeline-node.node-completed {
  background: linear-gradient(135deg, rgba(16,185,129,0.1) 0%, rgba(5,150,105,0.1) 100%);
  border-color: #10b981;
  box-shadow: 0 1px 3px rgba(16, 185, 129, 0.15);
}

.pipeline-node.node-missing {
  background: linear-gradient(135deg, rgba(245,158,11,0.1) 0%, rgba(217,119,6,0.1) 100%);
  border-color: #f59e0b;
}

.pipeline-node.node-error {
  background: linear-gradient(135deg, rgba(239,68,68,0.1) 0%, rgba(220,38,38,0.1) 100%);
  border-color: #ef4444;
}

/* 完成勾选标记 */
.node-check {
  position: absolute;
  bottom: -3px;
  right: -3px;
  width: 14px;
  height: 14px;
  background: #10b981;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 1px 3px rgba(16, 185, 129, 0.4);
}

.node-check svg {
  width: 9px;
  height: 9px;
  color: #fff;
}

/* 运行中脉冲动画 */
.node-pulse {
  position: absolute;
  inset: -4px;
  border: 2px solid #6366f1;
  border-radius: 12px;
  animation: nodePulse 1.5s ease-out infinite;
}

@keyframes nodePulse {
  0% {
    transform: scale(1);
    opacity: 0.6;
  }
  100% {
    transform: scale(1.15);
    opacity: 0;
  }
}

/* 空状态 */
.pipeline-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding: 20px 8px;
  text-align: center;
}

.empty-icon {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 12px;
}

.empty-icon svg {
  width: 100%;
  height: 100%;
  color: #cbd5e1;
}

.empty-text {
  font-size: 11px;
  font-weight: 500;
  color: #94a3b8;
  margin-bottom: 4px;
}

.empty-hint {
  font-size: 9px;
  color: #cbd5e1;
}

/* Chat Main */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  position: relative;
}

/* Messages */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  background: #f8fafc;
}

.chat-messages::-webkit-scrollbar {
  width: 6px;
}

.chat-messages::-webkit-scrollbar-track {
  background: transparent;
}

.chat-messages::-webkit-scrollbar-thumb {
  background: #d1d5db;
  border-radius: 3px;
}

.messages-inner {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.message {
  display: flex;
  gap: 10px;
  animation: messageIn 0.3s ease;
}

@keyframes messageIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 消息高亮效果 */
.message-highlight {
  animation: messageHighlight 1.5s ease;
}

@keyframes messageHighlight {
  0%, 100% {
    background: transparent;
  }
  20%, 60% {
    background: rgba(99, 102, 241, 0.1);
    border-radius: 12px;
  }
}

.message-user {
  justify-content: flex-end;
}

.message-user .message-content {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
  border-radius: 16px 16px 4px 16px;
  max-width: 70%;
}

.message-user .message-content p {
  margin: 0;
  font-size: 13px;
  line-height: 1.35;
}

.message-user .message-time {
  color: rgba(255,255,255,0.7);
}

.user-avatar {
  width: 32px;
  height: 32px;
  background: #e5e7eb;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
}

.message-agent {
  align-items: flex-start;
}

.agent-msg-avatar {
  width: 32px;
  height: 32px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
}

.message-agent .message-content {
  background: #fff;
  border: 1px solid #e5e7eb;
  color: #374151;
  border-radius: 16px 16px 16px 4px;
  max-width: 85%;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}

.message-content {
  padding: 12px 16px;
}

.message-content p {
  margin: 0 0 6px 0;
  font-size: 13px;
  line-height: 1.4;
}

/* Markdown 样式 */
.markdown-content {
  font-size: 13px;
  line-height: 1.4;
  word-wrap: break-word;
}

.markdown-content h2 {
  font-size: 16px;
  font-weight: 700;
  margin: 12px 0 6px 0;
  color: #1e293b;
}

.markdown-content h3 {
  font-size: 14px;
  font-weight: 600;
  margin: 10px 0 4px 0;
  color: #334155;
}

.markdown-content h4 {
  font-size: 13px;
  font-weight: 600;
  margin: 8px 0 3px 0;
  color: #475569;
}

.markdown-content strong {
  font-weight: 600;
  color: #1e293b;
}

.markdown-content em {
  font-style: italic;
}

.markdown-content .code-block {
  background: #1e293b;
  color: #e2e8f0;
  padding: 10px 14px;
  border-radius: 8px;
  margin: 8px 0;
  overflow-x: auto;
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
  font-size: 12px;
  line-height: 1.5;
}

.markdown-content .code-block code {
  background: none;
  padding: 0;
  color: inherit;
}

.markdown-content .inline-code {
  background: #f1f5f9;
  color: #e11d48;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
  font-size: 12px;
}

.markdown-content li {
  margin: 2px 0;
  padding-left: 8px;
  position: relative;
}

.markdown-content li::before {
  content: '•';
  position: absolute;
  left: -8px;
  color: #6366f1;
}

.markdown-content a {
  color: #6366f1;
  text-decoration: none;
}

.markdown-content a:hover {
  text-decoration: underline;
}

/* 打字光标效果 - 只在正在输入时显示 */
.markdown-content.typing-cursor::after {
  content: '';
  display: inline-block;
  width: 2px;
  height: 14px;
  background: #6366f1;
  margin-left: 2px;
  animation: blink 0.8s infinite;
  vertical-align: text-bottom;
}

@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}

.message-time {
  font-size: 10px;
  color: #9ca3af;
}

/* Skill Pipeline */
.skill-pipeline {
  margin: 12px 0;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  overflow: hidden;
}

.pipeline-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: linear-gradient(135deg, rgba(102,126,234,0.1) 0%, rgba(118,75,162,0.1) 100%);
  border-bottom: 1px solid #e5e7eb;
}

.pipeline-icon {
  font-size: 14px;
}

.pipeline-title {
  font-size: 11px;
  font-weight: 600;
  color: #6366f1;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.pipeline-steps {
  padding: 12px;
}

.pipeline-step {
  position: relative;
}

.step-connector {
  display: flex;
  justify-content: flex-start;
  padding: 4px 0 4px 18px;
}

.connector-line {
  width: 2px;
  height: 14px;
  background: #e5e7eb;
  border-radius: 1px;
}

.pipeline-step.status-completed .connector-line {
  background: #10b981;
}

.pipeline-step.status-running .connector-line {
  background: #6366f1;
}

.step-node {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  transition: all 0.3s ease;
  position: relative;
}

/* 步骤删除按钮 */
.step-delete-btn {
  position: absolute;
  top: -8px;
  right: -8px;
  width: 20px;
  height: 20px;
  background: #ef4444;
  border: 2px solid #fff;
  border-radius: 50%;
  color: #fff;
  cursor: pointer;
  opacity: 0;
  transition: all 0.15s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
  z-index: 10;
}

.step-delete-btn svg {
  width: 10px;
  height: 10px;
}

.step-node:hover .step-delete-btn {
  opacity: 1;
}

.step-delete-btn:hover {
  background: #dc2626;
  transform: scale(1.1);
}

.step-node.clickable {
  cursor: pointer;
}

.step-node.clickable:hover {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.05) 0%, rgba(139, 92, 246, 0.05) 100%);
  border-color: #818cf8;
  transform: translateY(-1px);
}

.step-node.disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.step-node.needs-input {
  border-color: #6366f1;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.03) 0%, rgba(139, 92, 246, 0.03) 100%);
  animation: needsInputPulse 2s ease-in-out infinite;
}

@keyframes needsInputPulse {
  0%, 100% {
    box-shadow: 0 0 0 0 rgba(99, 102, 241, 0.2);
  }
  50% {
    box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.1);
  }
}

.step-node.needs-input:hover {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.08) 0%, rgba(139, 92, 246, 0.08) 100%);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.15);
  transform: translateY(-1px);
}

.status-badge.needs-input-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  color: #fff;
  padding: 4px 10px;
  font-weight: 500;
}

.status-badge.needs-input-badge svg {
  width: 12px;
  height: 12px;
}

.pipeline-step.status-running .step-node {
  background: rgba(99, 102, 241, 0.05);
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.pipeline-step.status-completed .step-node {
  background: rgba(16, 185, 129, 0.05);
  border-color: #10b981;
}

.step-number {
  width: 22px;
  height: 22px;
  background: #f3f4f6;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  color: #6b7280;
  flex-shrink: 0;
}

.pipeline-step.status-running .step-number {
  background: #6366f1;
  color: #fff;
}

.pipeline-step.status-completed .step-number {
  background: #10b981;
  color: #fff;
}

.step-icon {
  font-size: 18px;
  flex-shrink: 0;
}

.step-info {
  flex: 1;
  min-width: 0;
}

.step-name {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: #111827;
  margin-bottom: 2px;
}

.step-desc-wrapper {
  position: relative;
}

.step-desc {
  display: block;
  font-size: 11px;
  color: #6b7280;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.step-tooltip {
  position: absolute;
  left: 50%;
  bottom: 100%;
  margin-bottom: 8px;
  padding: 8px 12px;
  background: #1e293b;
  color: #f1f5f9;
  font-size: 12px;
  line-height: 1.4;
  border-radius: 6px;
  max-width: 280px;
  width: max-content;
  z-index: 99999;
  opacity: 0;
  visibility: hidden;
  transform: translateX(-50%) translateY(4px);
  transition: all 0.15s ease;
  box-shadow: 0 4px 20px rgba(0,0,0,0.3);
  pointer-events: none;
  white-space: normal;
  word-break: break-word;
}

.step-tooltip::after {
  content: '';
  position: absolute;
  bottom: -6px;
  left: 50%;
  transform: translateX(-50%);
  border: 6px solid transparent;
  border-top-color: #1e293b;
  border-bottom: none;
}

.step-desc-wrapper:hover .step-tooltip {
  opacity: 1;
  visibility: visible;
  transform: translateX(-50%) translateY(0);
}

.step-status {
  flex-shrink: 0;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 10px;
  font-weight: 600;
}

.status-badge.pending {
  background: #f3f4f6;
  color: #9ca3af;
}

.status-badge.running {
  background: rgba(99, 102, 241, 0.1);
  color: #6366f1;
}

.status-badge.running.pausable {
  cursor: pointer;
  transition: all 0.2s ease;
}

.status-badge.running.pausable:hover {
  background: rgba(99, 102, 241, 0.2);
  transform: scale(1.02);
}

.status-badge.running.is-paused {
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
  animation: pulse-pause 1.5s ease-in-out infinite;
}

.status-badge.running.is-paused:hover {
  background: rgba(245, 158, 11, 0.25);
}

.pause-icon {
  font-size: 8px;
  margin-right: 2px;
}

/* 运行中/暂停时的操作区 */
.running-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.paused-edit-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 3px 8px;
  font-size: 10px;
  background: rgba(99, 102, 241, 0.1);
  color: #6366f1;
  border: 1px solid rgba(99, 102, 241, 0.3);
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.paused-edit-btn:hover {
  background: rgba(99, 102, 241, 0.2);
  border-color: #6366f1;
}

.paused-edit-btn svg {
  width: 10px;
  height: 10px;
}

@keyframes pulse-pause {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

.status-badge.configuring {
  background: rgba(99, 102, 241, 0.15);
  color: #6366f1;
  display: flex;
  align-items: center;
  gap: 6px;
}

.config-pulse {
  width: 8px;
  height: 8px;
  background: #6366f1;
  border-radius: 50%;
  animation: configPulse 1.5s ease-in-out infinite;
}

@keyframes configPulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(0.8); }
}

.status-badge.completed {
  background: rgba(16, 185, 129, 0.1);
  color: #10b981;
}

.status-badge.completed.rerunnable {
  cursor: pointer;
  transition: all 0.2s ease;
}

.status-badge.completed .completed-text {
  display: inline;
}

.status-badge.completed .rerun-text {
  display: none;
}

.status-badge.completed .rerun-icon {
  width: 12px;
  height: 12px;
  margin-left: 4px;
  opacity: 0;
  transition: opacity 0.2s ease;
}

.step-node:hover .status-badge.completed.rerunnable {
  background: rgba(99, 102, 241, 0.15);
  color: #6366f1;
}

.step-node:hover .status-badge.completed .completed-text {
  display: none;
}

.step-node:hover .status-badge.completed .rerun-text {
  display: inline;
}

.step-node:hover .status-badge.completed .rerun-icon {
  opacity: 1;
}

/* 文件一排显示样式 */
.output-files-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.output-file-item {
  position: relative;
  display: flex;
  align-items: center;
}

.output-file-link-mini {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: rgba(148, 163, 184, 0.08);
  border: 1px solid rgba(148, 163, 184, 0.15);
  border-radius: 6px;
  font-size: 11px;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s ease;
  text-decoration: none;
}

.output-file-link-mini:hover {
  background: rgba(var(--file-color-rgb, 99, 102, 241), 0.1);
  border-color: var(--file-color, #6366f1);
  color: var(--file-color, #6366f1);
}

.output-file-link-mini .file-icon {
  font-size: 12px;
}

.output-file-link-mini .file-name {
  max-width: 80px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.output-file-link-mini.current {
  background: rgba(16, 185, 129, 0.1);
  border-color: rgba(16, 185, 129, 0.3);
  color: #10b981;
}

.current-tag {
  font-size: 9px;
  padding: 1px 4px;
  background: #10b981;
  color: white;
  border-radius: 3px;
  margin-left: 2px;
}

.output-file-item.history .output-file-link-mini {
  opacity: 0.75;
}

.output-file-item.history:hover .output-file-link-mini {
  opacity: 1;
}

.file-delete-btn {
  position: absolute;
  top: -4px;
  right: -4px;
  width: 14px;
  height: 14px;
  padding: 0;
  border: none;
  background: #ef4444;
  color: white;
  border-radius: 50%;
  font-size: 10px;
  line-height: 1;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: center;
}

.output-file-item:hover .file-delete-btn {
  opacity: 1;
}

.file-delete-btn:hover {
  background: #dc2626;
}

/* 保存到便签按钮 */
.save-to-notes-btn {
  width: 20px;
  height: 20px;
  padding: 0;
  border: none;
  background: rgba(230, 200, 100, 0.2);
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
  opacity: 0;
  transition: all 0.15s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-left: 4px;
}

.output-file-item:hover .save-to-notes-btn {
  opacity: 1;
}

.save-to-notes-btn:hover {
  background: rgba(230, 180, 60, 0.35);
  transform: scale(1.1);
}

.history-text-mini {
  font-size: 10px;
  color: #94a3b8;
  padding: 3px 6px;
  background: rgba(148, 163, 184, 0.1);
  border-radius: 4px;
}

.step-output-text-mini {
  font-size: 11px;
  color: #64748b;
}

.status-badge.error {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}

.status-badge.missing {
  background: rgba(245, 158, 11, 0.1);
  color: #f59e0b;
}

/* Missing skill actions */
.step-missing-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.mini-action-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border: none;
  border-radius: 6px;
  font-size: 10px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.mini-action-btn svg {
  width: 12px;
  height: 12px;
}

.mini-action-btn.create-btn {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
}

.mini-action-btn.create-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(102, 126, 234, 0.4);
}

.mini-action-btn.upload-btn {
  background: #f3f4f6;
  color: #374151;
  border: 1px solid #e5e7eb;
}

.mini-action-btn.upload-btn:hover {
  background: #e5e7eb;
}

.spinner {
  width: 10px;
  height: 10px;
  border: 2px solid rgba(99, 102, 241, 0.2);
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 输出区域 */
.step-output-area {
  margin-top: 6px;
  margin-left: 32px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.step-output-text {
  display: block;
  padding: 8px 12px;
  background: rgba(16, 185, 129, 0.08);
  border-left: 2px solid #10b981;
  border-radius: 0 6px 6px 0;
  font-size: 11px;
  color: #059669;
}

/* 执行结果区域（友好展示） */
.step-result-area {
  margin-top: 10px;
  margin-left: 32px;
  background: linear-gradient(135deg, #fefce8 0%, #fef3c7 100%);
  border: 1px solid rgba(234, 179, 8, 0.3);
  border-radius: 12px;
  padding: 14px;
  max-width: 480px;
}

.step-result-area .result-section {
  margin-bottom: 12px;
}

.step-result-area .result-header,
.step-result-area .thinking-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

.step-result-area .result-icon,
.step-result-area .thinking-icon {
  font-size: 14px;
}

.step-result-area .result-title,
.step-result-area .thinking-title {
  font-size: 12px;
  font-weight: 600;
  color: #92400e;
}

.step-result-area .result-content,
.step-result-area .thinking-content {
  padding-left: 22px;
}

.step-result-area .result-text,
.step-result-area .thinking-text {
  margin: 0;
  font-size: 13px;
  line-height: 1.5;
  color: #78350f;
}

.step-result-area .thinking-section {
  padding-top: 10px;
  border-top: 1px dashed rgba(234, 179, 8, 0.4);
}

.step-result-area .execution-log {
  margin-top: 8px;
}

.step-result-area .execution-log summary {
  font-size: 10px;
  color: #00aa00;
  cursor: pointer;
  user-select: none;
  font-family: 'Cascadia Code', 'Fira Code', 'SF Mono', Monaco, Consolas, monospace;
}

.step-result-area .execution-log summary:hover {
  color: #33ff33;
}

.step-result-area .execution-log pre {
  margin: 6px 0 0 0;
  padding: 10px 12px;
  background: #0a0a0a;
  border-radius: 4px;
  border: 1px solid #1a3a1a;
  font-family: 'Cascadia Code', 'Fira Code', 'SF Mono', Monaco, Consolas, monospace;
  font-size: 10px;
  font-weight: 300;
  color: #33ff33;
  line-height: 1.4;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 150px;
  overflow-y: auto;
}

.step-result-area .execution-log pre::-webkit-scrollbar {
  width: 4px;
}

.step-result-area .execution-log pre::-webkit-scrollbar-track {
  background: #0a0a0a;
}

.step-result-area .execution-log pre::-webkit-scrollbar-thumb {
  background: #1a3a1a;
  border-radius: 2px;
}

.step-result-area .execution-log pre::-webkit-scrollbar-thumb:hover {
  background: #33ff33;
}

.step-result-area .result-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed rgba(234, 179, 8, 0.4);
}

.step-result-area .action-btn {
  padding: 6px 14px;
  border: none;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.step-result-area .action-btn.retry {
  background: #fbbf24;
  color: #78350f;
}

.step-result-area .action-btn.retry:hover {
  background: #f59e0b;
}

.step-result-area .action-btn.modify {
  background: white;
  color: #92400e;
  border: 1px solid rgba(234, 179, 8, 0.5);
}

.step-result-area .action-btn.modify:hover {
  background: #fffbeb;
  border-color: #f59e0b;
}

/* 输出文件链接 - 紧凑芯片风格 */
.output-file-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px 6px 8px;
  background: linear-gradient(135deg, #faf5ff 0%, #f3e8ff 100%);
  border: 1px solid #e9d5ff;
  border-radius: 20px;
  cursor: pointer;
  transition: all 0.2s ease;
  text-align: left;
}

.output-file-link:hover {
  background: linear-gradient(135deg, #f3e8ff 0%, #ede9fe 100%);
  border-color: #d8b4fe;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(139, 92, 246, 0.2);
}

.output-file-link .file-icon {
  width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%);
  border-radius: 50%;
  font-size: 12px;
  flex-shrink: 0;
}

.output-file-link .file-info {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.output-file-link .file-name {
  font-size: 12px;
  font-weight: 600;
  color: #6d28d9;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 140px;
}

.output-file-link .file-meta {
  font-size: 10px;
  color: #a78bfa;
  white-space: nowrap;
}

.output-file-link .file-arrow {
  width: 14px;
  height: 14px;
  color: #a78bfa;
  flex-shrink: 0;
  transition: all 0.2s ease;
}

.output-file-link:hover .file-arrow {
  color: #7c3aed;
  transform: translate(2px, -2px);
}

.pipeline-step.status-missing .step-node {
  background: rgba(245, 158, 11, 0.05);
  border-color: rgba(245, 158, 11, 0.3);
}

.pipeline-step.status-missing .step-number {
  background: #f59e0b;
  color: #fff;
}

.pipeline-step.status-missing .connector-line {
  background: #f59e0b;
}

/* Typing Indicator */
.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 4px 0;
}

.typing-indicator span {
  width: 6px;
  height: 6px;
  background: #6366f1;
  border-radius: 50%;
  animation: typing 1.4s infinite ease-in-out;
}

.typing-indicator span:nth-child(1) { animation-delay: 0s; }
.typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.4s; }

@keyframes typing {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
  30% { transform: translateY(-4px); opacity: 1; }
}

/* Input Area */
.chat-input {
  position: relative;
  padding: 14px 20px;
  background: #fff;
  border-top: 1px solid #e5e7eb;
}

.input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 4px 4px 4px 14px;
  transition: all 0.2s ease;
}

.input-wrapper:focus-within {
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
  background: #fff;
}

.input-wrapper textarea {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: #111827;
  font-family: inherit;
  font-size: 13px;
  line-height: 1.5;
  padding: 8px 0;
  resize: none;
  max-height: 100px;
}

.input-wrapper textarea::placeholder {
  color: #9ca3af;
}

.send-btn {
  width: 38px;
  height: 38px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border: none;
  border-radius: 10px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  transition: all 0.2s ease;
  flex-shrink: 0;
}

.send-btn:hover:not(:disabled) {
  transform: scale(1.05);
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.send-btn svg {
  width: 16px;
  height: 16px;
}

/* 停止按钮 */
.stop-btn {
  width: 38px;
  height: 38px;
  background: #ef4444;
  border: none;
  border-radius: 10px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  transition: all 0.2s ease;
  flex-shrink: 0;
  animation: pulse-stop 1.5s ease-in-out infinite;
}

.stop-btn:hover {
  background: #dc2626;
  transform: scale(1.05);
  box-shadow: 0 4px 12px rgba(239, 68, 68, 0.4);
}

.stop-btn svg {
  width: 14px;
  height: 14px;
}

@keyframes pulse-stop {
  0%, 100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4); }
  50% { box-shadow: 0 0 0 6px rgba(239, 68, 68, 0); }
}

.input-hint {
  margin-top: 8px;
  font-size: 11px;
  color: #9ca3af;
  text-align: center;
}

.processing-hint {
  color: #f59e0b;
  animation: blink 1s ease-in-out infinite;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

/* Continue Dialog */
.continue-dialog-overlay {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  backdrop-filter: blur(2px);
}

.continue-dialog {
  background: #fff;
  border-radius: 16px;
  padding: 24px;
  width: 90%;
  max-width: 320px;
  text-align: center;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.15);
}

.dialog-icon {
  font-size: 40px;
  margin-bottom: 12px;
}

.dialog-title {
  font-size: 16px;
  font-weight: 700;
  color: #111827;
  margin: 0 0 8px 0;
}

.dialog-desc {
  font-size: 13px;
  color: #6b7280;
  margin: 0 0 20px 0;
  line-height: 1.5;
}

.dialog-desc strong {
  color: #111827;
  font-family: monospace;
  background: #f3f4f6;
  padding: 2px 6px;
  border-radius: 4px;
}

.dialog-actions {
  display: flex;
  gap: 10px;
}

.dialog-btn {
  flex: 1;
  padding: 10px 16px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.dialog-btn.cancel {
  background: #f3f4f6;
  border: 1px solid #e5e7eb;
  color: #6b7280;
}

.dialog-btn.cancel:hover {
  background: #e5e7eb;
}

.dialog-btn.confirm {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border: none;
  color: #fff;
}

.dialog-btn.confirm:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
}

.dialog-btn.confirm.save {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
}

.dialog-btn.confirm.save:hover {
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.4);
}

.dialog-btn.confirm.save svg {
  width: 14px;
  height: 14px;
}

.dialog-btn.confirm.delete {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
}

.dialog-btn.confirm.delete:hover {
  box-shadow: 0 4px 12px rgba(239, 68, 68, 0.4);
}

.dialog-btn.confirm.delete svg {
  width: 14px;
  height: 14px;
}

/* Delete Dialog */
.delete-dialog {
  max-width: 320px;
}

/* Workflow Context Dialog */
.workflow-context-dialog {
  max-width: 420px;
}

.context-input-wrapper {
  margin: 16px 0;
  text-align: left;
}

.context-textarea {
  width: 100%;
  padding: 12px 14px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  font-size: 13px;
  color: #111827;
  font-family: inherit;
  resize: none;
  transition: all 0.2s ease;
  line-height: 1.5;
}

.context-textarea:focus {
  outline: none;
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
  background: #fff;
}

.context-textarea::placeholder {
  color: #9ca3af;
}

.input-hint {
  display: block;
  margin-top: 6px;
  font-size: 11px;
  color: #9ca3af;
  text-align: right;
}

/* Save Dialog Form */
.save-dialog {
  max-width: 360px;
}

.save-form {
  text-align: left;
  margin-bottom: 20px;
}

.form-label {
  display: block;
  font-size: 11px;
  font-weight: 600;
  color: #6b7280;
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.form-input,
.form-textarea {
  width: 100%;
  padding: 10px 12px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 13px;
  color: #111827;
  margin-bottom: 14px;
  transition: all 0.2s ease;
  font-family: inherit;
}

.form-input:focus,
.form-textarea:focus {
  outline: none;
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
  background: #fff;
}

.form-textarea {
  resize: none;
}

/* Dialog Transition */
.dialog-enter-active,
.dialog-leave-active {
  transition: all 0.25s ease;
}

.dialog-enter-from,
.dialog-leave-to {
  opacity: 0;
}

.dialog-enter-from .continue-dialog,
.dialog-leave-to .continue-dialog {
  transform: scale(0.9);
}

/* Header Action Button - 清空对话 */
.header-action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 6px 12px;
  background: rgba(255, 255, 255, 0.15);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 8px;
  color: rgba(255, 255, 255, 0.9);
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  margin-right: 10px;
}

.header-action-btn:hover {
  background: rgba(255, 255, 255, 0.25);
  border-color: rgba(255, 255, 255, 0.3);
  color: #fff;
}

.header-action-btn svg {
  width: 14px;
  height: 14px;
}

/* 上传按钮 - 输入区 */
.input-wrapper .upload-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: 8px;
  color: #9ca3af;
  cursor: pointer;
  transition: all 0.2s ease;
  flex-shrink: 0;
}

.input-wrapper .upload-btn:hover {
  background: #f3f4f6;
  color: #6366f1;
}

.input-wrapper .upload-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.input-wrapper .upload-btn svg {
  width: 20px;
  height: 20px;
}

/* 待发送的数据引用 */
.pending-refs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px 12px;
  background: #fffbeb;
  border-bottom: 1px solid #fde68a;
  border-radius: 12px 12px 0 0;
}

.pending-ref {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: #fff;
  border: 1px solid #fbbf24;
  border-radius: 12px;
  font-size: 12px;
  color: #92400e;
}

.pending-ref.folder {
  background: #fef3c7;
}

.ref-icon {
  font-size: 12px;
}

.ref-name {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ref-remove {
  background: none;
  border: none;
  color: #d97706;
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  padding: 0 2px;
}

.ref-remove:hover {
  color: #b45309;
}

/* 已上传文件预览区 */
.uploaded-files {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px 12px;
  background: #f8fafc;
  border-bottom: 1px solid #e5e7eb;
  border-radius: 12px 12px 0 0;
}

.pending-refs + .uploaded-files {
  border-radius: 0;
}

.uploaded-file {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  max-width: 200px;
  transition: all 0.2s ease;
}

.uploaded-file:hover {
  border-color: #c7d2fe;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.1);
}

.uploaded-file.uploading {
  border-color: #fbbf24;
  background: #fffbeb;
}

.uploaded-file.upload-error {
  border-color: #ef4444;
  background: #fef2f2;
}

.file-status {
  font-size: 10px;
}

.file-status.uploading {
  color: #d97706;
}

.file-status.success {
  color: #10b981;
}

.file-status.error {
  color: #ef4444;
}

.file-preview-img {
  width: 32px;
  height: 32px;
  object-fit: cover;
  border-radius: 4px;
  border: 1px solid #e5e7eb;
}

.file-preview-icon {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #eef2ff 0%, #e0e7ff 100%);
  border-radius: 4px;
  font-size: 16px;
}

.file-details {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.uploaded-file .file-name {
  font-size: 11px;
  font-weight: 500;
  color: #374151;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.file-size {
  font-size: 9px;
  color: #9ca3af;
}

.file-remove {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: 4px;
  color: #9ca3af;
  cursor: pointer;
  transition: all 0.15s ease;
  flex-shrink: 0;
}

.file-remove:hover {
  background: #fef2f2;
  color: #ef4444;
}

.file-remove svg {
  width: 12px;
  height: 12px;
}

/* 消息附件展示 */
.message-attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}

.attachment-item {
  border-radius: 8px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.2);
}

.attachment-img {
  max-width: 200px;
  max-height: 150px;
  object-fit: cover;
  display: block;
  border-radius: 8px;
}

.attachment-file {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: rgba(255, 255, 255, 0.1);
}

.attachment-icon {
  font-size: 20px;
}

.attachment-name {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.9);
  max-width: 150px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}


/* ==================== 右侧技能执行面板 ==================== */
.skill-side-panel {
  position: absolute;
  top: 0;
  right: 0;
  height: 100%;
  background: rgba(255, 255, 255, 0.98);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-left: 1px solid rgba(139, 92, 246, 0.15);
  box-shadow: -8px 0 32px rgba(139, 92, 246, 0.1);
  z-index: 100;
  display: flex;
  flex-direction: row;
}

/* 拖拽手柄 */
.panel-resize-handle {
  position: absolute;
  left: 0;
  top: 0;
  width: 4px;
  height: 100%;
  cursor: col-resize;
  background: transparent;
  transition: background 0.2s;
  z-index: 10;
}

.panel-resize-handle:hover,
.panel-resize-handle.is-resizing {
  background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%);
}

.panel-resize-handle::after {
  content: '';
  position: absolute;
  left: -4px;
  top: 0;
  width: 12px;
  height: 100%;
}

/* 浮动面板8方向拖拽手柄 */
.float-resize-handle {
  position: absolute;
  z-index: 20;
}

/* 边缘手柄 */
.float-resize-n {
  top: 0;
  left: 8px;
  right: 8px;
  height: 6px;
  cursor: ns-resize;
}

.float-resize-s {
  bottom: 0;
  left: 8px;
  right: 8px;
  height: 6px;
  cursor: ns-resize;
}

.float-resize-e {
  right: 0;
  top: 8px;
  bottom: 8px;
  width: 6px;
  cursor: ew-resize;
}

.float-resize-w {
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 6px;
  cursor: ew-resize;
}

/* 角落手柄 */
.float-resize-ne {
  top: 0;
  right: 0;
  width: 12px;
  height: 12px;
  cursor: nesw-resize;
}

.float-resize-nw {
  top: 0;
  left: 0;
  width: 12px;
  height: 12px;
  cursor: nwse-resize;
}

.float-resize-se {
  bottom: 0;
  right: 0;
  width: 12px;
  height: 12px;
  cursor: nwse-resize;
}

.float-resize-sw {
  bottom: 0;
  left: 0;
  width: 12px;
  height: 12px;
  cursor: nesw-resize;
}

.side-panel-inner {
  display: flex;
  flex-direction: column;
  flex: 1;
  height: 100%;
  overflow: hidden;
}

/* 浮动状态 */
.skill-side-panel.is-floating {
  border-radius: 12px;
  border: 1px solid rgba(139, 92, 246, 0.2);
  overflow: hidden;
}

.skill-side-panel.is-floating .side-panel-inner {
  border-radius: 12px;
}

/* 面板头部 */
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: linear-gradient(135deg, rgba(139, 92, 246, 0.08) 0%, rgba(124, 58, 237, 0.04) 100%);
  border-bottom: 1px solid rgba(139, 92, 246, 0.1);
}

.panel-header.is-draggable {
  cursor: move;
}

.panel-header.is-floating {
  border-radius: 12px 12px 0 0;
}

.panel-skill-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.panel-skill-avatar {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(145deg, #8b5cf6 0%, #7c3aed 100%);
  border-radius: 8px;
  font-size: 14px;
  box-shadow: 0 2px 8px rgba(139, 92, 246, 0.3);
}

.panel-skill-meta {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.panel-skill-name {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
  margin: 0;
}

.panel-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  font-weight: 500;
}

.panel-status.complete {
  color: #10b981;
}

.panel-status.complete svg {
  width: 14px;
  height: 14px;
}

.panel-status.processing {
  color: #8b5cf6;
}

.panel-status .pulse-dot {
  width: 6px;
  height: 6px;
  background: currentColor;
  border-radius: 50%;
  animation: pulse 1.5s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(0.8); }
}

/* 对话区域 */
.panel-chat-area {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

.panel-messages {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.panel-message {
  display: flex;
  gap: 10px;
  animation: panelMsgIn 0.3s ease-out;
}

@keyframes panelMsgIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.panel-message.is-user {
  flex-direction: row-reverse;
}

.panel-msg-avatar {
  width: 30px;
  height: 30px;
  border-radius: 10px;
  background: linear-gradient(145deg, #8b5cf6 0%, #7c3aed 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  flex-shrink: 0;
  box-shadow: 0 2px 6px rgba(139, 92, 246, 0.2);
}

.panel-msg-bubble {
  max-width: 85%;
  padding: 10px 14px;
  border-radius: 16px;
  font-size: 13px;
  line-height: 1.3;
  background: #f1f5f9;
  color: #334155;
  border-bottom-left-radius: 4px;
}

.panel-msg-bubble.user {
  background: linear-gradient(145deg, #8b5cf6 0%, #7c3aed 100%);
  color: #fff;
  border-bottom-left-radius: 16px;
  border-bottom-right-radius: 4px;
  box-shadow: 0 2px 8px rgba(139, 92, 246, 0.25);
}

.panel-bubble-text :deep(strong) {
  font-weight: 600;
}

.panel-bubble-text :deep(.bullet) {
  color: #8b5cf6;
  font-weight: bold;
}

.panel-msg-bubble.user .panel-bubble-text :deep(.bullet) {
  color: rgba(255, 255, 255, 0.8);
}

/* 打字指示器 */
.panel-typing {
  display: flex;
  gap: 4px;
  padding: 4px 0;
}

.panel-typing span {
  width: 5px;
  height: 5px;
  background: #94a3b8;
  border-radius: 50%;
  animation: typingBounce 1.4s ease-in-out infinite;
}

.panel-typing span:nth-child(2) { animation-delay: 0.15s; }
.panel-typing span:nth-child(3) { animation-delay: 0.3s; }

@keyframes typingBounce {
  0%, 60%, 100% { transform: translateY(0); }
  30% { transform: translateY(-5px); }
}

/* 系统消息 */
.panel-system-msg {
  width: 100%;
  display: flex;
  justify-content: center;
}

.panel-executing {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  background: rgba(139, 92, 246, 0.08);
  border-radius: 16px;
  font-size: 12px;
  color: #8b5cf6;
  font-weight: 500;
}

.spin-icon {
  width: 14px;
  height: 14px;
  animation: spin 1s linear infinite;
}

/* 底部输入区 */
.panel-footer {
  padding: 14px 16px;
  border-top: 1px solid #e5e7eb;
  background: #fff;
}

.panel-input-area {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* 面板输入框容器 - 与主聊天风格一致 */
.panel-input-row {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 4px 4px 4px 6px;
  transition: all 0.2s ease;
}

.panel-input-row:focus-within {
  border-color: #8b5cf6;
  box-shadow: 0 0 0 3px rgba(139, 92, 246, 0.1);
  background: #fff;
}

.panel-input-row textarea {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: #111827;
  font-family: inherit;
  font-size: 13px;
  line-height: 1.5;
  padding: 8px 0;
  resize: none;
  max-height: 100px;
}

.panel-input-row textarea::placeholder {
  color: #9ca3af;
}

.panel-send-btn {
  width: 38px;
  height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%);
  border: none;
  border-radius: 10px;
  cursor: pointer;
  color: #fff;
  transition: all 0.2s ease;
  flex-shrink: 0;
}

.panel-send-btn svg {
  width: 16px;
  height: 16px;
}

.panel-send-btn:hover:not(:disabled) {
  transform: scale(1.05);
  box-shadow: 0 4px 12px rgba(139, 92, 246, 0.4);
}

.panel-send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.panel-quick-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: 8px;
  color: #9ca3af;
  cursor: pointer;
  transition: all 0.2s ease;
  flex-shrink: 0;
}

.panel-quick-btn:hover {
  background: rgba(139, 92, 246, 0.1);
  color: #8b5cf6;
}

.panel-quick-btn svg {
  width: 18px;
  height: 18px;
}

/* 面板上传按钮 - 与主聊天风格一致 */
.panel-upload-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: 8px;
  color: #9ca3af;
  cursor: pointer;
  transition: all 0.2s ease;
  flex-shrink: 0;
}

.panel-upload-btn:hover:not(:disabled) {
  background: rgba(139, 92, 246, 0.1);
  color: #8b5cf6;
}

.panel-upload-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.panel-upload-btn svg {
  width: 20px;
  height: 20px;
}

/* 面板拖拽上传覆盖层 */
.panel-chat-area.is-drag-over {
  position: relative;
}

.panel-drop-overlay {
  position: absolute;
  inset: 0;
  background: rgba(139, 92, 246, 0.1);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
  border: 2px dashed #8b5cf6;
  border-radius: 8px;
  margin: 8px;
}

.panel-drop-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: #8b5cf6;
  font-size: 13px;
  font-weight: 500;
}

.panel-drop-hint svg {
  width: 32px;
  height: 32px;
}

/* 面板已上传文件预览 - 与主聊天风格一致 */
.panel-files-preview {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 10px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  margin-bottom: 8px;
}

.panel-file-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 12px;
  max-width: 180px;
  transition: all 0.2s ease;
}

.panel-file-item:hover {
  border-color: #d1d5db;
}

.panel-file-item.is-uploading {
  opacity: 0.6;
}

.panel-file-item.has-error {
  background: #fef2f2;
  border-color: #fecaca;
  color: #ef4444;
}

.panel-file-icon {
  font-size: 14px;
  flex-shrink: 0;
}

.panel-file-name {
  color: #374151;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}

.panel-file-remove {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: 50%;
  color: #9ca3af;
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.15s;
}

.panel-file-remove:hover {
  background: #fee2e2;
  color: #ef4444;
}

.panel-file-remove svg {
  width: 12px;
  height: 12px;
}

/* 完成状态 */
.panel-complete-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 8px 0;
}

.panel-complete-state .complete-icon {
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #10b981;
  animation: checkPop 0.4s ease;
}

.panel-complete-state .complete-icon svg {
  width: 44px;
  height: 44px;
}

@keyframes checkPop {
  0% { transform: scale(0); opacity: 0; }
  50% { transform: scale(1.2); }
  100% { transform: scale(1); opacity: 1; }
}

.panel-complete-state .complete-text {
  font-size: 13px;
  color: #64748b;
}

/* 确认区域 */
.panel-confirm-area {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.confirm-hint {
  font-size: 12px;
  color: #64748b;
  text-align: center;
}

.confirm-actions {
  display: flex;
  gap: 8px;
}

.confirm-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 10px 12px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  border: none;
}

.confirm-btn svg {
  width: 16px;
  height: 16px;
}

.confirm-btn.primary {
  background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%);
  color: #fff;
  flex: 1.5;
}

.confirm-btn.primary:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(139, 92, 246, 0.4);
}

.confirm-btn.secondary {
  background: #f1f5f9;
  color: #475569;
  border: 1px solid #e2e8f0;
}

.confirm-btn.secondary:hover {
  background: #e2e8f0;
  border-color: #cbd5e1;
}

.confirm-btn.cancel {
  background: transparent;
  color: #94a3b8;
  border: 1px dashed #e2e8f0;
  flex: 0.8;
}

.confirm-btn.cancel:hover {
  background: #fef2f2;
  color: #ef4444;
  border-color: #fecaca;
}

/* 面板滑入动画 */
.slide-panel-enter-active,
.slide-panel-leave-active {
  transition: all 0.3s ease;
}

.slide-panel-enter-from,
.slide-panel-leave-to {
  transform: translateX(100%);
  opacity: 0;
}

/* 状态切换动画 */
.status-fade-enter-active,
.status-fade-leave-active {
  transition: all 0.2s ease;
}

.status-fade-enter-from,
.status-fade-leave-to {
  opacity: 0;
  transform: translateX(-10px);
}

.msg-fade-enter-active {
  transition: all 0.3s ease;
}

.msg-fade-enter-from {
  opacity: 0;
  transform: translateY(10px);
}

/* 面板滚动条 */
.panel-chat-area::-webkit-scrollbar {
  width: 4px;
}

.panel-chat-area::-webkit-scrollbar-track {
  background: transparent;
}

.panel-chat-area::-webkit-scrollbar-thumb {
  background: rgba(139, 92, 246, 0.2);
  border-radius: 2px;
}

.panel-chat-area::-webkit-scrollbar-thumb:hover {
  background: rgba(139, 92, 246, 0.3);
}
</style>
