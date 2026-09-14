"""
CxKitty 多会话内存存储

SessionManager — 管理多个活跃 ChaoXingAPI 实例 (取代 SessionStore 单例)
TaskOrchestrator — 每会话任务状态管理 (取代 TaskManager 单例)
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from cxapi import ChaoXingAPI


# ---------------------------------------------------------------
# SessionManager
# ---------------------------------------------------------------


@dataclass
class SessionState:
    """单个活跃会话的状态"""
    session_id: str          # 手机号 (唯一键)
    api: ChaoXingAPI
    display_name: str        # 用于 UI 展示的名称
    login_method: str        # "password" | "qr" | "session"
    created_at: float = field(default_factory=time.time)


class SessionManager:
    """多会话管理器 (取代 SessionStore 单例)

    使用类级别 dict 存储所有活跃会话，支持线程安全的增删查。
    """

    _sessions: dict[str, SessionState] = {}
    _lock = threading.Lock()

    @classmethod
    def register(
        cls,
        session_id: str,
        api: ChaoXingAPI,
        display_name: str = "",
        login_method: str = "",
    ) -> str:
        """注册一个新会话 (或覆盖已有会话)"""
        with cls._lock:
            cls._sessions[session_id] = SessionState(
                session_id=session_id,
                api=api,
                display_name=display_name,
                login_method=login_method,
            )
        return session_id

    @classmethod
    def get(cls, session_id: str) -> Optional[SessionState]:
        """获取会话状态"""
        return cls._sessions.get(session_id)

    @classmethod
    def get_api(cls, session_id: str) -> Optional[ChaoXingAPI]:
        """获取会话的 API 实例"""
        state = cls._sessions.get(session_id)
        return state.api if state else None

    @classmethod
    def has_active(cls) -> bool:
        """是否有任何活跃会话"""
        return len(cls._sessions) > 0

    @classmethod
    def remove(cls, session_id: str) -> bool:
        """移除一个会话 (同时清理关联的任务状态)"""
        # 先取消该会话的任务
        TaskOrchestrator.cancel(session_id)
        TaskOrchestrator.cleanup(session_id)
        with cls._lock:
            return cls._sessions.pop(session_id, None) is not None

    @classmethod
    def list_all(cls) -> list[SessionState]:
        """列出所有活跃会话"""
        with cls._lock:
            return list(cls._sessions.values())

    @classmethod
    def get_all_statuses(cls) -> list[dict]:
        """获取所有会话的摘要 (供仪表盘 API 使用)"""
        from server.database import TaskOrchestrator
        with cls._lock:
            result = []
            for sid, state in cls._sessions.items():
                task_status = TaskOrchestrator.get_status(sid)
                result.append({
                    "session_id": sid,
                    "display_name": state.display_name,
                    "login_method": state.login_method,
                    "task_running": task_status.get("running", False),
                    "task_type": task_status.get("type", ""),
                    "task_step": task_status.get("step", ""),
                    "task_course_name": task_status.get("course_name", ""),
                })
            return result


# ---------------------------------------------------------------
# TaskOrchestrator
# ---------------------------------------------------------------


@dataclass
class TaskState:
    """单个会话的任务执行状态"""
    session_id: str
    thread: Optional[threading.Thread] = None
    cancel_flag: threading.Event = field(default_factory=threading.Event)
    confirm_event: Optional[threading.Event] = None
    confirm_result: list = field(default_factory=lambda: [False])
    task_type: str = ""          # "task" | "exam"
    course_name: str = ""
    step: str = "idle"           # "idle" | "starting" | "scanning" | "chapter" | "cancelling" | "done"
    _lock: threading.Lock = field(default_factory=threading.Lock)


class TaskOrchestrator:
    """每会话任务编排器 (取代 TaskManager 单例)

    每个 session_id 最多一个运行中任务。
    不同 session_id 之间的任务互不干扰。
    """

    _tasks: dict[str, TaskState] = {}
    _lock = threading.Lock()

    @classmethod
    def get_or_create(cls, session_id: str) -> TaskState:
        """获取或创建某会话的任务状态"""
        with cls._lock:
            if session_id not in cls._tasks:
                cls._tasks[session_id] = TaskState(session_id=session_id)
            return cls._tasks[session_id]

    @classmethod
    def start(
        cls,
        session_id: str,
        target: callable,
        task_type: str,
        task_params: dict,
    ):
        """为指定会话启动一个后台任务

        Raises:
            RuntimeError: 该会话已有运行中任务
        """
        ts = cls.get_or_create(session_id)
        if ts.thread and ts.thread.is_alive():
            raise RuntimeError(f"Session {session_id} already has a running task")
        ts.cancel_flag.clear()
        with ts._lock:
            ts.task_type = task_type
            ts.course_name = task_params.pop("course_name", "")
            ts.step = "starting"
        ts.thread = threading.Thread(
            target=target,
            kwargs=task_params,
            daemon=True,
            name=f"TaskWorker-{session_id}-{task_type}",
        )
        ts.thread.start()

    @classmethod
    def cancel(cls, session_id: str):
        """取消指定会话的任务"""
        ts = cls._tasks.get(session_id)
        if ts:
            ts.cancel_flag.set()
            with ts._lock:
                ts.step = "cancelling"

    @classmethod
    def finish(cls, session_id: str):
        """标记任务完成"""
        ts = cls._tasks.get(session_id)
        if ts:
            with ts._lock:
                ts.step = "done"
            ts.thread = None

    @classmethod
    def update_step(cls, session_id: str, step: str, course_name: str = ""):
        """更新任务步骤"""
        ts = cls._tasks.get(session_id)
        if ts:
            with ts._lock:
                ts.step = step
                if course_name:
                    ts.course_name = course_name

    @classmethod
    def get_status(cls, session_id: str) -> dict:
        """获取指定会话的任务状态"""
        ts = cls._tasks.get(session_id)
        if not ts:
            return {"running": False}
        with ts._lock:
            return {
                "running": ts.thread is not None and ts.thread.is_alive(),
                "type": ts.task_type,
                "course_name": ts.course_name,
                "step": ts.step,
            }

    @classmethod
    def is_running(cls, session_id: str) -> bool:
        """检查指定会话是否有运行中任务"""
        ts = cls._tasks.get(session_id)
        if not ts:
            return False
        return ts.thread is not None and ts.thread.is_alive()

    @classmethod
    def list_running_session_ids(cls) -> list[str]:
        """列出所有有运行中任务的会话 ID"""
        return [
            sid for sid, ts in cls._tasks.items()
            if ts.thread and ts.thread.is_alive()
        ]

    @classmethod
    def cleanup(cls, session_id: str):
        """清理指定会话的任务状态 (会话注销时调用)"""
        with cls._lock:
            ts = cls._tasks.pop(session_id, None)
            if ts and ts.thread and ts.thread.is_alive():
                ts.cancel_flag.set()
