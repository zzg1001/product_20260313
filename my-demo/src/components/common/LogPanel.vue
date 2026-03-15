<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ 'update:show': [value: boolean] }>()

const connected = ref(false)
const logCount = ref(0)
let logWindow: Window | null = null

// 打开日志窗口
const openLogWindow = () => {
  if (logWindow && !logWindow.closed) {
    logWindow.focus()
    return
  }

  const width = 420
  const height = window.screen.availHeight
  const left = window.screen.availWidth - width

  logWindow = window.open('', 'logs', `width=${width},height=${height},left=${left},top=0,menubar=no,toolbar=no,location=no,status=no,resizable=yes`)
  if (!logWindow) {
    alert('请允许弹出窗口')
    return
  }

  const host = location.hostname
  const doc = logWindow.document

  doc.write(`<!DOCTYPE html><html><head><title>运行日志</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0f172a;font-family:-apple-system,sans-serif;font-size:13px;color:#e2e8f0}
.header{position:sticky;top:0;z-index:10;display:flex;align-items:center;justify-content:space-between;padding:10px 16px;background:#1e293b;border-bottom:1px solid #334155}
.header-left{display:flex;align-items:center;gap:10px}
.dot{width:8px;height:8px;border-radius:50%;background:#64748b}
.dot.on{background:#22c55e}
.title{font-weight:600;color:#f1f5f9}
.count{color:#64748b;font-size:12px}
.header-right{display:flex;gap:8px}
.btn{background:#334155;border:none;color:#94a3b8;padding:6px 12px;border-radius:4px;cursor:pointer;font-size:12px}
.btn:hover{background:#475569;color:#e2e8f0}
#logs{padding:12px;height:calc(100vh - 50px);overflow-y:auto}
#logs::-webkit-scrollbar{width:6px}
#logs::-webkit-scrollbar-thumb{background:#475569;border-radius:3px}
.log{padding:10px 12px;margin-bottom:6px;background:#1e293b;border-radius:6px;border-left:3px solid #3b82f6}
.log.success{border-left-color:#22c55e}
.log.warn{border-left-color:#f59e0b;background:rgba(245,158,11,0.08)}
.log.error{border-left-color:#ef4444;background:rgba(239,68,68,0.08)}
.log-header{display:flex;align-items:center;gap:8px;margin-bottom:4px}
.log-title{flex:1;font-weight:500;color:#f1f5f9}
.log-step{color:#64748b;font-size:11px;background:#334155;padding:2px 6px;border-radius:3px}
.log-time{color:#64748b;font-size:11px}
.log-detail{color:#94a3b8;font-size:12px;margin-top:6px;line-height:1.5}
.log-data{margin-top:8px}
.log-data summary{color:#64748b;font-size:11px;cursor:pointer;padding:4px 0}
.log-data summary:hover{color:#94a3b8}
.log-data pre{margin-top:6px;padding:10px 12px;background:#0f172a;border:1px solid #334155;border-radius:4px;color:#94a3b8;font-size:11px;font-family:Monaco,Consolas,monospace;line-height:1.5;white-space:pre-wrap;word-break:break-all;max-height:200px;overflow-y:auto}
.empty{display:flex;align-items:center;justify-content:center;height:200px;color:#64748b}
</style></head>
<body>
<div class="header">
<div class="header-left"><span class="dot" id="dot"></span><span class="title">运行日志</span><span class="count" id="count">0 条</span></div>
<div class="header-right"><button class="btn" id="scrollBtn">自动滚动: 开</button><button class="btn" id="clearBtn">清空</button></div>
</div>
<div id="logs"><div class="empty">连接中...</div></div>
</body></html>`)
  doc.close()

  // 获取元素
  const logsEl = doc.getElementById('logs')!
  const dotEl = doc.getElementById('dot')!
  const countEl = doc.getElementById('count')!
  const scrollBtn = doc.getElementById('scrollBtn')!
  const clearBtn = doc.getElementById('clearBtn')!

  let count = 0
  let autoScroll = true
  let ws: WebSocket | null = null

  // 添加日志
  const addLog = (d: any) => {
    const empty = logsEl.querySelector('.empty')
    if (empty) empty.remove()

    const div = doc.createElement('div')
    div.className = 'log ' + (d.level || 'info')

    let html = '<div class="log-header">'
    html += '<span class="log-title">' + escapeHtml(d.title || '') + '</span>'
    if (d.step) html += '<span class="log-step">' + escapeHtml(d.step) + '</span>'
    html += '<span class="log-time">' + (d.time || '') + '</span>'
    html += '</div>'

    if (d.detail) {
      html += '<div class="log-detail">' + escapeHtml(d.detail) + '</div>'
    }

    if (d.data) {
      html += '<details class="log-data"><summary>📋 查看详细数据</summary><pre>' + escapeHtml(d.data) + '</pre></details>'
    }

    div.innerHTML = html
    logsEl.appendChild(div)
    count++
    countEl.textContent = count + ' 条'

    if (autoScroll) {
      logsEl.scrollTop = logsEl.scrollHeight
    }

    while (logsEl.children.length > 300) {
      logsEl.removeChild(logsEl.firstChild!)
      count--
    }
  }

  const escapeHtml = (text: string) => {
    if (!text) return ''
    const div = doc.createElement('div')
    div.textContent = text
    return div.innerHTML
  }

  // 连接 WebSocket
  const connect = () => {
    const wsUrl = `ws://${host}:8000/api/logs/ws`
    console.log('Connecting:', wsUrl)

    ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      console.log('Connected')
      dotEl.classList.add('on')
      logsEl.innerHTML = '<div class="empty">已连接，等待日志...</div>'
    }

    ws.onclose = () => {
      console.log('Disconnected')
      dotEl.classList.remove('on')
      setTimeout(connect, 3000)
    }

    ws.onerror = (e) => {
      console.error('WS Error:', e)
    }

    ws.onmessage = (e) => {
      try {
        const d = JSON.parse(e.data)
        console.log('Msg:', d)
        if (d.type || !d.id) return
        addLog(d)
      } catch (err) {
        console.error('Parse error:', err)
      }
    }
  }

  // 按钮事件
  scrollBtn.onclick = () => {
    autoScroll = !autoScroll
    scrollBtn.textContent = '自动滚动: ' + (autoScroll ? '开' : '关')
  }

  clearBtn.onclick = () => {
    fetch(`http://${host}:8000/api/logs/clear`, { method: 'DELETE' })
    logsEl.innerHTML = '<div class="empty">日志已清空</div>'
    count = 0
    countEl.textContent = '0 条'
  }

  connect()

  // 监听窗口关闭
  const checkClosed = setInterval(() => {
    if (logWindow?.closed) {
      clearInterval(checkClosed)
      logWindow = null
      emit('update:show', false)
    }
  }, 500)

  emit('update:show', true)
}

