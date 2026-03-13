<script setup lang="ts">
import { ref, watch, computed, nextTick } from 'vue'
import { skillsApi, agentApi } from '@/api'

const props = defineProps<{
  show: boolean
  mode: 'create' | 'upload'
  prefillName?: string | null
}>()

const emit = defineEmits<{
  close: []
  submit: [data: any]
}>()

// 创建流程阶段
type CreateStage = 'chat' | 'review'
const createStage = ref<CreateStage>('chat')

// AI 对话相关
interface AiMessage {
  id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  generating?: boolean
  options?: string[] // 快捷选项
  field?: string // 关联的字段
  isConfirmation?: boolean // 是否是确认消息
}

const aiMessages = ref<AiMessage[]>([])
const aiInput = ref('')
const aiGenerating = ref(false)
const aiChatContainer = ref<HTMLElement | null>(null)
const waitingConfirm = ref(false) // 等待用户确认创建
const skillSummary = ref('') // AI 总结的技能信息

// 当前收集阶段
type CollectStage = 'purpose' | 'name' | 'features' | 'confirm' | 'done'
const collectStage = ref<CollectStage>('purpose')

// 收集到的 Skill 数据
const skillData = ref({
  name: '',
  description: '',
  icon: '⚡',
  tags: [] as string[],
  purpose: '',
  features: [] as string[],
  skillMd: '',
  scripts: [
    { name: 'run.py', content: '' }
  ],
  references: [
    { name: 'api-guide.md', content: '' }
  ],
  assets: [
    { name: 'config.json', content: '' }
  ]
})

// 图标映射
const iconMap: Record<string, string> = {
  '数据': '📊', 'data': '📊', '分析': '📊',
  'API': '🔗', '接口': '🔗', '请求': '🔗',
  '文档': '📑', 'PDF': '📑', '解析': '📑',
  '翻译': '🌍', '语言': '🌍',
  '图像': '🖼️', '图片': '🖼️', '视觉': '🖼️',
  '代码': '💻', '编程': '💻', '开发': '💻',
  '测试': '🧪', '自动化': '🧪',
  '数据库': '🗃️', 'SQL': '🗃️',
  '邮件': '📧', '通知': '📧',
  '搜索': '🔍', '查找': '🔍',
}

// 上传相关
const uploadFiles = ref<File[]>([])
const uploadZipFile = ref<File | null>(null)  // ZIP 文件
const uploadFolderName = ref<string>('')
const isDragging = ref(false)
const uploadParsedData = ref<{
  name: string
  description: string
  icon: string
  tags: string[]
  skillMd: string
  files: { name: string; path: string; size: number }[]
} | null>(null)
const uploadError = ref<string | null>(null)
const isUploading = ref(false)

// 解析 SKILL.md 文件的 YAML frontmatter
const parseSkillMd = (content: string): { name: string; description: string; license?: string; body: string } => {
  const frontmatterMatch = content.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$/)
  if (!frontmatterMatch) {
    // 没有 frontmatter，尝试从内容提取
    const lines = content.split('\n')
    const titleMatch = lines[0]?.match(/^#\s+(.+)/)
    return {
      name: titleMatch ? titleMatch[1].trim() : 'uploaded-skill',
      description: lines.slice(1, 3).join(' ').trim() || 'Uploaded skill',
      body: content
    }
  }

  const [, frontmatter, body] = frontmatterMatch
  const result: any = { body: body.trim() }

  // 解析 YAML frontmatter
  if (frontmatter) {
    const lines = frontmatter.split('\n')
    for (const line of lines) {
      const match = line.match(/^(\w+):\s*(.+)$/)
      if (match) {
        const [, key, value] = match
        result[key] = value.trim()
      }
    }
  }

  return {
    name: result.name || 'uploaded-skill',
    description: result.description || 'Uploaded skill',
    license: result.license,
    body: result.body
  }
}

// 根据描述推断图标
const inferIcon = (description: string): string => {
  const desc = description.toLowerCase()
  if (desc.includes('frontend') || desc.includes('ui') || desc.includes('design')) return '🎨'
  if (desc.includes('data') || desc.includes('analysis')) return '📊'
  if (desc.includes('api') || desc.includes('integration')) return '🔗'
  if (desc.includes('doc') || desc.includes('document')) return '📑'
  if (desc.includes('translate') || desc.includes('language')) return '🌍'
  if (desc.includes('image') || desc.includes('visual')) return '🖼️'
  if (desc.includes('code') || desc.includes('programming')) return '💻'
  if (desc.includes('test')) return '🧪'
  if (desc.includes('database') || desc.includes('sql')) return '🗃️'
  if (desc.includes('email') || desc.includes('mail')) return '📧'
  return '⚡'
}

// 处理文件夹上传
const handleFolderUpload = async (files: FileList) => {
  uploadError.value = null
  uploadParsedData.value = null
  uploadFiles.value = []

  const fileArray = Array.from(files)
  if (fileArray.length === 0) {
    uploadError.value = '请选择文件夹'
    return
  }

  // 获取文件夹名称（从第一个文件的路径提取）
  const firstFile = fileArray[0]
  const pathParts = (firstFile.webkitRelativePath || firstFile.name).split('/')
  uploadFolderName.value = pathParts[0] || 'skill-folder'

  // 查找 SKILL.md 文件
  const skillMdFile = fileArray.find(f =>
    f.name.toUpperCase() === 'SKILL.MD' ||
    f.webkitRelativePath?.toUpperCase().endsWith('/SKILL.MD')
  )

  if (!skillMdFile) {
    uploadError.value = '文件夹中未找到 SKILL.md 文件'
    return
  }

  try {
    const content = await skillMdFile.text()
    const parsed = parseSkillMd(content)

    // 收集所有文件信息
    const fileInfos = fileArray.map(f => ({
      name: f.name,
      path: f.webkitRelativePath || f.name,
      size: f.size
    }))

    uploadFiles.value = fileArray
    uploadParsedData.value = {
      name: parsed.name,
      description: parsed.description,
      icon: inferIcon(parsed.description),
      tags: ['Uploaded'],
      skillMd: content,
      files: fileInfos
    }
  } catch (e: any) {
    uploadError.value = '文件解析失败: ' + e.message
  }
}

