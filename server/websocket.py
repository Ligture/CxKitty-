"""WebSocket 事件处理 — Socket.IO 异步服务端"""

import asyncio

import socketio

from server.database import TaskOrchestrator
from server.services.callback_factory import set_event_loop

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")


@sio.event
async def connect(sid, environ, auth):
    """客户端连接 — 同时捕获事件循环供工作线程使用"""
    try:
        set_event_loop(asyncio.get_running_loop())
    except RuntimeError:
        pass
    await sio.emit("connected", {"message": "WebSocket 已连接"}, to=sid)


@sio.event
async def join_session(sid, data):
    """客户端请求监听特定会话的事件
    data = {"session_id": "138xxxxxxxxx"}
    """
    session_id = data.get("session_id") if data else None
    if session_id:
        await sio.enter_room(sid, session_id)


@sio.event
async def leave_session(sid, data):
    """客户端停止监听特定会话"""
    session_id = data.get("session_id") if data else None
    if session_id:
        await sio.leave_room(sid, session_id)


@sio.event
async def join_dashboard(sid):
    """客户端加入仪表盘广播 room"""
    await sio.enter_room(sid, "dashboard")


@sio.event
async def task_confirm_submit(sid, data):
    """前端回复考试交卷确认
    data = {"session_id": "138xxxxxxxxx", "confirmed": true/false}
    """
    if not data:
        return
    session_id = data.get("session_id")
    confirmed = data.get("confirmed", False)
    ts = TaskOrchestrator._tasks.get(session_id)
    if ts:
        ts.confirm_result[0] = confirmed
        if ts.confirm_event:
            ts.confirm_event.set()


@sio.event
async def disconnect(sid):
    """客户端断开连接 (room 自动清理)"""
    pass
