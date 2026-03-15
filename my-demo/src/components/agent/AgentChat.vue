<script setup lang="ts">
import { ref, nextTick, watch, computed, onUnmounted } from 'vue'
import { agentApi, type ChatMessage } from '@/api'

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
  status: 'pending' | 'running' | 'completed' | 'error' | 'missing'
  output?: string
  userInput?: string  // 用户输入的参数/指令
  outputFile?: OutputFile  // 输出文件
  errorDetails?: {  // 执行结果详情（用于分析和建议）
    error?: string
    output?: string
  }
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

  // 清空上传的文件
  uploadedFiles.value = []

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
const executingStepInfo = ref<{ messageId: number; stepId: number } | null>(null)

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
const closeSkillExecution = () => {
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
}

// 发送面板消息 - 多轮对话
const sendSkillPanelMessage = async () => {
  if (!skillPanelInput.value.trim() || skillPanelProcessing.value) return

  const userMessage = skillPanelInput.value.trim()
  skillPanelInput.value = ''
  skillPanelWaitingConfirm.value = false

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
  closeSkillExecution()
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

// 直接执行（使用默认配置）
const quickExecuteSkillPanel = () => {
  skillPanelMessages.value.push({
    id: Date.now(),
    role: 'user',
    content: '使用默认配置',
    timestamp: new Date()
  })
  skillPanelMessages.value.push({
    id: Date.now() + 1,
    role: 'assistant',
    content: `好的，将使用默认配置执行「${executionContext.value || executingSkill.value?.name}」`,
    timestamp: new Date()
  })
  scrollSkillPanelToBottom()

  setTimeout(() => {
    executeSkillPanel()
  }, 500)
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
  const stepInfo = executingStepInfo.value
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
            const filePaths = getContextFilePaths()
            // 优先使用交互面板中的 context，其次使用用户查询，最后使用技能描述
            const contextValue = result.params?.context || lastUserQuery.value || step.description || ''
            const params = {
              ...(result.params || {}),
              context: contextValue,
              skillDescription: step.description,
              ...(filePaths.length > 0 ? {
                file_path: filePaths[0],
                file_paths: filePaths
              } : {})
            }

            console.log(`[handleSkillComplete] Executing skill "${step.skillName}" with context:`, contextValue)

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
      fromAdj.push(e.to)
    }
    const toDegree = inDegree[e.to]
    if (toDegree !== undefined) {
      inDegree[e.to] = toDegree + 1
    }
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

  // 如果流程正在运行，不允许点击
  if (isPipelineRunning(messageId)) return

  // 找到步骤索引
  const startIndex = msg.skillPlan.findIndex(s => s.id === stepId)
  if (startIndex === -1) return

  const step = msg.skillPlan[startIndex]

  // 重置该步骤及之后所有步骤的状态为 pending（这样配置完成后会从这里开始执行）
  for (let i = startIndex; i < msg.skillPlan.length; i++) {
    msg.skillPlan[i].status = 'pending'
    msg.skillPlan[i].output = undefined
    msg.skillPlan[i].outputFile = undefined
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
      fromAdj.push(e.to)
    }
    const toDegree = inDegree[e.to]
    if (toDegree !== undefined) {
      inDegree[e.to] = toDegree + 1
    }
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
        const filePaths = getContextFilePaths()

        // 安全解析 userInput
        let baseParams: Record<string, any> = {}
        if (step.userInput) {
          try {
            baseParams = JSON.parse(step.userInput)
          } catch (e) {
            console.warn(`[Skill Seq] Failed to parse userInput for "${step.skillName}":`, e)
          }
        }

        // 获取上下文：优先 userInput 里的 context，其次用户查询，最后技能描述
        const contextValue = baseParams.context || lastUserQuery.value || step.description || ''

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
}

