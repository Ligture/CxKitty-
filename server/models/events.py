"""WebSocket 事件载荷模型

所有服务端→客户端事件 payload 均包含 session_id 字段，
以便前端按会话路由到正确的 UI 面板。
"""

from pydantic import BaseModel
from typing import Optional


class BaseEvent(BaseModel):
    session_id: str


# --- 任务进度 ---

class TaskProgressEvent(BaseEvent):
    event: str  # "chapters_loaded" | "chapters_updated" | "quiz_start" | "quiz_done"
                # | "video_start" | "video_done" | "document_start" | "document_done"
    course_name: str = ""
    chapters: Optional[list[dict]] = None
    total_chapters: Optional[int] = None
    chapter_index: Optional[int] = None
    chapter_label: Optional[str] = None
    chapter_name: Optional[str] = None
    task_point_index: Optional[int] = None
    quiz_title: Optional[str] = None
    total_questions: Optional[int] = None
    video_title: Optional[str] = None
    duration: Optional[int] = None
    document_title: Optional[str] = None
    completed: Optional[int] = None
    incompleted: Optional[int] = None


# --- 题目 ---

class QuestionEvent(BaseEvent):
    index: int = 0
    total: int = 0
    completed: int = 0
    incompleted: int = 0
    question_id: str = ""
    question_value: str = ""
    question_type: str = ""
    options: Optional[dict] = None
    answer: str = ""
    status: bool = False  # matched or not


class QuestionResultEvent(BaseEvent):
    index: int = 0
    question_id: str = ""
    success: bool = False
    result: str = ""


# --- 视频 ---

class VideoEvent(BaseEvent):
    playing_time: int = 0
    duration: int = 0
    speed: float = 1.0
    next_report_sec: int = 0


class VideoReportEvent(BaseEvent):
    playing_time: int = 0
    duration: int = 0
    success: bool = False
    result: str = ""


# --- 验证码 / 人脸 ---

class CaptchaEvent(BaseEvent):
    status: str = ""  # "recognizing" | "success" | "retry"
    times: Optional[int] = None
    code: Optional[str] = None


class FaceEvent(BaseEvent):
    status: str = ""  # "preparing" | "success"
    url: Optional[str] = None
    object_id: Optional[str] = None
    path: Optional[str] = None


# --- 等待 ---

class WaitEvent(BaseEvent):
    seconds_remaining: int = 0
    message: str = ""


# --- 考试 ---

class ExamMetaEvent(BaseEvent):
    title: str = ""
    remain_time: int = 0
    total_questions: int = 0
    answer_sheet: Optional[dict] = None


class ConfirmNeededEvent(BaseEvent):
    completed: int = 0
    incompleted: int = 0
    mistakes: list[dict] = []


# --- 完成 / 错误 ---

class TaskCompleteEvent(BaseEvent):
    status: str = ""    # "success" | "all_done" | "exam_done"
    course_name: str = ""
    title: str = ""
    auto_submitted: bool = False


class TaskErrorEvent(BaseEvent):
    error: str = ""
    detail: Optional[str] = None


# --- 仪表盘 ---

class DashboardUpdateEvent(BaseModel):
    session_id: str
    event_type: str = ""
    course_name: str = ""
    step: str = ""


# --- 配置 ---

class ConfigUpdatedEvent(BaseModel):
    section: Optional[str] = None
    message: str = ""


# --- 客户端→服务端 ---

class ConfirmSubmitRequest(BaseModel):
    session_id: str
    confirmed: bool


class JoinSessionRequest(BaseModel):
    session_id: str
