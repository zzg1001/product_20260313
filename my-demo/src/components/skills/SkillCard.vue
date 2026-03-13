<script setup lang="ts">
import { computed } from 'vue'

interface Skill {
  id: number
  name: string
  description: string
  tags: string[]
  icon: string
  author: string
  version: string
  created_at?: string
}

const props = defineProps<{
  skill: Skill
}>()

const emit = defineEmits<{
  delete: []
  edit: []
}>()

// 是否可编辑（上传的不可编辑）
const isEditable = computed(() => {
  return props.skill.author !== 'uploaded'
})

const handleEdit = (e: Event) => {
  e.stopPropagation()
  emit('edit')
}

const tagColors = computed(() => {
  return props.skill.tags.map(tag => {
    switch (tag.toLowerCase()) {
      case 'expert': return { bg: '#fef3c7', color: '#b45309' }
      case 'public': return { bg: '#d1fae5', color: '#047857' }
      case 'private': return { bg: '#fee2e2', color: '#b91c1c' }
      case 'beta': return { bg: '#e0e7ff', color: '#4338ca' }
      default: return { bg: '#f1f5f9', color: '#475569' }
    }
  })
})

const handleDelete = (e: Event) => {
  e.stopPropagation()
  emit('delete')
}

// 格式化时间
const formatDate = (dateStr?: string) => {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  const days = Math.floor(diff / (1000 * 60 * 60 * 24))

  if (days === 0) return '今天'
  if (days === 1) return '昨天'
  if (days < 7) return `${days}天前`
  if (days < 30) return `${Math.floor(days / 7)}周前`

  return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

// 截断描述
const shortDesc = computed(() => {
  const desc = props.skill.description || ''
  return desc.length > 30 ? desc.slice(0, 30) + '...' : desc
})
</script>

<template>
  <article class="card" :class="{ 'is-uploaded': !isEditable }">
    <div class="card-actions">
      <button v-if="isEditable" class="action-btn edit-btn" @click="handleEdit" title="编辑">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
        </svg>
      </button>
      <button class="action-btn del-btn" @click="handleDelete" title="删除">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M18 6L6 18M6 6l12 12"/>
        </svg>
      </button>
    </div>
    <div class="card-icon">{{ skill.icon }}</div>
    <div class="card-body">
      <div class="tags">
        <span v-for="(tag, i) in skill.tags" :key="tag" class="tag" :style="{ background: tagColors[i]?.bg || '#f1f5f9', color: tagColors[i]?.color || '#475569' }">{{ tag }}</span>
      </div>
      <div class="title">{{ skill.name }}</div>
      <div class="desc-wrapper">
        <span class="desc">{{ shortDesc }}</span>
        <div v-if="skill.description && skill.description.length > 30" class="tooltip">{{ skill.description }}</div>
      </div>
      <div class="meta">
        <span :class="{ 'uploaded-badge': !isEditable }">
          {{ isEditable ? skill.author : '📦 已上传' }}
        </span>
        <span v-if="skill.created_at" class="time">{{ formatDate(skill.created_at) }}</span>
        <span class="ver">v{{ skill.version }}</span>
      </div>
    </div>
  </article>
</template>

<style scoped>
.card {
  flex: 1;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  display: flex;
  padding: 8px;
  gap: 8px;
  cursor: pointer;
  transition: all 0.12s;
  overflow: hidden;
  position: relative;
}

.card:hover {
  border-color: #818cf8;
  box-shadow: 0 1px 4px rgba(99,102,241,0.1);
}

/* 操作按钮组 */
.card-actions {
  position: absolute;
  top: 4px;
  right: 4px;
  display: flex;
  gap: 2px;
  opacity: 0;
  transition: all 0.12s;
}

.card:hover .card-actions { opacity: 1; }

.action-btn {
  width: 18px;
  height: 18px;
  background: #f3f4f6;
  border: none;
  border-radius: 4px;
  color: #9ca3af;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.12s;
}

.action-btn svg {
  width: 10px;
  height: 10px;
}

.edit-btn:hover {
  background: #e0e7ff;
  color: #6366f1;
}

.del-btn:hover {
  background: #fee2e2;
  color: #dc2626;
}

/* 上传的卡片样式 */
.card.is-uploaded {
  border-style: dashed;
}

.uploaded-badge {
  color: #8b5cf6;
  font-weight: 500;
}

.card-icon {
  width: 28px;
  height: 28px;
  background: #f8fafc;
  border-radius: 5px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  flex-shrink: 0;
}

.card-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.tags {
  display: flex;
  gap: 2px;
}

.tag {
  font-size: 7px;
  font-weight: 700;
  text-transform: uppercase;
  padding: 1px 3px;
  border-radius: 2px;
}

.title {
  font-size: 11px;
  font-weight: 600;
  color: #111827;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.desc-wrapper {
  position: relative;
}

.desc {
  font-size: 9px;
  line-height: 1.3;
  color: #6b7280;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  display: block;
}

.tooltip {
  position: absolute;
  left: 0;
  top: 100%;
  margin-top: 4px;
  padding: 6px 10px;
  background: #1e293b;
  color: #f1f5f9;
  font-size: 10px;
  line-height: 1.4;
  border-radius: 6px;
  max-width: 180px;
  width: max-content;
  z-index: 100;
  opacity: 0;
  visibility: hidden;
  transform: translateY(-4px);
  transition: all 0.15s ease;
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  pointer-events: none;
}

.tooltip::before {
  content: '';
  position: absolute;
  top: -4px;
  left: 12px;
  border: 4px solid transparent;
  border-bottom-color: #1e293b;
  border-top: none;
}

.desc-wrapper:hover .tooltip {
  opacity: 1;
  visibility: visible;
  transform: translateY(0);
}

.meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 8px;
  color: #9ca3af;
  margin-top: auto;
}

.time {
  color: #94a3b8;
}

.ver {
  background: #f3f4f6;
  padding: 0 3px;
  border-radius: 2px;
  margin-left: auto;
}
</style>