// 处理 ZIP 文件上传
const handleZipFileUpload = async (file: File) => {
  uploadError.value = null
  uploadParsedData.value = null
  uploadFiles.value = []
  uploadZipFile.value = file
  uploadFolderName.value = file.name.replace(/\.zip$/i, '')

  // ZIP 文件直接保存，不解析内容（后端会处理）
  uploadParsedData.value = {
    name: uploadFolderName.value,
    description: '从 ZIP 包导入的技能',
    icon: '📦',
    tags: ['Uploaded'],
    skillMd: '',
    files: [{ name: file.name, path: file.name, size: file.size }]
  }
}

// 处理单文件上传（兼容）
const handleSingleFileUpload = async (file: File) => {
  uploadError.value = null
  uploadParsedData.value = null

  // 支持 ZIP 文件
  if (file.name.toUpperCase().endsWith('.ZIP')) {
    await handleZipFileUpload(file)
    return
  }

  if (!file.name.toUpperCase().endsWith('.MD')) {
    uploadError.value = '请上传 ZIP 压缩包或 SKILL.md 文件'
    return
  }

  try {
    const content = await file.text()
    const parsed = parseSkillMd(content)

    uploadFiles.value = [file]
    uploadFolderName.value = ''
    uploadParsedData.value = {
      name: parsed.name,
      description: parsed.description,
      icon: inferIcon(parsed.description),
      tags: ['Uploaded'],
      skillMd: content,
      files: [{ name: file.name, path: file.name, size: file.size }]
    }
  } catch (e: any) {
    uploadError.value = '文件解析失败: ' + e.message
  }
}

// 初始化对话
const initConversation = () => {
  const prefillHint = props.prefillName ? `\n\n（提示：你提到了 "${props.prefillName}"，可以基于这个继续描述）` : ''

  aiMessages.value = [
    {
      id: 1,
      role: 'assistant',
      content: `👋 你好！我是 **Skill Creator**。\n\n告诉我你想创建什么样的技能？请描述：\n• 技能的用途和场景\n• 输入输出是什么\n• 有什么特殊功能\n\n我会帮你整理并生成完整的技能。${prefillHint}`,
      options: ['数据分析处理', 'API接口调用', '文档解析提取', '代码辅助工具'],
      field: 'purpose'
    }
  ]
  collectStage.value = 'purpose'
  waitingConfirm.value = false
  skillSummary.value = ''
  skillData.value = {
    name: '',
    description: '',
    icon: '⚡',
    tags: [],
    purpose: '',
    features: [],
    skillMd: '',
    scripts: [{ name: 'run.py', content: '' }],
    references: [{ name: 'api-guide.md', content: '' }],
    assets: [{ name: 'config.json', content: '' }]
  }
}

// 滚动到底部
const scrollToBottom = () => {
  nextTick(() => {
    if (aiChatContainer.value) {
      aiChatContainer.value.scrollTop = aiChatContainer.value.scrollHeight
    }
  })
}

// 处理用户输入 - 多轮 AI 对话
const handleUserInput = async (input: string) => {
  if (!input.trim() || aiGenerating.value) return

  waitingConfirm.value = false

  // 添加用户消息
  aiMessages.value.push({
    id: Date.now(),
    role: 'user',
    content: input
  })
  aiInput.value = ''
  aiGenerating.value = true
  scrollToBottom()

  // 添加 AI 回复占位
  const aiMsgId = Date.now() + 1
  aiMessages.value.push({
    id: aiMsgId,
    role: 'assistant',
    content: '',
    generating: true
  })
  scrollToBottom()

  try {
    // 收集对话历史
    const history = aiMessages.value
      .filter(m => m.role !== 'system' && m.id !== aiMsgId && !m.generating)
      .map(m => ({ role: m.role as 'user' | 'assistant', content: m.content }))

    // 收集用户所有输入
    const userInputs = aiMessages.value
      .filter(m => m.role === 'user')
      .map(m => m.content)

    // 调用 AI API
    let fullContent = ''
    for await (const chunk of agentApi.chatStream({
      message: `用户想创建一个技能，最新输入：${input}\n\n请根据用户的描述：
1. 理解用户需求
2. 总结技能的关键信息（名称、描述、功能、输入输出）
3. 询问是否有补充，或者是否可以开始创建

如果信息足够完整，请用以下格式总结：
---
📋 **技能概要**
- 名称：xxx
- 描述：xxx
- 功能：xxx
- 输入：xxx
- 输出：xxx
---
然后询问用户是否确认创建。`,
      history: history
    })) {
      fullContent += chunk
      const msgIndex = aiMessages.value.findIndex(m => m.id === aiMsgId)
      if (msgIndex !== -1) {
        aiMessages.value[msgIndex] = {
          ...aiMessages.value[msgIndex],
          content: fullContent,
          generating: false
        }
      }
      scrollToBottom()
    }

    // 检查是否包含技能概要（表示可以创建了）
    if (fullContent.includes('技能概要') || fullContent.includes('确认创建')) {
      waitingConfirm.value = true
      skillSummary.value = userInputs.join('；')

      // 尝试从 AI 回复中提取技能信息
      extractSkillInfo(fullContent, userInputs)
    }

  } catch (error: any) {
    // API 调用失败，使用模拟回复
    const userInputs = aiMessages.value
      .filter(m => m.role === 'user')
      .map(m => m.content)

    const simulatedResponse = generateSimulatedResponse(userInputs)

    const msgIndex = aiMessages.value.findIndex(m => m.id === aiMsgId)
    if (msgIndex !== -1) {
      aiMessages.value[msgIndex] = {
        ...aiMessages.value[msgIndex],
        content: simulatedResponse,
        generating: false
      }
    }

    waitingConfirm.value = true
    skillSummary.value = userInputs.join('；')
    extractSkillInfo(simulatedResponse, userInputs)
    scrollToBottom()
  } finally {
    aiGenerating.value = false
  }
}

