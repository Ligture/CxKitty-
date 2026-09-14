"""会话管理 Pydantic 模型"""

from pydantic import BaseModel


class SessionSummary(BaseModel):
    index: int
    phone: str           # 脱敏手机号
    phone_raw: str = ""
    puid: int = 0
    name: str            # 脱敏姓名
    name_raw: str = ""
    has_passwd: bool = False


class ActiveSession(BaseModel):
    session_id: str
    display_name: str
    login_method: str = ""
    task_running: bool = False
    task_type: str = ""
    task_step: str = ""
    task_course_name: str = ""