// 状态检测
let statusWs: WebSocket | null = null

const checkConnection = () => {
  const wsUrl = `ws://${location.hostname}:8000/api/logs/ws`
  statusWs = new WebSocket(wsUrl)
  statusWs.onopen = () => { connected.value = true }
  statusWs.onclose = () => {
    connected.value = false
    setTimeout(checkConnection, 5000)
  }
  statusWs.onmessage = (e) => {
    try {
      const d = JSON.parse(e.data)
      if (d.id) logCount.value++
    } catch {}
  }
}

onMounted(() => checkConnection())
onUnmounted(() => statusWs?.close())
</script>

<template>
  <Teleport to="body">
    <div class="log-tab" :class="{ on: connected }" @click="openLogWindow">
      <span v-if="logCount > 0" class="badge">{{ logCount > 99 ? '99+' : logCount }}</span>
    </div>
  </Teleport>
</template>

<style scoped>
.log-tab {
  position: fixed;
  right: 0;
  top: 50%;
  transform: translateY(-50%);
  z-index: 9999;
  width: 4px;
  height: 60px;
  background: #64748b;
  border-radius: 2px 0 0 2px;
  cursor: pointer;
  transition: all 0.15s;
  opacity: 0.25;
}

.log-tab:hover {
  opacity: 0.7;
  width: 6px;
}

.log-tab.on {
  background: #22c55e;
}

.badge {
  position: absolute;
  top: -8px;
  left: -10px;
  background: #ef4444;
  color: white;
  font-size: 8px;
  padding: 1px 3px;
  border-radius: 6px;
  min-width: 14px;
  text-align: center;
}
</style>
