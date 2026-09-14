"""认证相关 Pydantic 模型"""

from pydantic import BaseModel, Field


class LoginPasswdRequest(BaseModel):
    phone: str = Field(min_length=11, max_length=11, description="手机号")
    password: str = Field(min_length=1, description="密码")


class LoginSessionRequest(BaseModel):
    index: int = Field(ge=0, description="已保存会话的索引")


class LoginReloginRequest(BaseModel):
    index: int = Field(ge=0, description="已保存会话的索引")


class QRInitResponse(BaseModel):
    session_id: str
    qr_url: str


class QRPollResponse(BaseModel):
    status: str  # "waiting" | "scanned" | "confirmed" | "expired"
    type: str = ""
    nickname: str = ""
    uid: str = ""


class AccountInfoResponse(BaseModel):
    puid: int
    name: str
    sex: str
    phone: str
    school: str
    stu_id: str = ""


class LoginSuccessResponse(BaseModel):
    session_id: str
    account: AccountInfoResponse
    message: str = "登录成功"


class ApiResponse(BaseModel):
    ok: bool
    data: object = None
    error: str | None = None
    message: str = ""
