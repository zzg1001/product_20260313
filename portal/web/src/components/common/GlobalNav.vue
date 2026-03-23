<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'

const router = useRouter()
const route = useRoute()

const isExpanded = ref(false)

interface NavItem {
  path: string
  query?: { tab: string }
  icon: string
  label: string
  name: string
}

const navItems: NavItem[] = [
  { path: '/', query: { tab: 'agent' }, icon: '💬', label: '对话', name: 'home' },
  { path: '/', query: { tab: 'skills' }, icon: '⚡', label: 'Skills', name: 'skills' },
  { path: '/', query: { tab: 'workflows' }, icon: '🔗', label: '工作流', name: 'workflows' },
  { path: '/agents', icon: '🤖', label: 'Agents', name: 'agents' },
  { path: '/architecture', icon: '◈', label: '架构', name: 'architecture' },
  { path: '/agent-studio', icon: '🛠️', label: '工坊', name: 'agent-studio' },
  { path: '/monitor', icon: '📡', label: '监控', name: 'monitor' }
]

const isActive = (item: NavItem) => {
  if (item.query?.tab) {
    return route.path === item.path && route.query.tab === item.query.tab
  }
  if (item.path === '/' && !item.query) {
    return route.path === '/' && !route.query.tab
  }
  return route.path === item.path
}

const navigate = (item: NavItem) => {
  if (item.query) {
    router.push({ path: item.path, query: item.query })
  } else {
    router.push(item.path)
  }
}

const toggleNav = () => {
  isExpanded.value = !isExpanded.value
}
</script>

<template>
  <nav :class="['global-nav', { expanded: isExpanded }]">
    <!-- 展开/收起按钮 -->
    <button class="nav-toggle" @click="toggleNav">
      <svg viewBox="0 0 20 20" fill="currentColor">
        <path v-if="isExpanded" fill-rule="evenodd" d="M12.707 5.293a1 1 0 010 1.414L9.414 10l3.293 3.293a1 1 0 01-1.414 1.414l-4-4a1 1 0 010-1.414l4-4a1 1 0 011.414 0z" clip-rule="evenodd"/>
        <path v-else fill-rule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clip-rule="evenodd"/>
      </svg>
    </button>

    <!-- 导航项 -->
    <div class="nav-items">
      <button
        v-for="item in navItems"
        :key="item.name"
        :class="['nav-item', { active: isActive(item) }]"
        @click="navigate(item)"
        :title="item.label"
      >
        <span class="nav-icon">{{ item.icon }}</span>
        <span v-if="isExpanded" class="nav-label">{{ item.label }}</span>
      </button>
    </div>
  </nav>
</template>

<style scoped>
.global-nav {
  position: fixed;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  z-index: 1000;
  display: flex;
  flex-direction: column;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-left: none;
  border-radius: 0 12px 12px 0;
  padding: 8px;
  box-shadow: 2px 0 8px rgba(0, 0, 0, 0.08);
  transition: all 0.3s ease;
}

.global-nav.expanded {
  width: 130px;
}

.nav-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  background: transparent;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  border-radius: 8px;
  margin-bottom: 8px;
  transition: all 0.2s;
}

.nav-toggle:hover {
  background: #f1f5f9;
  color: #64748b;
}

.nav-toggle svg {
  width: 16px;
  height: 16px;
}

.nav-items {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: transparent;
  border: none;
  border-radius: 8px;
  color: #64748b;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}

.nav-item:hover {
  background: #f1f5f9;
  color: #475569;
}

.nav-item.active {
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.1), rgba(118, 75, 162, 0.1));
  color: #667eea;
}

.nav-icon {
  font-size: 18px;
  flex-shrink: 0;
}

.nav-label {
  font-weight: 500;
}
</style>
