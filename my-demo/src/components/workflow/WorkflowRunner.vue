<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import {
  executionsApi,
  type ExecutionStatusResponse,
  type InteractionRequest,
  type WorkflowPreCheck,
  type CompletedStep
} from '@/api'

const props = defineProps<{
  workflowId: string
  workflowName?: string
}>()

const emit = defineEmits<{
  close: []
  completed: [result: ExecutionStatusResponse]
}>()

// 状态
const loading = ref(false)
const error = ref<string | null>(null)
const phase = ref<'precheck' | 'precollect' | 'running' | 'paused' | 'completed' | 'failed'>('precheck')

// 预检查结果
const precheck = ref<WorkflowPreCheck | null>(null)
const preInputs = ref<Record<string, any>>({})

// 执行状态
const execution = ref<ExecutionStatusResponse | null>(null)
const interactionValue = ref<any>(null)

// 计算属性
const progressPercent = computed(() => {
  if (!execution.value) return 0
  return Math.round((execution.value.current_step / execution.value.total_steps) * 100)
})

const currentInteraction = computed(() => execution.value?.pending_interaction)

// API base URL
const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

// 从 step.result 中提取 _output_file
const getOutputFile = (step: CompletedStep) => {
  if (!step.result) return null
  // result 可能是对象，包含 _output_file
  if (typeof step.result === 'object' && step.result._output_file) {
    return step.result._output_file
  }
  return null
}

// 获取完整的文件下载 URL
const getOutputFileUrl = (step: CompletedStep) => {
  const outputFile = getOutputFile(step)
  if (!outputFile?.url) return ''
  // 如果是相对路径，加上 API base URL
  if (outputFile.url.startsWith('/')) {
    return `${API_BASE}${outputFile.url}`
  }
  return outputFile.url
}

// 初始化：预检查工作流
const initPrecheck = async () => {
  loading.value = true
  error.value = null

  try {
    precheck.value = await executionsApi.precheck(props.workflowId)

    if (precheck.value.before_interactions.length > 0) {
      // 有需要预收集的交互
      phase.value = 'precollect'
      // 初始化默认值
      precheck.value.before_interactions.forEach(inter => {
        if (inter.type === 'confirm') {
          preInputs.value[inter.interaction_id] = false
        }
      })
    } else {
      // 无需预收集，直接开始
      await startExecution()
    }
  } catch (e: any) {
    error.value = e.message
    phase.value = 'failed'
  } finally {
    loading.value = false
  }
}

// 开始执行
const startExecution = async () => {
  loading.value = true
  error.value = null
  phase.value = 'running'

  try {
    execution.value = await executionsApi.start(props.workflowId, preInputs.value)
    updatePhaseFromStatus()
  } catch (e: any) {
    error.value = e.message
    phase.value = 'failed'
  } finally {
    loading.value = false
  }
}

