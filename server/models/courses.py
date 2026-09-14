"""课程相关 Pydantic 模型"""

from pydantic import BaseModel
from typing import Optional


class CourseModel(BaseModel):
    index: int
    course_id: str
    class_id: str
    name: str
    teacher_name: str = ""
    state: str = ""           # "进行中" | "已结束"
    state_value: int = 0      # 0=active, 1=ended


class ChapterModel(BaseModel):
    index: int
    chapter_id: str
    label: str                # e.g. "1.1"
    name: str
    layer: int = 0
    point_total: int = 0
    point_finished: int = 0
    is_finished: bool = False


class CourseChaptersResponse(BaseModel):
    course_name: str
    chapters: list[ChapterModel]


class ExamModel(BaseModel):
    index: int
    exam_id: str
    name: str
    status: str = ""
    expire_time: str = ""