// 按拓扑层级并行执行技能
const executeSkillsParallel = async (messageId: number) => {
  const msg = messages.value.find(m => m.id === messageId)
  if (!msg?.skillPlan || !msg.pipelineEdges) {
    // 没有边信息，回退到顺序执行
    if (msg?.skillPlan) {
      await executeSkills(messageId, msg.skillPlan)
    }
    return
  }

  const steps = msg.skillPlan
  const edges = msg.pipelineEdges

  // 如果没有nodeId，回退到顺序执行
  if (!steps[0]?.nodeId) {
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
      fromAdj.push(e.to)
    }
    const toDegree = inDegree[e.to]
    if (toDegree !== undefined) {
      inDegree[e.to] = toDegree + 1
    }
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
          currentBatch.push(step)
          toProcess.push(nodeId)
        }
      }
    })

    if (currentBatch.length === 0) {
      // 防止死循环
      break
    }

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

          // 安全解析 userInput
          let baseParams: Record<string, any> = {}
          if (step.userInput) {
            try {
              baseParams = JSON.parse(step.userInput)
            } catch (e) {
              console.warn(`[Skill Parallel] Failed to parse userInput for "${step.skillName}":`, e)
            }
          }

          // 获取上下文：优先 baseParams.context，其次用户查询，最后技能描述
          const contextValue = baseParams.context || lastUserQuery.value || step.description || ''
          console.log(`[Skill Parallel] Context for "${step.skillName}":`, contextValue)

          const params = {
            ...baseParams,
            // 添加用户原始查询作为上下文
            context: contextValue,
            skillDescription: step.description,
            // 如果有上传的文件，传递文件路径
            ...(filePaths.length > 0 ? {
              file_path: filePaths[0],  // 主文件
              file_paths: filePaths     // 所有文件
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

    // 移除已完成的节点，更新入度
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

// 展开工作流节点（递归处理子流程）
const expandWorkflowNodes = (nodes: any[], edges: any[] = []): { steps: SkillStep[], edges: PipelineEdge[] } => {
  const steps: SkillStep[] = []
  const resultEdges: PipelineEdge[] = []
  let stepId = 1

  const processNode = (node: any) => {
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

  return { steps, edges: resultEdges }
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
  const { steps: skillPlan, edges: pipelineEdges } = expandWorkflowNodes(workflow.nodes, workflow.edges || [])

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
  setTimeout(() => {
    const agentMessage: Message = {
      id: Date.now(),
      type: 'agent',
      content: context
        ? `好的，我来帮你处理：「${context}」\n\n将使用工作流「${workflow.name}」，包含 ${workflow.nodes.length} 个步骤：`
        : `好的，开始执行工作流「${workflow.name}」。这个流程包含 ${workflow.nodes.length} 个步骤：`,
      timestamp: new Date(),
      skillPlan,
      pipelineEdges
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
  if ((!inputText.value.trim() && uploadedFiles.value.length === 0) || isProcessing.value) return

  // 收集附件信息（包含服务器路径）
  const attachments: MessageAttachment[] = uploadedFiles.value
    .filter(f => !f.uploading && !f.uploadError)  // 只包含上传成功的文件
    .map(f => ({
      id: f.id,
      name: f.name,
      type: f.type,
      size: f.size,
      url: f.url,
      serverPath: f.serverPath
    }))

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
                        'clickable': !isPipelineRunning(message.id) && step.status !== 'running',
                        'disabled': isPipelineRunning(message.id)
                      }"
                      @click="!isPipelineRunning(message.id) && step.status !== 'running' && openSkillForRerun(message.id, step.id)"
                      :title="isPipelineRunning(message.id) ? '流程运行中，请等待完成' : '点击配置并重新执行'"
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
                        <!-- 等待中 -->
                        <span v-if="step.status === 'pending'" class="status-badge pending">
                          等待中
                        </span>
                        <span
                          v-else-if="step.status === 'running'"
                          class="status-badge running pausable"
                          :class="{ 'is-paused': isPaused }"
                          @click.stop="togglePauseExecution(message.id)"
                          :title="isPaused ? '点击继续执行' : '点击暂停执行'"
                        >
                          <span v-if="isPaused" class="pause-icon">▶</span>
                          <span v-else class="spinner"></span>
                          {{ isPaused ? '已暂停' : '执行中' }}
                        </span>
                        <span v-else-if="step.status === 'completed'" class="status-badge completed">已完成</span>
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
                    <!-- 输出信息 -->
                    <div v-if="step.status === 'completed'" class="step-output-area">
                      <span v-if="step.output && !step.outputFile" class="step-output-text">
                        {{ step.output }}
                      </span>
                      <!-- 输出文件链接 -->
                      <button
                        v-if="step.outputFile"
                        class="output-file-link"
                        :style="{ '--file-color': getFileTypeInfo(step.outputFile.type).color }"
                        @click.stop="openOutputFile(step.outputFile)"
                      >
                        <span class="file-icon">{{ getFileTypeInfo(step.outputFile.type).icon }}</span>
                        <span class="file-info">
                          <span class="file-name">{{ step.outputFile.name }}</span>
                          <span class="file-meta">
                            {{ getFileTypeInfo(step.outputFile.type).label }}
                            <span v-if="step.outputFile.size"> · {{ step.outputFile.size }}</span>
                          </span>
                        </span>
                        <svg class="file-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
                          <polyline points="15 3 21 3 21 9"/>
                          <line x1="10" y1="14" x2="21" y2="3"/>
                        </svg>
                      </button>
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
              placeholder="描述你想完成的任务，或拖拽文件到这里..."
              @keydown.enter.exact.prevent="sendMessage"
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
              :disabled="!inputText.trim() && uploadedFiles.length === 0"
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

    <!-- 右侧技能执行面板 -->
    <Transition name="slide-panel">
      <div v-if="showSkillExecution && executingSkill" class="skill-side-panel">
        <div class="side-panel-inner">
          <!-- 面板头部 -->
          <header class="panel-header">
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
            <button class="panel-close-btn" @click="closeSkillExecution" title="关闭">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M18 6L6 18M6 6l12 12"/>
              </svg>
            </button>
          </header>

          <!-- 对话区域 -->
          <main class="panel-chat-area" ref="skillPanelChatRef">
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
                <div class="panel-input-row">
                  <textarea
                    ref="skillPanelInputRef"
                    v-model="skillPanelInput"
                    placeholder="输入你的需求..."
                    @keydown.enter.exact.prevent="sendSkillPanelMessage"
                    :disabled="skillPanelProcessing"
                    rows="1"
                  ></textarea>
                  <button
                    class="panel-send-btn"
                    @click="sendSkillPanelMessage"
                    :disabled="!skillPanelInput.trim() || skillPanelProcessing"
                  >
                    <svg viewBox="0 0 24 24" fill="none">
                      <path d="M5 12h14M12 5l7 7-7 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                  </button>
                </div>
                <button
                  v-if="!skillPanelProcessing && skillPanelMessages.length <= 1"
                  class="panel-quick-btn"
                  @click="quickExecuteSkillPanel"
                >
                  <svg viewBox="0 0 16 16" fill="none">
                    <path d="M8.5 1L3 9h4.5l-.5 6 5.5-8H8l.5-6z" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
                  </svg>
                  跳过配置，直接执行
                </button>
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
  line-height: 1.5;
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
  margin: 0 0 8px 0;
  font-size: 13px;
  line-height: 1.6;
}

/* Markdown 样式 */
.markdown-content {
  font-size: 13px;
  line-height: 1.7;
  word-wrap: break-word;
}

.markdown-content h2 {
  font-size: 16px;
  font-weight: 700;
  margin: 16px 0 8px 0;
  color: #1e293b;
}

.markdown-content h3 {
  font-size: 14px;
  font-weight: 600;
  margin: 12px 0 6px 0;
  color: #334155;
}

.markdown-content h4 {
  font-size: 13px;
  font-weight: 600;
  margin: 10px 0 4px 0;
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
  padding: 12px 16px;
  border-radius: 8px;
  margin: 10px 0;
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
  margin: 4px 0;
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
  left: 0;
  top: 100%;
  margin-top: 4px;
  padding: 6px 10px;
  background: #1e293b;
  color: #f1f5f9;
  font-size: 11px;
  line-height: 1.4;
  border-radius: 6px;
  max-width: 200px;
  width: max-content;
  z-index: 100;
  opacity: 0;
  visibility: hidden;
  transform: translateY(-4px);
  transition: all 0.15s ease;
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  pointer-events: none;
}

.step-tooltip::before {
  content: '';
  position: absolute;
  top: -4px;
  left: 12px;
  border: 4px solid transparent;
  border-bottom-color: #1e293b;
  border-top: none;
}

.step-desc-wrapper:hover .step-tooltip {
  opacity: 1;
  visibility: visible;
  transform: translateY(0);
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

@keyframes pulse-pause {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

.status-badge.completed {
  background: rgba(16, 185, 129, 0.1);
  color: #10b981;
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
  font-size: 11px;
  color: #a16207;
  cursor: pointer;
  user-select: none;
}

.step-result-area .execution-log summary:hover {
  color: #854d0e;
}

.step-result-area .execution-log pre {
  margin: 6px 0 0 0;
  padding: 8px 10px;
  background: rgba(255, 255, 255, 0.6);
  border-radius: 6px;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 10px;
  color: #78350f;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 120px;
  overflow-y: auto;
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
  width: 380px;
  height: 100%;
  background: rgba(255, 255, 255, 0.98);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-left: 1px solid rgba(139, 92, 246, 0.15);
  box-shadow: -8px 0 32px rgba(139, 92, 246, 0.1);
  z-index: 100;
  display: flex;
  flex-direction: column;
}

.side-panel-inner {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

/* 面板头部 */
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  background: linear-gradient(135deg, rgba(139, 92, 246, 0.08) 0%, rgba(124, 58, 237, 0.04) 100%);
  border-bottom: 1px solid rgba(139, 92, 246, 0.1);
}

.panel-skill-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.panel-skill-avatar {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(145deg, #8b5cf6 0%, #7c3aed 100%);
  border-radius: 12px;
  font-size: 18px;
  box-shadow: 0 4px 12px rgba(139, 92, 246, 0.3);
}

.panel-skill-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.panel-skill-name {
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
  margin: 0;
}

.panel-status {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
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

.panel-close-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  color: #94a3b8;
  transition: all 0.2s ease;
}

.panel-close-btn:hover {
  background: rgba(0, 0, 0, 0.05);
  color: #64748b;
}

.panel-close-btn svg {
  width: 18px;
  height: 18px;
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
  line-height: 1.5;
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
  padding: 14px 20px 18px;
  border-top: 1px solid rgba(0, 0, 0, 0.05);
  background: rgba(248, 250, 252, 0.6);
}

.panel-input-area {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.panel-input-row {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}

.panel-input-row textarea {
  flex: 1;
  padding: 10px 14px;
  border: 1px solid rgba(139, 92, 246, 0.2);
  border-radius: 12px;
  font-size: 13px;
  font-family: inherit;
  resize: none;
  outline: none;
  background: #fff;
  transition: all 0.2s ease;
  min-height: 40px;
  max-height: 80px;
}

.panel-input-row textarea:focus {
  border-color: rgba(139, 92, 246, 0.5);
  box-shadow: 0 0 0 3px rgba(139, 92, 246, 0.1);
}

.panel-input-row textarea::placeholder {
  color: #94a3b8;
}

.panel-send-btn {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(145deg, #8b5cf6 0%, #7c3aed 100%);
  border: none;
  border-radius: 12px;
  cursor: pointer;
  color: #fff;
  transition: all 0.2s ease;
  flex-shrink: 0;
}

.panel-send-btn svg {
  width: 18px;
  height: 18px;
}

.panel-send-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(139, 92, 246, 0.35);
}

.panel-send-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.panel-quick-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 14px;
  background: transparent;
  border: 1px dashed rgba(139, 92, 246, 0.3);
  border-radius: 8px;
  font-size: 12px;
  color: #8b5cf6;
  cursor: pointer;
  transition: all 0.2s ease;
}

.panel-quick-btn:hover {
  background: rgba(139, 92, 246, 0.05);
  border-color: rgba(139, 92, 246, 0.5);
}

.panel-quick-btn svg {
  width: 14px;
  height: 14px;
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