// 提交交互响应
const submitInteraction = async () => {
  if (!execution.value || !currentInteraction.value) return

  loading.value = true
  error.value = null

  try {
    execution.value = await executionsApi.submitInteraction(execution.value.execution_id, {
      interaction_id: currentInteraction.value.interaction_id,
      value: interactionValue.value
    })
    interactionValue.value = null
    updatePhaseFromStatus()
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

// 取消执行
const cancelExecution = async () => {
  if (!execution.value) return

  try {
    await executionsApi.cancel(execution.value.execution_id)
    phase.value = 'failed'
    error.value = '用户取消'
  } catch (e: any) {
    error.value = e.message
  }
}

// 根据执行状态更新阶段
const updatePhaseFromStatus = () => {
  if (!execution.value) return

  switch (execution.value.status) {
    case 'running':
      phase.value = 'running'
      // 轮询状态
      pollStatus()
      break
    case 'paused':
      phase.value = 'paused'
      break
    case 'completed':
      phase.value = 'completed'
      emit('completed', execution.value)
      break
    case 'failed':
      phase.value = 'failed'
      error.value = execution.value.error || '执行失败'
      break
  }
}

// 轮询执行状态
let pollTimer: number | null = null
const pollStatus = async () => {
  if (pollTimer) clearTimeout(pollTimer)

  if (!execution.value || phase.value !== 'running') return

  try {
    execution.value = await executionsApi.getStatus(execution.value.execution_id)
    updatePhaseFromStatus()

    // 继续轮询
    if (phase.value === 'running') {
      pollTimer = window.setTimeout(pollStatus, 1000)
    }
  } catch (e: any) {
    error.value = e.message
  }
}

// 重试
const retry = () => {
  error.value = null
  preInputs.value = {}
  execution.value = null
  initPrecheck()
}

// 组件挂载时开始预检查
initPrecheck()

// 清理
watch(() => props.workflowId, () => {
  if (pollTimer) clearTimeout(pollTimer)
  retry()
})
</script>

<template>
  <div class="workflow-runner">
    <!-- 头部 -->
    <div class="runner-header">
      <h3>{{ workflowName || precheck?.workflow_name || '工作流执行' }}</h3>
      <button class="close-btn" @click="emit('close')">×</button>
    </div>

    <!-- 进度条 -->
    <div v-if="execution" class="progress-section">
      <div class="progress-bar">
        <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
      </div>
      <div class="progress-text">
        {{ execution.current_step }} / {{ execution.total_steps }} 步骤
      </div>
    </div>

    <!-- 预收集交互 -->
    <div v-if="phase === 'precollect' && precheck" class="precollect-phase">
      <p class="phase-hint">请填写以下信息后开始执行：</p>

      <div class="interactions-form">
        <div
          v-for="inter in precheck.before_interactions"
          :key="inter.interaction_id"
          class="form-item"
        >
          <label>
            {{ inter.label }}
            <span v-if="inter.required" class="required">*</span>
          </label>
          <p v-if="inter.description" class="form-desc">{{ inter.description }}</p>

          <!-- 文本输入 -->
          <input
            v-if="inter.type === 'input'"
            v-model="preInputs[inter.interaction_id]"
            type="text"
            :placeholder="inter.label"
          />

          <!-- 单选 -->
          <select
            v-else-if="inter.type === 'select'"
            v-model="preInputs[inter.interaction_id]"
          >
            <option value="" disabled>请选择...</option>
            <option v-for="opt in inter.options" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </select>

          <!-- 确认框 -->
          <label v-else-if="inter.type === 'confirm'" class="checkbox-label">
            <input
              type="checkbox"
              v-model="preInputs[inter.interaction_id]"
            />
            <span>{{ inter.label }}</span>
          </label>
        </div>
      </div>

      <div class="actions">
        <button class="btn-secondary" @click="emit('close')">取消</button>
        <button class="btn-primary" @click="startExecution" :disabled="loading">
          {{ loading ? '启动中...' : '开始执行' }}
        </button>
      </div>
    </div>

    <!-- 运行中 -->
    <div v-else-if="phase === 'running'" class="running-phase">
      <div class="spinner"></div>
      <p>正在执行第 {{ (execution?.current_step || 0) + 1 }} 步...</p>

      <!-- 已完成步骤 -->
      <div v-if="execution?.completed_steps.length" class="completed-steps">
        <div
          v-for="step in execution.completed_steps"
          :key="step.step_index"
          class="step-item completed"
        >
          <span class="step-icon">{{ step.icon || '✓' }}</span>
          <span class="step-name">{{ step.skill_name }}</span>
          <span class="step-status">✓</span>
        </div>
      </div>

      <button class="btn-secondary" @click="cancelExecution">取消</button>
    </div>

    <!-- 暂停中（等待交互） -->
    <div v-else-if="phase === 'paused' && currentInteraction" class="paused-phase">
      <div class="interaction-panel">
        <div class="interaction-header">
          <span class="skill-badge">{{ currentInteraction.skill_name }}</span>
          <span class="step-badge">步骤 {{ currentInteraction.step_index + 1 }}</span>
        </div>

        <h4>{{ currentInteraction.label }}</h4>
        <p v-if="currentInteraction.description" class="interaction-desc">
          {{ currentInteraction.description }}
        </p>

        <!-- 上下文参考 -->
        <div v-if="currentInteraction.context" class="context-ref">
          <details>
            <summary>查看前序步骤输出</summary>
            <pre>{{ JSON.stringify(currentInteraction.context, null, 2) }}</pre>
          </details>
        </div>

        <!-- 交互控件 -->
        <div class="interaction-input">
          <!-- 文本输入 -->
          <input
            v-if="currentInteraction.type === 'input'"
            v-model="interactionValue"
            type="text"
            :placeholder="currentInteraction.label"
          />

          <!-- 单选 -->
          <select
            v-else-if="currentInteraction.type === 'select'"
            v-model="interactionValue"
          >
            <option value="" disabled>请选择...</option>
            <option v-for="opt in currentInteraction.options" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </select>

          <!-- 确认 -->
          <div v-else-if="currentInteraction.type === 'confirm'" class="confirm-buttons">
            <button class="btn-secondary" @click="interactionValue = false; submitInteraction()">
              取消
            </button>
            <button class="btn-primary" @click="interactionValue = true; submitInteraction()">
              确认
            </button>
          </div>
        </div>

        <div v-if="currentInteraction.type !== 'confirm'" class="actions">
          <button class="btn-secondary" @click="cancelExecution">取消执行</button>
          <button
            class="btn-primary"
            @click="submitInteraction"
            :disabled="loading || (currentInteraction.required && !interactionValue)"
          >
            {{ loading ? '处理中...' : '继续执行' }}
          </button>
        </div>
      </div>

      <!-- 已完成步骤 -->
      <div v-if="execution?.completed_steps.length" class="completed-steps">
        <div
          v-for="step in execution.completed_steps"
          :key="step.step_index"
          class="step-item completed"
        >
          <span class="step-icon">{{ step.icon || '✓' }}</span>
          <span class="step-name">{{ step.skill_name }}</span>
          <span class="step-status">✓</span>
        </div>
      </div>
    </div>

    <!-- 完成 -->
    <div v-else-if="phase === 'completed'" class="completed-phase">
      <div class="success-icon">✓</div>
      <h4>执行完成</h4>

      <div class="completed-steps">
        <div
          v-for="step in execution?.completed_steps"
          :key="step.step_index"
          class="step-item completed"
        >
          <span class="step-icon">{{ step.icon || '✓' }}</span>
          <span class="step-name">{{ step.skill_name }}</span>
          <span class="step-output" v-if="step.output">{{ step.output }}</span>
          <!-- 显示输出文件下载链接 -->
          <a
            v-if="getOutputFile(step)"
            :href="getOutputFileUrl(step)"
            target="_blank"
            class="output-file-link"
          >
            📄 {{ getOutputFile(step)?.name || '下载结果' }}
          </a>
        </div>
      </div>

      <div class="actions">
        <button class="btn-secondary" @click="emit('close')">关闭</button>
        <button class="btn-primary" @click="retry">再次执行</button>
      </div>
    </div>

    <!-- 失败 -->
    <div v-else-if="phase === 'failed'" class="failed-phase">
      <div class="error-icon">✕</div>
      <h4>执行失败</h4>
      <p class="error-message">{{ error }}</p>

      <div class="actions">
        <button class="btn-secondary" @click="emit('close')">关闭</button>
        <button class="btn-primary" @click="retry">重试</button>
      </div>
    </div>

    <!-- 加载中 -->
    <div v-else-if="loading" class="loading-phase">
      <div class="spinner"></div>
      <p>加载中...</p>
    </div>
  </div>
</template>

<style scoped>
.workflow-runner {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.12);
  max-width: 480px;
  width: 100%;
  max-height: 80vh;
  overflow-y: auto;
}

.runner-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid #e5e7eb;
}

