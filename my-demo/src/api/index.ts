// API Configuration and Services
import config from '@/config'

const API_BASE_URL = config.apiBaseUrl

// Generic fetch wrapper
async function request<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Request failed' }))
    throw new Error(error.detail || `HTTP error! status: ${response.status}`)
  }

  return response.json()
}

// ============ Common Types ============

export interface InteractionOption {
  value: string
  label: string
}

export interface SkillInteraction {
  id: string
  type: 'input' | 'select' | 'multiselect' | 'confirm' | 'upload' | 'form'
  label: string
  description?: string
  required: boolean
  timing: 'before' | 'during'
  depends_on?: string
  options?: InteractionOption[]
}

// 技能输出配置
export interface OutputConfig {
  enabled: boolean  // 是否生成输出文件
  preferred_type?: string  // 优先文件类型: png, pdf, xlsx, docx, txt, json, html, md 等
  filename_template?: string  // 文件名模板，支持 {skill_name}, {timestamp}, {uuid}
  description?: string  // 输出说明
}

// ============ Skills API ============

export interface Skill {
  id: string  // UUID
  group_id: string  // 版本组ID
  name: string
  description: string | null
  icon: string | null
  tags: string[] | null
  folder_path: string | null  // 技能文件夹路径
  entry_script: string | null  // 入口脚本
  interactions: SkillInteraction[] | null
  output_config: OutputConfig | null  // 输出文件配置
  author: string | null
  version: string | null
  status: 'active' | 'deprecated'  // 版本状态
  original_created_at: string  // 原始创建时间（用于排序）
  created_at: string
  updated_at: string
}

export interface SkillVersion {
  id: string
  version: string | null
  status: string
  created_at: string
}

export interface SkillCreate {
  name: string
  description?: string
  icon?: string
  tags?: string[]
  entry_script?: string
  interactions?: SkillInteraction[]
  output_config?: OutputConfig  // 输出文件配置
  author?: string
  version?: string
  code?: string  // 脚本代码，提供后自动创建文件夹
}

export interface SkillUpdate {
  name?: string
  description?: string
  icon?: string
  tags?: string[]
  entry_script?: string
  interactions?: SkillInteraction[]
  output_config?: OutputConfig  // 输出文件配置
  author?: string
  version?: string
  code?: string  // 更新脚本代码
  // 更新模式: overwrite=覆盖当前版本, new_version=创建新版本
  update_mode?: 'overwrite' | 'new_version'
}

export interface SkillUploadData {
  file: File  // ZIP 文件
  name: string
  description?: string
  icon?: string
  tags?: string[]
  entry_script?: string
  author?: string
  version?: string
}

