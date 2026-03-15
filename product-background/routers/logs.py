"""
日志系统 - 详细可读的实时日志
"""

import asyncio
import logging
import json
from datetime import datetime
from typing import Set, Optional, List, Dict, Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from collections import deque

router = APIRouter(prefix="/api/logs", tags=["Logs"])

# 存储日志
recent_logs: deque = deque(maxlen=500)
active_connections: Set[WebSocket] = set()
_log_id = 0


def _create_log(
    level: str,
    title: str,
    detail: str = None,
    data: Any = None,
    step: str = None
) -> dict:
    """
    创建日志条目

    Args:
        level: 级别 info/success/warn/error
        title: 标题（简短描述）
        detail: 详情文本
        data: 结构化数据（会被JSON序列化）
        step: 步骤标识 如 "1/3"
    """
    global _log_id
    _log_id += 1

    # 序列化 data
    data_str = None
    if data is not None:
        try:
            if isinstance(data, str):
                data_str = data
            else:
                data_str = json.dumps(data, ensure_ascii=False, indent=2, default=str)
        except:
            data_str = str(data)

    return {
        "id": _log_id,
        "time": datetime.now().strftime("%H:%M:%S.%f")[:-3],
        "level": level,
        "title": title,
        "detail": detail,
        "data": data_str,
        "step": step
    }


async def _broadcast(log: dict):
    """广播日志"""
    if not active_connections:
        return

    msg = json.dumps(log, ensure_ascii=False)
    dead = set()

    for conn in active_connections:
        try:
            await conn.send_text(msg)
        except:
            dead.add(conn)

    for c in dead:
        active_connections.discard(c)


def _send(log: dict):
    """发送日志"""
    recent_logs.append(log)
    # 同时打印到控制台
    print(f"[{log['time']}] [{log['level'].upper()}] {log['title']}")
    if log.get('detail'):
        print(f"    {log['detail']}")
    if log.get('data'):
        for line in str(log['data']).split('\n')[:5]:
            print(f"    {line}")

    # 广播到 WebSocket
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_broadcast(log))
    except RuntimeError:
        # 没有运行中的事件循环
        pass


# ============================================================
# 日志 API
# ============================================================

def log_info(title: str, detail: str = None, data: Any = None, step: str = None):
    """信息日志"""
    _send(_create_log("info", title, detail, data, step))

def log_success(title: str, detail: str = None, data: Any = None, step: str = None):
    """成功日志"""
    _send(_create_log("success", title, detail, data, step))

def log_warn(title: str, detail: str = None, data: Any = None, step: str = None):
    """警告日志"""
    _send(_create_log("warn", title, detail, data, step))

def log_error(title: str, detail: str = None, data: Any = None, step: str = None):
    """错误日志"""
    _send(_create_log("error", title, detail, data, step))


# ============================================================
# 业务日志 - 请求/响应
# ============================================================

def log_request(endpoint: str, method: str = "POST", params: Dict = None):
    """记录请求"""
    _send(_create_log(
        "info",
        f"→ {method} {endpoint}",
        detail=None,
        data=params
    ))

def log_response(endpoint: str, success: bool, result: Any = None, error: str = None):
    """记录响应"""
    if success:
        _send(_create_log(
            "success",
            f"← {endpoint} 成功",
            detail=None,
            data=result
        ))
    else:
        _send(_create_log(
            "error",
            f"← {endpoint} 失败",
            detail=error,
            data=None
        ))


# ============================================================
# 业务日志 - 技能执行
# ============================================================

def log_skill_start(name: str, params: Dict = None):
    """技能开始"""
    _send(_create_log(
        "info",
        f"▶ 技能开始: {name}",
        detail=None,
        data=params,
        step="开始"
    ))

def log_skill_step(name: str, step: str, detail: str = None, data: Any = None):
    """技能步骤"""
    _send(_create_log(
        "info",
        f"◐ {name}: {step}",
        detail=detail,
        data=data,
        step=step
    ))

def log_skill_success(name: str, result: Any = None):
    """技能成功"""
    _send(_create_log(
        "success",
        f"✓ 技能完成: {name}",
        detail=None,
        data=result,
        step="完成"
    ))

def log_skill_error(name: str, error: str, detail: str = None):
    """技能失败"""
    _send(_create_log(
        "error",
        f"✕ 技能失败: {name}",
        detail=error,
        data=detail,
        step="错误"
    ))


# ============================================================
# 业务日志 - AI
# ============================================================

def log_ai_start(prompt_preview: str = None):
    """AI 开始"""
    _send(_create_log(
        "info",
        "🤖 AI 处理中...",
        detail=prompt_preview[:100] + "..." if prompt_preview and len(prompt_preview) > 100 else prompt_preview
    ))

def log_ai_done(response_preview: str = None):
    """AI 完成"""
    _send(_create_log(
        "success",
        "🤖 AI 响应完成",
        detail=response_preview[:200] + "..." if response_preview and len(response_preview) > 200 else response_preview
    ))


# ============================================================
# 业务日志 - 文件
# ============================================================

def log_file_read(path: str, size: int = None):
    """读取文件"""
    detail = f"大小: {size} bytes" if size else None
    _send(_create_log("info", f"📄 读取文件: {path}", detail=detail))

def log_file_write(path: str, size: int = None):
    """写入文件"""
    detail = f"大小: {size} bytes" if size else None
    _send(_create_log("success", f"📄 生成文件: {path}", detail=detail))


# ============================================================
# WebSocket 端点
# ============================================================

@router.websocket("/ws")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    active_connections.add(websocket)
    print(f"[LOG] WebSocket 客户端连接，当前: {len(active_connections)}")

    try:
        # 发送最近日志
        logs_to_send = list(recent_logs)[-100:]
        for log in logs_to_send:
            await websocket.send_text(json.dumps(log, ensure_ascii=False))

        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                if data == "ping":
                    await websocket.send_text('{"type":"pong"}')
            except asyncio.TimeoutError:
                await websocket.send_text('{"type":"heartbeat"}')
    except WebSocketDisconnect:
        pass
    finally:
        active_connections.discard(websocket)
        print(f"[LOG] WebSocket 客户端断开，剩余: {len(active_connections)}")


@router.get("/recent")
async def get_recent(limit: int = 100):
    return {"logs": list(recent_logs)[-limit:]}


@router.delete("/clear")
async def clear():
    recent_logs.clear()
    return {"ok": True}


# ============================================================
# 兼容 Python logging
# ============================================================

class LogHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            if any(x in msg for x in ["GET /api/logs", "WebSocket", "uvicorn.access"]):
                return

            level = record.levelname.lower()
            if level == "warning":
                level = "warn"

            _send(_create_log(level, msg))
        except:
            pass


def setup_log_handler():
    handler = LogHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter('%(name)s: %(message)s'))
    logging.getLogger().addHandler(handler)
    return handler


# ============================================================
# 系统日志
# ============================================================

def sys_ready():
    """系统就绪"""
    _send(_create_log("success", "✓ 系统启动完成", detail="AI Skills Platform Ready"))
