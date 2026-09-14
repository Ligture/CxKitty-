"""任务相关 Pydantic 模型"""

from pydantic import BaseModel, Field
from typing import Optional


class TaskOverride(BaseModel):
    video_enable: Optional[bool] = None
    video_speed: Optional[float] = None
    video_report_rate: Optional[int] = None
    video_wait: Optional[int] = None
    work_enable: Optional[bool] = None
    work_export: Optional[bool] = None
    work_fallback_fuzzer: Optional[bool] = None
    work_fallback_save: Optional[bool] = None
    work_wait: Optional[int] = None
    document_enable: Optional[bool] = None
    document_wait: Optional[int] = None
    exam_fallback_fuzzer: Optional[bool] = None
    exam_confirm_submit: Optional[bool] = None
    exam_persubmit_delay: Optional[int] = None


class TaskStartRequest(BaseModel):
    course_indices: list[int] = Field(min_length=1)
    overrides: Optional[TaskOverride] = None


class ExamStartRequest(BaseModel):
    exam_index: int
    course_index: int
    export_only: bool = False
    overrides: Optional[TaskOverride] = None


class TaskStatusResponse(BaseModel):
    session_id: str = ""
    running: bool = False
    type: str = ""
    course_name: str = ""
    step: str = "idle"