export const skillsApi = {
  // Get all skills (with optional search)
  getAll: (search?: string) => {
    const params = search ? `?q=${encodeURIComponent(search)}` : ''
    return request<Skill[]>(`/skills${params}`)
  },

  // Get single skill
  getById: (id: string) => request<Skill>(`/skills/${id}`),

  // Get skill by name
  getByName: (name: string) => request<Skill>(`/skills/by-name/${encodeURIComponent(name)}`),

  // Create skill (without folder)
  create: (data: SkillCreate) =>
    request<Skill>('/skills', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // Preview ZIP content before upload (with AI analysis)
  previewUpload: async (file: File): Promise<{
    name: string
    description: string
    icon: string
    tags: string[]
    author: string
    version: string
    entry_script: string | null
    files: string[]
    ai_analysis?: {
      description?: string
      capabilities?: string[]
      input_types?: string[]
      output_types?: string[]
      tags?: string[]
      icon?: string
      complexity?: string
      error?: string
    }
  }> => {
    const formData = new FormData()
    formData.append('file', file)

    const response = await fetch(`${API_BASE_URL}/skills/upload/preview`, {
      method: 'POST',
      body: formData,
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Preview failed' }))
      throw new Error(error.detail || `HTTP error! status: ${response.status}`)
    }

    return response.json()
  },

  // Upload skill (with folder ZIP)
  upload: async (data: SkillUploadData): Promise<Skill> => {
    const formData = new FormData()
    formData.append('file', data.file)
    formData.append('name', data.name)
    if (data.description) formData.append('description', data.description)
    if (data.icon) formData.append('icon', data.icon)
    if (data.tags) formData.append('tags', JSON.stringify(data.tags))
    if (data.entry_script) formData.append('entry_script', data.entry_script)
    if (data.author) formData.append('author', data.author)
    if (data.version) formData.append('version', data.version)

    const response = await fetch(`${API_BASE_URL}/skills/upload`, {
      method: 'POST',
      body: formData,
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Upload failed' }))
      throw new Error(error.detail || `HTTP error! status: ${response.status}`)
    }

    return response.json()
  },

  // Update skill info
  update: (id: string, data: SkillUpdate) =>
    request<Skill>(`/skills/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  // Update skill folder
  updateFolder: async (id: string, file: File): Promise<Skill> => {
    const formData = new FormData()
    formData.append('file', file)

    const response = await fetch(`${API_BASE_URL}/skills/${id}/folder`, {
      method: 'PUT',
      body: formData,
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Upload failed' }))
      throw new Error(error.detail || `HTTP error! status: ${response.status}`)
    }

    return response.json()
  },

  // Delete skill
  delete: (id: string) =>
    request<void>(`/skills/${id}`, {
      method: 'DELETE',
    }),

  // Get skill files
  getFiles: (id: string) =>
    request<{ files: { name: string; path: string; size: number }[] }>(`/skills/${id}/files`),

  // Get skill file content
  getFileContent: (id: string, filePath: string) =>
    request<{ content: string | null; binary?: boolean; size?: number }>(`/skills/${id}/file/${filePath}`),

  // ============ 临时技能 API ============

  // Create temporary skill (for testing)
  createTemp: (data: SkillCreate) =>
    request<TempSkillResponse>('/skills/temp', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // Get temporary skill
  getTemp: (tempId: string) =>
    request<TempSkillResponse>(`/skills/temp/${tempId}`),

  // Finalize temporary skill (move to permanent)
  finalizeTemp: (tempId: string) =>
    request<Skill>(`/skills/temp/${tempId}/finalize`, {
      method: 'POST',
    }),

  // Delete temporary skill
  deleteTemp: (tempId: string) =>
    request<void>(`/skills/temp/${tempId}`, {
      method: 'DELETE',
    }),

  // ============ 版本管理 API ============

  // Get all versions of a skill
  getVersions: (id: string) =>
    request<SkillVersion[]>(`/skills/${id}/versions`),

  // Rollback to a specific version
  rollback: (id: string, targetVersionId: string) =>
    request<Skill>(`/skills/${id}/rollback/${targetVersionId}`, {
      method: 'POST',
    }),
}

// Temporary skill response
export interface TempSkillResponse {
  temp_id: string
  name: string
  description: string | null
  icon: string | null
  tags: string[] | null
  folder_path: string
  entry_script: string | null
  is_temp?: boolean
}

// ============ Agent API ============

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ChatRequest {
  message: string
  history?: ChatMessage[]
  skill_ids?: string[]  // UUID array
}

export interface ChatResponse {
  message: string
  skill_suggestions?: any[]
}

export interface PlanRequest {
  user_input: string
  available_skills?: string[]
}

export interface SkillPlanItem {
  skill_id: string
  skill_name: string
  reason: string
  params?: Record<string, any>
}

export interface PlanResponse {
  plan: SkillPlanItem[]
  explanation: string
}

export interface ExecuteRequest {
  skill_id: string  // UUID
  script_name?: string
  params?: Record<string, any>
}

export interface OutputFile {
  name: string
  type: string
  url: string
  size?: string
}

export interface ExecuteResponse {
  success: boolean
  result?: any
  error?: string
  output?: string
  output_file?: OutputFile
}

export interface UploadResponse {
  success: boolean
  filename: string
  original_name: string
  path: string
  url: string
  size: number
  type: string
}

export const agentApi = {
  // Chat (non-streaming)
  chat: (data: ChatRequest) =>
    request<ChatResponse>('/agent/chat', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // Chat (streaming via SSE)
  chatStream: async function* (
    data: ChatRequest,
    signal?: AbortSignal
  ): AsyncGenerator<string> {
    const url = `${API_BASE_URL}/agent/chat/stream`
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data),
      signal,
    })

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }

    const reader = response.body?.getReader()
    if (!reader) {
      throw new Error('No response body')
    }

    const decoder = new TextDecoder()
    let buffer = ''

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const jsonData = line.slice(6)
            if (jsonData === '[DONE]') {
              return
            }
            try {
              const parsed = JSON.parse(jsonData)
              if (parsed.content) {
                yield parsed.content
              }
              if (parsed.error) {
                throw new Error(parsed.error)
              }
            } catch (e) {
              // Ignore parse errors for malformed chunks
            }
          }
        }
      }
    } finally {
      reader.releaseLock()
    }
  },

  // Plan skills
  plan: (data: PlanRequest) =>
    request<PlanResponse>('/agent/plan', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // Execute skill
  execute: (data: ExecuteRequest) =>
    request<ExecuteResponse>('/agent/execute', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // Execute temporary skill (for testing)
  executeTemp: (data: ExecuteRequest) =>
    request<ExecuteResponse>('/agent/execute-temp', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // Upload file for skill processing
  upload: async (file: File): Promise<UploadResponse> => {
    const formData = new FormData()
    formData.append('file', file)

    const response = await fetch(`${API_BASE_URL}/agent/upload`, {
      method: 'POST',
      body: formData,
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Upload failed' }))
      throw new Error(error.detail || `HTTP error! status: ${response.status}`)
    }

    return response.json()
  },
}

// ============ Workflows API ============

export interface WorkflowNode {
  id: string
  type: 'skill' | 'workflow'
  name: string
  icon: string
  description: string
  config?: Record<string, any>
  position: { x: number; y: number }
}

export interface WorkflowEdge {
  id: string
  from: string
  to: string
}

export interface Workflow {
  id: string
  name: string
  description: string | null
  icon: string | null
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  created_at: string
  updated_at: string
}

export interface WorkflowCreate {
  id: string
  name: string
  description?: string
  icon?: string
  nodes?: WorkflowNode[]
  edges?: WorkflowEdge[]
}

export interface WorkflowUpdate {
  name?: string
  description?: string
  icon?: string
  nodes?: WorkflowNode[]
  edges?: WorkflowEdge[]
}

export const workflowsApi = {
  // Get all workflows (with optional search)
  getAll: (search?: string) => {
    const params = search ? `?q=${encodeURIComponent(search)}` : ''
    return request<Workflow[]>(`/workflows${params}`)
  },

  // Get single workflow
  getById: (id: string) => request<Workflow>(`/workflows/${id}`),

  // Create workflow
  create: (data: WorkflowCreate) =>
    request<Workflow>('/workflows', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // Update workflow
  update: (id: string, data: WorkflowUpdate) =>
    request<Workflow>(`/workflows/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  // Delete workflow
  delete: (id: string) =>
    request<void>(`/workflows/${id}`, {
      method: 'DELETE',
    }),
}

// ============ Favorites API ============

export interface FavoriteListResponse {
  skills: string[]  // 收藏的技能ID列表
  workflows: string[]  // 收藏的子流程ID列表
}

// 获取或生成用户ID（匿名用户使用本地存储的ID）
const getUserId = (): string => {
  const key = 'user-anonymous-id'
  let userId = localStorage.getItem(key)
  if (!userId) {
    userId = `anon-${Date.now()}-${Math.random().toString(36).slice(2)}`
    localStorage.setItem(key, userId)
  }
  return userId
}

export const favoritesApi = {
  // 获取收藏列表
  getAll: () =>
    request<FavoriteListResponse>('/favorites', {
      headers: { 'X-User-ID': getUserId() }
    }),

  // 切换收藏状态
  toggle: (itemType: 'skill' | 'workflow', itemId: string) =>
    request<{ favorited: boolean; item_id: string }>('/favorites/toggle', {
      method: 'POST',
      headers: { 'X-User-ID': getUserId() },
      body: JSON.stringify({ item_type: itemType, item_id: itemId })
    }),

  // 添加收藏
  add: (itemType: 'skill' | 'workflow', itemId: string) =>
    request<any>('/favorites', {
      method: 'POST',
      headers: { 'X-User-ID': getUserId() },
      body: JSON.stringify({ item_type: itemType, item_id: itemId })
    }),

  // 取消收藏
  remove: (itemType: 'skill' | 'workflow', itemId: string) =>
    request<any>('/favorites', {
      method: 'DELETE',
      headers: { 'X-User-ID': getUserId() },
      body: JSON.stringify({ item_type: itemType, item_id: itemId })
    }),
}

// ============ Executions API ============

export interface InteractionRequest {
  interaction_id: string
  skill_id?: string
  skill_name: string
  step_index: number
  type: string
  label: string
  description?: string
  required: boolean
  options?: InteractionOption[]
  context?: Record<string, any>
}

export interface CompletedStep {
  step_index: number
  skill_name: string
  icon?: string
  status: 'completed' | 'skipped'
  result?: any
  output?: string
}

export interface ExecutionStatusResponse {
  execution_id: string
  workflow_id: string
  workflow_name?: string
  status: 'pending' | 'running' | 'paused' | 'completed' | 'failed'
  current_step: number
  total_steps: number
  completed_steps: CompletedStep[]
  pending_interaction?: InteractionRequest
  error?: string
  created_at?: string
  updated_at?: string
}

export interface WorkflowStepInfo {
  step_index: number
  skill_name: string
  icon?: string
  interactions: SkillInteraction[]
}

export interface WorkflowPreCheck {
  workflow_id: string
  workflow_name: string
  total_steps: number
  steps: WorkflowStepInfo[]
  before_interactions: InteractionRequest[]
  has_during_interactions: boolean
}

export interface StartExecutionRequest {
  pre_inputs?: Record<string, any>
}

export interface InteractionResponseData {
  interaction_id: string
  value: any
}

export const executionsApi = {
  // 预检查工作流
  precheck: (workflowId: string) =>
    request<WorkflowPreCheck>(`/executions/workflow/${workflowId}/precheck`),

  // 启动工作流执行
  start: (workflowId: string, preInputs?: Record<string, any>) =>
    request<ExecutionStatusResponse>(`/executions/workflow/${workflowId}/start`, {
      method: 'POST',
      body: JSON.stringify({ pre_inputs: preInputs }),
    }),

  // 获取执行状态
  getStatus: (executionId: string) =>
    request<ExecutionStatusResponse>(`/executions/${executionId}`),

  // 提交交互响应
  submitInteraction: (executionId: string, response: InteractionResponseData) =>
    request<ExecutionStatusResponse>(`/executions/${executionId}/interact`, {
      method: 'POST',
      body: JSON.stringify(response),
    }),

  // 取消执行
  cancel: (executionId: string) =>
    request<{ message: string }>(`/executions/${executionId}/cancel`, {
      method: 'POST',
    }),

  // 列出执行记录
  list: (workflowId?: string, limit: number = 50) => {
    const params = new URLSearchParams()
    if (workflowId) params.append('workflow_id', workflowId)
    params.append('limit', limit.toString())
    return request<ExecutionStatusResponse[]>(`/executions?${params}`)
  },
}

// Export all APIs
export default {
  skills: skillsApi,
  agent: agentApi,
  workflows: workflowsApi,
  executions: executionsApi,
  favorites: favoritesApi,
}