// 从 AI 回复中提取技能信息
const extractSkillInfo = (aiResponse: string, userInputs: string[]) => {
  const combinedInput = userInputs.join(' ')

  // 提取名称
  const nameMatch = aiResponse.match(/名称[：:]\s*([^\n,，]+)/)
  if (nameMatch) {
    skillData.value.name = nameMatch[1].trim().replace(/\*\*/g, '')
  } else {
    skillData.value.name = generateSkillName(combinedInput)
  }

  // 提取描述
  const descMatch = aiResponse.match(/描述[：:]\s*([^\n]+)/)
  if (descMatch) {
    skillData.value.description = descMatch[1].trim().replace(/\*\*/g, '')
  } else {
    skillData.value.description = combinedInput.slice(0, 100)
  }

  // 智能提取图标
  for (const [key, icon] of Object.entries(iconMap)) {
    if (combinedInput.includes(key)) {
      skillData.value.icon = icon
      break
    }
  }

  // 提取功能
  const funcMatch = aiResponse.match(/功能[：:]\s*([^\n]+)/)
  if (funcMatch) {
    skillData.value.features = funcMatch[1].split(/[,，、]/).map(s => s.trim()).filter(Boolean)
  }

  skillData.value.purpose = combinedInput
}

// 生成模拟回复
const generateSimulatedResponse = (userInputs: string[]): string => {
  const combinedInput = userInputs.join(' ')
  const suggestedName = generateSkillName(combinedInput)

  // 智能提取图标
  let icon = '⚡'
  for (const [key, ic] of Object.entries(iconMap)) {
    if (combinedInput.includes(key)) {
      icon = ic
      break
    }
  }

  return `好的，我来总结一下你想要创建的技能：

---
📋 **技能概要**
- 名称：${suggestedName}
- 图标：${icon}
- 描述：${combinedInput.slice(0, 80)}${combinedInput.length > 80 ? '...' : ''}
- 功能：根据你的需求自动处理
- 输入：待处理的数据/内容
- 输出：处理结果
---

请确认以上信息是否正确？
• 确认无误 → 点击「确认创建」
• 需要补充 → 继续输入更多细节`
}

// 处理快捷选项点击
const handleOptionClick = (option: string) => {
  handleUserInput(option)
}

// 确认创建技能
const confirmCreateSkill = () => {
  waitingConfirm.value = false

  // 添加确认消息
  aiMessages.value.push({
    id: Date.now(),
    role: 'user',
    content: '✓ 确认创建'
  })

  // 生成完整的 Skill 结构
  generateSkillStructure()

  // 跳转到预览页面
  createStage.value = 'review'
  scrollToBottom()
}

// 继续补充
const continueAddingDetails = () => {
  waitingConfirm.value = false

  aiMessages.value.push({
    id: Date.now(),
    role: 'assistant',
    content: '好的，请继续补充你的需求，我会更新技能配置：'
  })
  scrollToBottom()

  nextTick(() => {
    const inputEl = document.querySelector('.ai-input-area input') as HTMLInputElement
    inputEl?.focus()
  })
}

// 取消创建
const cancelCreation = () => {
  emit('close')
}

// 根据阶段处理对话
const processStage = async (input: string) => {
  switch (collectStage.value) {
    case 'purpose':
      await handlePurposeInput(input)
      break
    case 'name':
      await handleNameInput(input)
      break
    case 'features':
      await handleFeaturesInput(input)
      break
    case 'confirm':
      await handleConfirmInput(input)
      break
  }
}

// 处理用途输入
const handlePurposeInput = async (input: string) => {
  skillData.value.purpose = input

  // 智能提取图标
  for (const [key, icon] of Object.entries(iconMap)) {
    if (input.includes(key)) {
      skillData.value.icon = icon
      break
    }
  }

  // 智能生成名称建议
  const suggestedName = generateSkillName(input)
  const suggestedDesc = `${input.slice(0, 50)}${input.length > 50 ? '...' : ''}`

  skillData.value.description = suggestedDesc

  aiMessages.value.push({
    id: Date.now(),
    role: 'assistant',
    content: `很好！我理解你想创建一个 **${input}** 相关的技能。\n\n我建议将它命名为：\n\n🏷️ **${suggestedName}**\n\n你觉得这个名字怎么样？也可以告诉我你想要的名字。`,
    options: [`用 "${suggestedName}"`, '我想换个名字'],
    field: 'name'
  })

  skillData.value.name = suggestedName
  collectStage.value = 'name'
}