.runner-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #111827;
}

.close-btn {
  width: 28px;
  height: 28px;
  border: none;
  background: #f3f4f6;
  border-radius: 6px;
  font-size: 18px;
  color: #6b7280;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.close-btn:hover {
  background: #e5e7eb;
  color: #374151;
}

/* 进度条 */
.progress-section {
  padding: 12px 20px;
  border-bottom: 1px solid #f3f4f6;
}

.progress-bar {
  height: 6px;
  background: #e5e7eb;
  border-radius: 3px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #6366f1, #8b5cf6);
  border-radius: 3px;
  transition: width 0.3s ease;
}

.progress-text {
  margin-top: 6px;
  font-size: 12px;
  color: #6b7280;
  text-align: right;
}

/* 预收集表单 */
.precollect-phase,
.running-phase,
.paused-phase,
.completed-phase,
.failed-phase,
.loading-phase {
  padding: 20px;
}

.phase-hint {
  margin: 0 0 16px;
  font-size: 14px;
  color: #6b7280;
}

.interactions-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-item label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: #374151;
  margin-bottom: 6px;
}

.form-item .required {
  color: #ef4444;
  margin-left: 2px;
}

.form-desc {
  margin: 0 0 6px;
  font-size: 12px;
  color: #9ca3af;
}

