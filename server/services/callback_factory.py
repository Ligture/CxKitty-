"""
回调工厂 — 为 Resolver 创建 Socket.IO emit 回调 (实例化版本)

取代 WebUICallbacks 的类级别单例模式。
每个 CallbackFactory 实例绑定一个 session_id, 所有 emit 事件路由到对应 Socket.IO room。

线程安全: 使用 asyncio.run_coroutine_threadsafe() 从工作线程调度 async emit。
"""

import asyncio
import threading
import time
from typing import Callable

from server.database import TaskOrchestrator


# 全局: 服务启动时由 lifespan 注入主事件循环
_event_loop: asyncio.AbstractEventLoop | None = None


def set_event_loop(loop: asyncio.AbstractEventLoop):
    global _event_loop
    _event_loop = loop


class CallbackFactory:
    """每会话回调工厂 — 所有事件带 session_id 路由"""

    def __init__(self, session_id: str, sio_server=None):
        self.session_id = session_id
        self.sio = sio_server

    def set_sio(self, sio_server):
        """注入 Socket.IO server (如果构造时不可用)"""
        self.sio = sio_server

    def _emit(self, event: str, data: dict):
        """从工作线程 emit 到 session 专属 room + 仪表盘广播 room

        使用 asyncio.run_coroutine_threadsafe() 安全地从线程调度到主事件循环。
        """
        if not self.sio or not _event_loop:
            return
        try:
            payload = {"session_id": self.session_id, **data}
            summary = {
                "session_id": self.session_id,
                "event_type": event,
                "course_name": data.get("course_name", ""),
                "step": data.get("event", data.get("step", "")),
            }

            async def _do_emit():
                await self.sio.emit(event, payload, room=self.session_id)
                await self.sio.emit("dashboard:update", summary, room="dashboard")

            asyncio.run_coroutine_threadsafe(_do_emit(), _event_loop)
        except Exception:
            pass

    # --- QuestionResolver 回调 ---

    def make_question_progress(self) -> Callable:
        def cb(index, total, completed, incompleted, question, answer_status):
            self._emit("task:question", {
                "index": index,
                "total": total,
                "completed": completed,
                "incompleted": incompleted,
                "question_id": question.id,
                "question_value": question.value,
                "question_type": question.type.name,
                "options": question.options,
                "answer": question.answer,
                "status": answer_status,
            })
        return cb

    def make_question_submit(self) -> Callable:
        def cb(index, question, is_success, result_data):
            self._emit("task:question_submit", {
                "index": index,
                "question_id": question.id,
                "is_success": is_success,
                "result": str(result_data)[:500],
            })
        return cb

    def make_confirm_submit(self):
        def cb(completed_cnt, incompleted_cnt, mistakes, exam_dto):
            mistake_list = []
            for q, a in mistakes:
                mistake_list.append({
                    "question": q.value[:100],
                    "type": q.type.name,
                    "answer": str(a)[:100],
                })
            self._emit("task:confirm_needed", {
                "completed": completed_cnt,
                "incompleted": incompleted_cnt,
                "mistakes": mistake_list,
            })
            # 阻塞等待用户确认 (通过 TaskOrchestrator 的 per-session confirm_event)
            ts = TaskOrchestrator.get_or_create(self.session_id)
            ts.confirm_event = threading.Event()
            ts.confirm_result = [False]
            ts.confirm_event.wait(timeout=600)
            return ts.confirm_result[0]
        return cb

    # --- MediaPlayResolver 回调 ---

    def make_media_progress(self) -> Callable:
        def cb(playing_time, duration, speed, next_report_time):
            self._emit("task:video", {
                "playing_time": playing_time,
                "duration": duration,
                "speed": speed,
                "next_report_sec": next_report_time,
            })
        return cb

    def make_media_report(self) -> Callable:
        def cb(playing_time, duration, is_success, result_data):
            self._emit("task:video_report", {
                "playing_time": playing_time,
                "duration": duration,
                "is_success": is_success,
                "result": str(result_data)[:500],
            })
        return cb

    # --- Captcha / Face 回调 ---

    def make_captcha_after(self) -> Callable:
        def cb(times: int):
            self._emit("task:captcha", {"times": times, "status": "recognizing"})
        return cb

    def make_captcha_before(self) -> Callable:
        def cb(status: bool, code: str):
            if status:
                time.sleep(5.0)  # 匹配 TUI: 成功时等待服务器传播状态
            else:
                time.sleep(1.0)  # 匹配 TUI: 失败时短暂等待
            self._emit("task:captcha", {
                "status": "success" if status else "retry",
                "code": code,
            })
        return cb

    def make_face_after(self) -> Callable:
        def cb(orig_url: str):
            self._emit("task:face", {"status": "preparing", "url": orig_url})
        return cb

    def make_face_before(self) -> Callable:
        def cb(object_id: str, image_path):
            time.sleep(5.0)  # 匹配 TUI: 成功时等待
            self._emit("task:face", {
                "status": "success",
                "object_id": object_id,
                "path": str(image_path),
            })
        return cb

    def install_session_callbacks(self, api):
        """在 SessionWraper 上注册 captcha/face 回调 (每个 api 实例独立)"""
        api.session.reg_captcha_after(self.make_captcha_after())
        api.session.reg_captcha_before(self.make_captcha_before())
        api.session.reg_face_after(self.make_face_after())
        api.session.reg_face_before(self.make_face_before())