// 处理名称输入
const handleNameInput = async (input: string) => {
  if (input.includes('用 "') || input.includes('可以') || input.includes('好') || input.includes('行')) {
    // 用户同意建议的名称
  } else {
    // 用户想换名字
    const newName = input.replace(/["""]/g, '').trim()
    if (newName && !newName.includes('换') && !newName.includes('名字')) {
      skillData.value.name = newName
    }
  }

  aiMessages.value.push({
    id: Date.now(),
    role: 'assistant',
    content: `好的，技能名称确定为 **${skillData.value.name}**！\n\n现在告诉我这个技能需要哪些核心功能？比如：\n- 输入输出格式\n- 主要处理逻辑\n- 特殊要求等`,
    options: ['自动生成基础功能', '我来详细描述'],
    field: 'features'
  })

  collectStage.value = 'features'
}

// 处理功能输入
const handleFeaturesInput = async (input: string) => {
  if (input.includes('自动生成') || input.includes('基础')) {
    skillData.value.features = ['基础数据处理', '标准输入输出', '错误处理']
  } else {
    skillData.value.features = input.split(/[,，、\n]/).map(s => s.trim()).filter(Boolean)
  }

  // 生成完整的 Skill 结构
  generateSkillStructure()

  aiMessages.value.push({
    id: Date.now(),
    role: 'assistant',
    content: `太棒了！我已经为你生成了完整的 Skill 结构：\n\n📁 **${skillData.value.name}/**\n├── 📄 SKILL.md\n├── 📁 scripts/\n│   └── run.py\n├── 📁 references/\n│   └── api-guide.md\n└── 📁 assets/\n    └── config.json\n\n点击下方按钮查看详情并确认创建。`,
    options: ['✅ 确认创建', '🔧 我想调整'],
    field: 'confirm'
  })

  collectStage.value = 'confirm'
}

// 处理确认输入
const handleConfirmInput = async (input: string) => {
  if (input.includes('确认') || input.includes('创建') || input.includes('好') || input.includes('✅')) {
    createStage.value = 'review'
  } else {
    aiMessages.value.push({
      id: Date.now(),
      role: 'assistant',
      content: '好的，你想调整什么？可以告诉我：\n- 修改名称\n- 修改描述\n- 添加/删除功能\n- 或者重新开始',
      options: ['修改名称', '修改描述', '重新开始']
    })
  }
}

// 生成技能名称
const generateSkillName = (purpose: string): string => {
  const keywords = ['数据', '分析', 'API', '接口', '文档', '解析', '翻译', '图像', '代码', '测试']
  for (const kw of keywords) {
    if (purpose.includes(kw)) {
      const nameMap: Record<string, string> = {
        '数据': 'data-processor',
        '分析': 'data-analyzer',
        'API': 'api-connector',
        '接口': 'api-integrator',
        '文档': 'doc-parser',
        '解析': 'content-extractor',
        '翻译': 'translator',
        '图像': 'image-processor',
        '代码': 'code-assistant',
        '测试': 'test-generator'
      }
      return nameMap[kw] || 'custom-skill'
    }
  }
  return 'custom-skill'
}

// 生成完整的 Skill 结构
const generateSkillStructure = () => {
  const { name, description, purpose, features } = skillData.value

  // 生成 SKILL.md
  skillData.value.skillMd = `# ${name}

## 概述
${description || purpose}

## 功能特性
${features.map(f => `- ${f}`).join('\n')}

## 使用方法
\`\`\`bash
python scripts/run.py --input "your_input"
\`\`\`

## 参数说明
| 参数 | 类型 | 必填 | 描述 |
|------|------|------|------|
| input | string | 是 | 输入内容 |
| output | string | 否 | 输出路径 |

## 输出格式
返回 JSON 格式的处理结果。

## 示例
\`\`\`json
{
  "status": "success",
  "data": {}
}
\`\`\`
`

  // 生成主脚本
  const scriptItem = skillData.value.scripts[0]
  if (scriptItem) scriptItem.content = `#!/usr/bin/env python3
"""
${name} - ${description || purpose}
Auto-generated by Skill Creator
"""

import argparse
import json
import sys

def main():
    parser = argparse.ArgumentParser(description='${description || purpose}')
    parser.add_argument('--input', required=True, help='Input data')
    parser.add_argument('--output', default=None, help='Output path')
    args = parser.parse_args()

    try:
        # TODO: 实现核心逻辑
        result = process(args.input)

        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(output)
        else:
            print(output)

    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}))
        sys.exit(1)

def process(input_data):
    """
    核心处理逻辑
    Features: ${features.join(', ')}
    """
    return {
        "status": "success",
        "data": input_data
    }

if __name__ == "__main__":
    main()
`

  // 生成参考文档
  const refItem = skillData.value.references[0]
  if (refItem) refItem.content = `# ${name} API 指南

## 接口说明
本技能提供以下功能接口...

## 调用方式
\`\`\`python
from ${name.replace(/-/g, '_')} import process
result = process(input_data)
\`\`\`

## 返回格式
- status: 状态码 (success/error)
- data: 处理结果
- message: 错误信息（仅在出错时）
`

  // 生成配置文件
  const assetItem = skillData.value.assets[0]
  if (assetItem) assetItem.content = JSON.stringify({
    name: name,
    version: "1.0.0",
    description: description || purpose,
    author: "user",
    created: new Date().toISOString().split('T')[0],
    features: features
  }, null, 2)

  // 智能标签
  skillData.value.tags = ['Custom']
  if (purpose.includes('数据') || purpose.includes('分析')) skillData.value.tags.push('Data')
  if (purpose.includes('API') || purpose.includes('接口')) skillData.value.tags.push('API')
}

// 上传处理
const handleDrop = async (e: DragEvent) => {
  isDragging.value = false
  const files = e.dataTransfer?.files

  // 处理文件
  if (files && files.length > 0) {
    const firstFile = files[0]
    if (firstFile) {
      // 只接受 ZIP 文件
      if (firstFile.name.toUpperCase().endsWith('.ZIP')) {
        await handleSingleFileUpload(firstFile)
      } else {
        uploadError.value = '请上传 ZIP 压缩包文件'
      }
    }
  }
}

// 递归读取文件夹中的所有文件
const readDirectoryFiles = async (dirEntry: FileSystemDirectoryEntry): Promise<File[]> => {
  const files: File[] = []

  const readEntries = (reader: FileSystemDirectoryReader): Promise<FileSystemEntry[]> => {
    return new Promise((resolve, reject) => {
      reader.readEntries(resolve, reject)
    })
  }

  const readFile = (fileEntry: FileSystemFileEntry): Promise<File> => {
    return new Promise((resolve, reject) => {
      fileEntry.file(resolve, reject)
    })
  }

  const processEntry = async (entry: FileSystemEntry, path: string = ''): Promise<void> => {
    if (entry.isFile) {
      const fileEntry = entry as FileSystemFileEntry
      const file = await readFile(fileEntry)
      // 创建带路径的文件对象
      const fileWithPath = new File([file], file.name, { type: file.type })
      Object.defineProperty(fileWithPath, 'webkitRelativePath', {
        value: path + file.name,
        writable: false
      })
      files.push(fileWithPath)
    } else if (entry.isDirectory) {
      const dirReader = (entry as FileSystemDirectoryEntry).createReader()
      let entries = await readEntries(dirReader)
      while (entries.length > 0) {
        for (const e of entries) {
          await processEntry(e, path + entry.name + '/')
        }
        entries = await readEntries(dirReader)
      }
    }
  }

  await processEntry(dirEntry, '')
  return files
}

// 从数组创建 FileList
const createFileListFromArray = (files: File[]): FileList => {
  const dt = new DataTransfer()
  files.forEach(f => dt.items.add(f))
  return dt.files
}

const handleFileSelect = async (e: Event) => {
  const target = e.target as HTMLInputElement
  const files = target.files
  if (files && files.length > 0) {
    const firstFile = files[0]
    if (firstFile) {
      await handleSingleFileUpload(firstFile)
    }
  }
  // 重置 input，允许再次选择相同文件
  target.value = ''
}

// 提交创建
const handleCreate = () => {
  emit('submit', {
    name: skillData.value.name,
    description: skillData.value.description,
    icon: skillData.value.icon,
    tags: skillData.value.tags,
    structure: {
      skillMd: skillData.value.skillMd,
      scripts: skillData.value.scripts,
      references: skillData.value.references,
      assets: skillData.value.assets
    }
  })
  resetForm()
}

const handleUploadSubmit = async () => {
  if (!uploadParsedData.value) return

  isUploading.value = true
  uploadError.value = null

  try {
    let newSkill

    // 如果有 ZIP 文件，使用 upload API
    if (uploadZipFile.value) {
      newSkill = await skillsApi.upload({
        file: uploadZipFile.value,
        name: uploadParsedData.value.name,
        description: uploadParsedData.value.description,
        icon: uploadParsedData.value.icon,
        tags: uploadParsedData.value.tags,
        author: 'uploaded',
        version: '1.0.0'
      })
    } else if (uploadFiles.value.length > 0) {
      // 文件夹上传：需要打包成 ZIP（暂不支持，提示用户）
      uploadError.value = '文件夹上传暂不支持，请先将文件夹压缩成 ZIP 文件再上传'
      isUploading.value = false
      return
    } else {
      uploadError.value = '请选择要上传的 ZIP 文件'
      isUploading.value = false
      return
    }

    // 通知父组件（传递完整数据，包括 id 表示已创建，父组件不需要再调用API）
    emit('submit', {
      id: newSkill.id,
      name: newSkill.name,
      description: newSkill.description,
      icon: newSkill.icon,
      tags: newSkill.tags,
      author: newSkill.author,
      version: newSkill.version,
      created_at: newSkill.created_at
    })
    resetForm()
  } catch (e: any) {
    console.error('Upload failed:', e)
    uploadError.value = '上传失败: ' + (e.message || '未知错误')
  } finally {
    isUploading.value = false
  }
}

// 重置
const resetForm = () => {
  createStage.value = 'chat'
  collectStage.value = 'purpose'
  initConversation()
  uploadFiles.value = []
  uploadZipFile.value = null
  uploadFolderName.value = ''
  uploadParsedData.value = null
  uploadError.value = null
  isUploading.value = false
  aiInput.value = ''
}

const handleClose = () => {
  resetForm()
  emit('close')
}

// 返回编辑
const backToChat = () => {
  createStage.value = 'chat'
}

// 编辑预览中的内容
const activeEditTab = ref<'skillMd' | 'script' | 'reference' | 'asset'>('skillMd')

// 安全访问数组元素的计算属性
const scriptContent = computed({
  get: () => skillData.value.scripts[0]?.content || '',
  set: (val: string) => {
    const item = skillData.value.scripts[0]
    if (item) item.content = val
  }
})

const referenceContent = computed({
  get: () => skillData.value.references[0]?.content || '',
  set: (val: string) => {
    const item = skillData.value.references[0]
    if (item) item.content = val
  }
})

const assetContent = computed({
  get: () => skillData.value.assets[0]?.content || '',
  set: (val: string) => {
    const item = skillData.value.assets[0]
    if (item) item.content = val
  }
})

// 监听显示状态
watch(() => props.show, (newVal) => {
  if (newVal) {
    initConversation()
    if (props.prefillName) {
      skillData.value.name = props.prefillName
      // 自动开始对话
      nextTick(() => {
        handleUserInput(`我想创建一个叫 ${props.prefillName} 的技能`)
      })
    }
  }
})
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="show" class="modal-overlay" @click.self="handleClose">
        <div class="modal-container">
          <!-- 关闭按钮 -->
          <button class="close-btn" @click="handleClose">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>

          <!-- 上传模式 -->
          <template v-if="mode === 'upload'">
            <div class="upload-mode">
              <div class="upload-header">
                <div class="upload-icon-big">📦</div>
                <h2>上传技能包</h2>
                <p>上传 ZIP 压缩包</p>
              </div>

              <div
                class="upload-zone"
                :class="{ dragging: isDragging, 'has-file': uploadZipFile || uploadFiles.length > 0 }"
                @dragover.prevent="isDragging = true"
                @dragleave="isDragging = false"
                @drop.prevent="handleDrop"
              >
                <!-- ZIP 文件选择 -->
                <input
                  type="file"
                  accept=".zip"
                  @change="handleFileSelect"
                />
                <template v-if="!uploadZipFile && uploadFiles.length === 0">
                  <div class="upload-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                      <polyline points="17 8 12 3 7 8"/>
                      <line x1="12" y1="3" x2="12" y2="15"/>
                    </svg>
                  </div>
                  <span class="upload-text">拖放 ZIP 文件到这里</span>
                  <span class="upload-hint">或点击选择技能压缩包</span>
                </template>
                <template v-else>
                  <div class="folder-preview">
                    <span class="folder-icon">📦</span>
                    <div class="folder-details">
                      <span class="folder-name">{{ uploadFolderName || '已选择文件' }}</span>
                      <span class="folder-count">{{ uploadZipFile ? (uploadZipFile.size / 1024).toFixed(1) + ' KB' : uploadFiles.length + ' 个文件' }}</span>
                    </div>
                    <button class="remove-btn" @click.stop="uploadFiles = []; uploadZipFile = null; uploadParsedData = null; uploadError = null; uploadFolderName = ''">✕</button>
                  </div>
                </template>
              </div>

              <!-- 错误信息 -->
              <div v-if="uploadError" class="upload-error">
                <span>⚠️</span> {{ uploadError }}
              </div>

              <!-- 技能信息编辑 -->
              <div v-if="uploadParsedData" class="parsed-preview">
                <div class="preview-form">
                  <div class="form-row">
                    <label>技能名称</label>
                    <input v-model="uploadParsedData.name" type="text" placeholder="输入技能名称" />
                  </div>
                  <div class="form-row">
                    <label>描述</label>
                    <input v-model="uploadParsedData.description" type="text" placeholder="输入技能描述" />
                  </div>
                  <div class="form-row">
                    <label>图标</label>
                    <input v-model="uploadParsedData.icon" type="text" placeholder="选择图标" style="width: 60px;" />
                  </div>
                </div>
              </div>

              <div class="upload-actions">
                <button class="btn-cancel" @click="handleClose">取消</button>
                <button class="btn-submit" :disabled="!uploadZipFile || isUploading" @click="handleUploadSubmit">
                  <template v-if="isUploading">
                    <span class="btn-spinner"></span>
                    上传中...
                  </template>
                  <template v-else>
                    上传并导入
                  </template>
                </button>
              </div>
            </div>
          </template>

          <!-- 创建模式 -->
          <template v-else>
            <!-- 对话阶段 -->
            <div v-if="createStage === 'chat'" class="create-mode">
              <!-- 顶部 -->
              <div class="create-header">
                <div class="header-avatar">
                  <span>🤖</span>
                  <span class="status-dot"></span>
                </div>
                <div class="header-info">
                  <h3>Skill 创建助手</h3>
                  <span class="header-hint">通过对话快速创建技能</span>
                </div>
                <!-- 进度指示 -->
                <div class="progress-pills">
                  <span class="pill" :class="{ active: collectStage === 'purpose', done: ['name', 'features', 'confirm', 'done'].includes(collectStage) }">1</span>
                  <span class="pill" :class="{ active: collectStage === 'name', done: ['features', 'confirm', 'done'].includes(collectStage) }">2</span>
                  <span class="pill" :class="{ active: collectStage === 'features', done: ['confirm', 'done'].includes(collectStage) }">3</span>
                  <span class="pill" :class="{ active: collectStage === 'confirm' || collectStage === 'done' }">✓</span>
                </div>
              </div>

              <!-- 来自 Agent 提示 -->
              <div v-if="prefillName" class="from-agent">
                <span>🤖</span>
                <span>来自 Agent 任务，创建后自动返回继续执行</span>
              </div>

              <!-- 对话区域 -->
              <div class="chat-area" ref="aiChatContainer">
                <div v-for="msg in aiMessages" :key="msg.id" class="chat-msg" :class="msg.role">
                  <div class="msg-bubble">
                    <!-- 加载动画 -->
                    <div v-if="msg.generating" class="typing">
                      <span></span><span></span><span></span>
                    </div>
                    <!-- 消息内容 -->
                    <template v-else>
                      <div class="msg-text" v-html="msg.content.replace(/\n/g, '<br>').replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')"></div>
                      <!-- 快捷选项 -->
                      <div v-if="msg.options" class="msg-options">
                        <button
                          v-for="opt in msg.options"
                          :key="opt"
                          class="option-btn"
                          @click="handleOptionClick(opt)"
                          :disabled="aiGenerating"
                        >
                          {{ opt }}
                        </button>
                      </div>
                    </template>
                  </div>
                </div>
              </div>

              <!-- 输入区域 -->
              <div class="input-area">
                <!-- 等待确认状态 -->
                <Transition name="fade" mode="out-in">
                  <div v-if="waitingConfirm" key="confirm" class="confirm-area">
                    <div class="confirm-hint">请确认以上技能信息是否正确</div>
                    <div class="confirm-actions">
                      <button class="confirm-btn primary" @click="confirmCreateSkill">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <polyline points="20 6 9 17 4 12"/>
                        </svg>
                        确认创建
                      </button>
                      <button class="confirm-btn secondary" @click="continueAddingDetails">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <path d="M12 5v14M5 12h14"/>
                        </svg>
                        继续补充
                      </button>
                      <button class="confirm-btn cancel" @click="cancelCreation">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <path d="M18 6L6 18M6 6l12 12"/>
                        </svg>
                        取消
                      </button>
                    </div>
                  </div>

                  <!-- 输入状态 -->
                  <div v-else key="input" class="input-wrapper">
                    <div class="input-box">
                      <input
                        v-model="aiInput"
                        type="text"
                        placeholder="描述你想创建的技能..."
                        @keydown.enter="handleUserInput(aiInput)"
                        :disabled="aiGenerating"
                      />
                      <button
                        class="send-btn"
                        @click="handleUserInput(aiInput)"
                        :disabled="!aiInput.trim() || aiGenerating"
                      >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <line x1="22" y1="2" x2="11" y2="13"/>
                          <polygon points="22 2 15 22 11 13 2 9 22 2"/>
                        </svg>
                      </button>
                    </div>
                    <div class="input-tips">
                      按 Enter 发送 · 描述越详细，生成的技能越准确
                    </div>
                  </div>
                </Transition>
              </div>
            </div>

            <!-- 预览确认阶段 -->
            <div v-else class="review-mode">
              <div class="review-header">
                <button class="back-btn" @click="backToChat">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="15 18 9 12 15 6"/>
                  </svg>
                  返回
                </button>
                <h3>确认 Skill 结构</h3>
              </div>

              <!-- Skill 概览卡片 -->
              <div class="skill-overview">
                <div class="skill-icon-big">{{ skillData.icon }}</div>
                <div class="skill-meta">
                  <h4>{{ skillData.name }}</h4>
                  <p>{{ skillData.description }}</p>
                  <div class="skill-tags">
                    <span v-for="tag in skillData.tags" :key="tag" class="tag">{{ tag }}</span>
                  </div>
                </div>
              </div>

              <!-- 文件编辑标签 -->
              <div class="edit-tabs">
                <button :class="{ active: activeEditTab === 'skillMd' }" @click="activeEditTab = 'skillMd'">
                  📄 SKILL.md
                </button>
                <button :class="{ active: activeEditTab === 'script' }" @click="activeEditTab = 'script'">
                  🐍 run.py
                </button>
                <button :class="{ active: activeEditTab === 'reference' }" @click="activeEditTab = 'reference'">
                  📚 api-guide.md
                </button>
                <button :class="{ active: activeEditTab === 'asset' }" @click="activeEditTab = 'asset'">
                  📦 config.json
                </button>
              </div>

              <!-- 编辑区域 -->
              <div class="edit-content">
                <textarea
                  v-if="activeEditTab === 'skillMd'"
                  v-model="skillData.skillMd"
                  spellcheck="false"
                ></textarea>
                <textarea
                  v-else-if="activeEditTab === 'script'"
                  v-model="scriptContent"
                  spellcheck="false"
                ></textarea>
                <textarea
                  v-else-if="activeEditTab === 'reference'"
                  v-model="referenceContent"
                  spellcheck="false"
                ></textarea>
                <textarea
                  v-else
                  v-model="assetContent"
                  spellcheck="false"
                ></textarea>
              </div>

              <!-- 操作按钮 -->
              <div class="review-actions">
                <button class="btn-cancel" @click="backToChat">继续调整</button>
                <button class="btn-submit" @click="handleCreate">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="20 6 9 17 4 12"/>
                  </svg>
                  创建技能
                </button>
              </div>
            </div>
          </template>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.6);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 20px;
}

.modal-container {
  background: #fff;
  border-radius: 20px;
  width: 100%;
  max-width: 520px;
  max-height: 85vh;
  overflow: hidden;
  position: relative;
  box-shadow: 0 25px 50px rgba(0, 0, 0, 0.25);
  display: flex;
  flex-direction: column;
}

.close-btn {
  position: absolute;
  top: 16px;
  right: 16px;
  width: 32px;
  height: 32px;
  background: rgba(0,0,0,0.05);
  border: none;
  border-radius: 8px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #64748b;
  transition: all 0.2s;
  z-index: 10;
}

.close-btn:hover {
  background: rgba(0,0,0,0.1);
  color: #1e293b;
}

.close-btn svg {
  width: 18px;
  height: 18px;
}

/* ============ 上传模式 ============ */
.upload-mode {
  padding: 32px 28px;
}

.upload-header {
  text-align: center;
  margin-bottom: 24px;
}

.upload-icon-big {
  font-size: 48px;
  margin-bottom: 12px;
}

.upload-header h2 {
  font-size: 20px;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 6px;
}

.upload-header p {
  font-size: 14px;
  color: #64748b;
  margin: 0;
}

.upload-zone {
  background: #f8fafc;
  border: 2px dashed #e2e8f0;
  border-radius: 16px;
  padding: 40px 24px;
  text-align: center;
  position: relative;
  transition: all 0.2s;
  cursor: pointer;
}

.upload-zone input {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
}

.upload-zone.dragging {
  border-color: #6366f1;
  background: rgba(99, 102, 241, 0.05);
}

.upload-zone .upload-icon {
  margin-bottom: 16px;
}

.upload-zone .upload-icon svg {
  width: 48px;
  height: 48px;
  color: #94a3b8;
}

.upload-text {
  display: block;
  font-size: 16px;
  font-weight: 500;
  color: #1e293b;
  margin-bottom: 6px;
}

.upload-hint {
  font-size: 13px;
  color: #94a3b8;
}

.upload-zone.has-file {
  padding: 20px 24px;
  border-style: solid;
  border-color: #6366f1;
}

.file-preview,
.folder-preview {
  display: flex;
  align-items: center;
  gap: 14px;
}

.file-icon,
.folder-icon {
  font-size: 32px;
}

.file-details,
.folder-details {
  flex: 1;
  text-align: left;
}

.file-name,
.folder-name {
  display: block;
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
}

.file-size,
.folder-count {
  font-size: 12px;
  color: #94a3b8;
}

.remove-btn {
  width: 28px;
  height: 28px;
  background: #fee2e2;
  border: none;
  border-radius: 6px;
  color: #dc2626;
  cursor: pointer;
  font-size: 14px;
}

.upload-actions {
  display: flex;
  gap: 12px;
  margin-top: 24px;
}

/* 上传错误 */
.upload-error {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 10px;
  margin-top: 16px;
  font-size: 13px;
  color: #dc2626;
}

/* 技能信息表单 */
.parsed-preview {
  margin-top: 16px;
  padding: 16px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
}

.preview-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.form-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.form-row label {
  font-size: 12px;
  font-weight: 500;
  color: #64748b;
}

.form-row input {
  padding: 10px 12px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 14px;
  color: #1e293b;
  transition: all 0.2s;
}

.form-row input:focus {
  outline: none;
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

/* 按钮加载状态 */
.btn-spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  display: inline-block;
  margin-right: 6px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ============ 创建模式 ============ */
.create-mode {
  display: flex;
  flex-direction: column;
  height: 70vh;
  max-height: 600px;
}

.create-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px 24px;
  border-bottom: 1px solid #f1f5f9;
  background: linear-gradient(180deg, #fff 0%, #fafbfc 100%);
}

.header-avatar {
  position: relative;
  width: 44px;
  height: 44px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
}

.status-dot {
  position: absolute;
  bottom: -2px;
  right: -2px;
  width: 12px;
  height: 12px;
  background: #10b981;
  border: 2px solid #fff;
  border-radius: 50%;
}

.header-info {
  flex: 1;
}

.header-info h3 {
  font-size: 16px;
  font-weight: 700;
  color: #1e293b;
  margin: 0;
}

.header-hint {
  font-size: 12px;
  color: #94a3b8;
}

.progress-pills {
  display: flex;
  gap: 6px;
}

.pill {
  width: 24px;
  height: 24px;
  background: #f1f5f9;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 600;
  color: #94a3b8;
  transition: all 0.3s;
}

.pill.active {
  background: #6366f1;
  color: #fff;
  transform: scale(1.1);
}

.pill.done {
  background: #10b981;
  color: #fff;
}

.from-agent {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px;
  background: linear-gradient(90deg, rgba(99,102,241,0.1) 0%, rgba(139,92,246,0.1) 100%);
  font-size: 12px;
  color: #6366f1;
  font-weight: 500;
}

/* 对话区域 */
.chat-area {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.chat-msg {
  display: flex;
  flex-direction: column;
  animation: msgIn 0.3s ease;
}

@keyframes msgIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

.chat-msg.user {
  align-items: flex-end;
}

.chat-msg.assistant {
  align-items: flex-start;
}

.msg-bubble {
  max-width: 85%;
  padding: 14px 18px;
  border-radius: 18px;
  font-size: 14px;
  line-height: 1.6;
}

.chat-msg.user .msg-bubble {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
  border-bottom-right-radius: 6px;
}

.chat-msg.assistant .msg-bubble {
  background: #f1f5f9;
  color: #1e293b;
  border-bottom-left-radius: 6px;
}

.msg-text strong {
  color: #6366f1;
  font-weight: 600;
}

.chat-msg.user .msg-text strong {
  color: #fff;
}

/* 快捷选项 */
.msg-options {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}

.option-btn {
  padding: 8px 14px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 500;
  color: #475569;
  cursor: pointer;
  transition: all 0.2s;
}

.option-btn:hover:not(:disabled) {
  background: #6366f1;
  border-color: #6366f1;
  color: #fff;
  transform: translateY(-1px);
}

.option-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 打字动画 */
.typing {
  display: flex;
  gap: 4px;
  padding: 4px 0;
}

.typing span {
  width: 8px;
  height: 8px;
  background: #94a3b8;
  border-radius: 50%;
  animation: bounce 1.4s infinite ease-in-out;
}

.typing span:nth-child(1) { animation-delay: 0s; }
.typing span:nth-child(2) { animation-delay: 0.2s; }
.typing span:nth-child(3) { animation-delay: 0.4s; }

@keyframes bounce {
  0%, 60%, 100% { transform: translateY(0); }
  30% { transform: translateY(-6px); }
}

/* 输入区域 */
.input-area {
  padding: 16px 24px 20px;
  background: #fff;
  border-top: 1px solid #f1f5f9;
}

.input-box {
  display: flex;
  gap: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 6px 6px 6px 18px;
  transition: all 0.2s;
}

.input-box:focus-within {
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
  background: #fff;
}

.input-box input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  font-size: 14px;
  color: #1e293b;
}

.input-box input::placeholder {
  color: #94a3b8;
}

.send-btn {
  width: 40px;
  height: 40px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border: none;
  border-radius: 10px;
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.send-btn:hover:not(:disabled) {
  transform: scale(1.05);
}

.send-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.send-btn svg {
  width: 18px;
  height: 18px;
}

.input-tips {
  text-align: center;
  font-size: 11px;
  color: #94a3b8;
  margin-top: 10px;
}

.input-wrapper {
  display: flex;
  flex-direction: column;
}

/* 确认区域 */
.confirm-area {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.confirm-hint {
  text-align: center;
  font-size: 13px;
  color: #64748b;
}

.confirm-actions {
  display: flex;
  gap: 10px;
}

.confirm-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 13px;
  font-weight: 600;
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
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(139, 92, 246, 0.4);
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

/* fade 动画 */
.fade-enter-active,
.fade-leave-active {
  transition: all 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: translateY(5px);
}

/* ============ 预览模式 ============ */
.review-mode {
  display: flex;
  flex-direction: column;
  height: 70vh;
  max-height: 600px;
}

.review-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 24px;
  border-bottom: 1px solid #f1f5f9;
}

.back-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  background: #f1f5f9;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s;
}

.back-btn:hover {
  background: #e2e8f0;
}

.back-btn svg {
  width: 16px;
  height: 16px;
}

.review-header h3 {
  font-size: 16px;
  font-weight: 600;
  color: #1e293b;
  margin: 0;
}

/* Skill 概览 */
.skill-overview {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px 24px;
  background: linear-gradient(135deg, rgba(99,102,241,0.08) 0%, rgba(139,92,246,0.08) 100%);
  border-bottom: 1px solid #e2e8f0;
}

.skill-icon-big {
  width: 56px;
  height: 56px;
  background: #fff;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
}

.skill-meta {
  flex: 1;
}

.skill-meta h4 {
  font-size: 18px;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 4px;
}

.skill-meta p {
  font-size: 13px;
  color: #64748b;
  margin: 0 0 8px;
}

.skill-tags {
  display: flex;
  gap: 6px;
}

.tag {
  padding: 3px 10px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 500;
  color: #6366f1;
}

/* 编辑标签 */
.edit-tabs {
  display: flex;
  gap: 2px;
  padding: 12px 24px 0;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
}

.edit-tabs button {
  padding: 10px 14px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  font-size: 12px;
  font-weight: 500;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s;
}

.edit-tabs button:hover {
  color: #475569;
}

.edit-tabs button.active {
  color: #6366f1;
  border-bottom-color: #6366f1;
  background: #fff;
}

/* 编辑内容 */
.edit-content {
  flex: 1;
  overflow: hidden;
}

.edit-content textarea {
  width: 100%;
  height: 100%;
  background: #1e293b;
  border: none;
  padding: 16px 20px;
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
  font-size: 12px;
  line-height: 1.6;
  color: #e2e8f0;
  resize: none;
  box-sizing: border-box;
}

.edit-content textarea:focus {
  outline: none;
}

/* 操作按钮 */
.review-actions {
  display: flex;
  gap: 12px;
  padding: 16px 24px;
  background: #fff;
  border-top: 1px solid #f1f5f9;
}

.btn-cancel,
.btn-submit {
  flex: 1;
  padding: 12px 20px;
  border-radius: 12px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.btn-cancel {
  background: #f1f5f9;
  border: none;
  color: #64748b;
}

.btn-cancel:hover {
  background: #e2e8f0;
}

.btn-submit {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border: none;
  color: #fff;
}

.btn-submit:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 15px rgba(99, 102, 241, 0.4);
}

.btn-submit:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-submit svg {
  width: 18px;
  height: 18px;
}

/* ============ 过渡动画 ============ */
.modal-enter-active,
.modal-leave-active {
  transition: all 0.3s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-from .modal-container,
.modal-leave-to .modal-container {
  transform: scale(0.95) translateY(20px);
  opacity: 0;
}

.modal-enter-active .modal-container,
.modal-leave-active .modal-container {
  transition: all 0.3s ease;
}
</style>