.form-item input[type="text"],
.form-item select {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  font-size: 14px;
  outline: none;
  transition: border-color 0.15s;
}

.form-item input[type="text"]:focus,
.form-item select:focus {
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.checkbox-label {
  display: flex !important;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.checkbox-label input[type="checkbox"] {
  width: 16px;
  height: 16px;
}

/* 按钮 */
.actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  margin-top: 20px;
}

.btn-primary,
.btn-secondary {
  padding: 10px 20px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}

.btn-primary {
  background: #6366f1;
  color: #fff;
  border: none;
}

.btn-primary:hover:not(:disabled) {
  background: #4f46e5;
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-secondary {
  background: #fff;
  color: #374151;
  border: 1px solid #d1d5db;
}

.btn-secondary:hover {
  background: #f9fafb;
  border-color: #9ca3af;
}

/* 运行中 */
.running-phase {
  text-align: center;
}

.spinner {
  width: 40px;
  height: 40px;
  border: 3px solid #e5e7eb;
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin: 0 auto 16px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 已完成步骤 */
.completed-steps {
  margin-top: 16px;
  border-top: 1px solid #f3f4f6;
  padding-top: 12px;
}

.step-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #f9fafb;
  border-radius: 6px;
  margin-bottom: 6px;
}

.step-item.completed {
  background: #ecfdf5;
}

.step-icon {
  font-size: 14px;
}

.step-name {
  flex: 1;
  font-size: 13px;
  color: #374151;
}

.step-status {
  color: #10b981;
  font-weight: 600;
}

.step-output {
  font-size: 11px;
  color: #6b7280;
  margin-left: auto;
}

.output-file-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: 12px;
  padding: 4px 10px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  text-decoration: none;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  transition: all 0.2s;
}

.output-file-link:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
}

/* 暂停交互 */
.interaction-panel {
  background: #f9fafb;
  border-radius: 10px;
  padding: 16px;
  border: 1px solid #e5e7eb;
}

.interaction-header {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.skill-badge,
.step-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 500;
}

.skill-badge {
  background: #dbeafe;
  color: #1d4ed8;
}

.step-badge {
  background: #fef3c7;
  color: #b45309;
}

.interaction-panel h4 {
  margin: 0 0 8px;
  font-size: 15px;
  color: #111827;
}

.interaction-desc {
  margin: 0 0 12px;
  font-size: 13px;
  color: #6b7280;
}

.context-ref {
  margin-bottom: 12px;
}

.context-ref summary {
  font-size: 12px;
  color: #6366f1;
  cursor: pointer;
}

.context-ref pre {
  margin: 8px 0 0;
  padding: 10px;
  background: #1e293b;
  color: #e2e8f0;
  border-radius: 6px;
  font-size: 11px;
  overflow-x: auto;
}

.interaction-input {
  margin-top: 12px;
}

.interaction-input input,
.interaction-input select {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  font-size: 14px;
  outline: none;
}

.confirm-buttons {
  display: flex;
  gap: 12px;
}

.confirm-buttons button {
  flex: 1;
}

/* 完成/失败 */
.success-icon,
.error-icon {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28px;
  margin: 0 auto 16px;
}

.success-icon {
  background: #d1fae5;
  color: #059669;
}

.error-icon {
  background: #fee2e2;
  color: #dc2626;
}

.completed-phase h4,
.failed-phase h4 {
  text-align: center;
  margin: 0 0 16px;
  font-size: 18px;
  color: #111827;
}

.error-message {
  text-align: center;
  color: #dc2626;
  font-size: 14px;
  margin: 0 0 16px;
  padding: 12px;
  background: #fef2f2;
  border-radius: 8px;
}

.loading-phase {
  text-align: center;
  padding: 40px 20px;
}

.loading-phase p {
  color: #6b7280;
  margin-top: 12px;
}
</style>
