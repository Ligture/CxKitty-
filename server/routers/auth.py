"""认证路由 — 登录 / 登出"""

from fastapi import APIRouter, HTTPException
from cxapi import ChaoXingAPI
from utils import save_session, sessions_load, ck2dict, mask_phone, mask_name

from server.database import SessionManager
from server.models.auth import (
    LoginPasswdRequest, LoginSessionRequest, LoginReloginRequest,
    QRInitResponse, QRPollResponse, AccountInfoResponse, LoginSuccessResponse,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _accinfo_dict(api: ChaoXingAPI) -> dict:
    acc = api.acc
    return {
        "puid": acc.puid,
        "name": acc.name,
        "sex": acc.sex.name,
        "phone": mask_phone(acc.phone),
        "school": acc.school,
        "stu_id": acc.stu_id,
    }


@router.post("/login/passwd")
def login_passwd(req: LoginPasswdRequest):
    """手机号 + 密码登录"""
    api = ChaoXingAPI()
    ok, resp_data = api.login_passwd(req.phone, req.password)
    if not ok:
        msg = resp_data.get("msg2", resp_data.get("msg", "登录失败"))
        raise HTTPException(401, msg)
    api.accinfo()
    save_session(api.session.ck_dump(), api.acc, req.password)
    session_id = api.acc.phone
    SessionManager.register(session_id, api, display_name=api.acc.name, login_method="password")
    return {"ok": True, "data": {
        "session_id": session_id,
        "account": _accinfo_dict(api),
    }}


@router.post("/login/qr/init")
def login_qr_init():
    """初始化二维码登录"""
    api = ChaoXingAPI()
    api.qr_get()
    qr_url = api.qr_geturl()
    session_id = f"qr_{api.qr_uuid}"
    SessionManager.register(session_id, api, login_method="qr")
    return {"ok": True, "data": {"session_id": session_id, "qr_url": qr_url}}


@router.get("/login/qr/{session_id}/poll")
def login_qr_poll(session_id: str):
    """轮询二维码登录状态"""
    api = SessionManager.get_api(session_id)
    if not api:
        raise HTTPException(400, "请先初始化二维码")
    qr_status = api.login_qr()
    result = {"status": qr_status.get("status"), "type": qr_status.get("type")}
    if qr_status.get("status") is True:
        api.accinfo()
        save_session(api.session.ck_dump(), api.acc)
        result["acc"] = _accinfo_dict(api)
        # 用真实手机号作为 session_id
        real_id = api.acc.phone
        SessionManager.remove(session_id)
        SessionManager.register(real_id, api, display_name=api.acc.name, login_method="qr")
        result["session_id"] = real_id
    elif qr_status.get("type") == "4":
        result["nickname"] = qr_status.get("nickname", "")
        result["uid"] = qr_status.get("uid", "")
    return {"ok": True, "data": result}


@router.post("/login/session")
def login_session(req: LoginSessionRequest):
    """从已保存会话恢复登录"""
    sess_list = sessions_load()
    if req.index < 0 or req.index >= len(sess_list):
        raise HTTPException(400, "会话索引越界")
    session_data = sess_list[req.index]
    api = ChaoXingAPI()
    ck = ck2dict(session_data.ck)
    api.session.ck_load(ck)
    if not api.accinfo():
        if session_data.passwd:
            ok, resp_data = api.login_passwd(session_data.phone, session_data.passwd)
            if not ok:
                raise HTTPException(401, "会话已失效，自动重登失败")
            api.accinfo()
            save_session(api.session.ck_dump(), api.acc, session_data.passwd)
        else:
            raise HTTPException(401, "会话已失效且无保存的密码，请手动登录")
    session_id = api.acc.phone
    SessionManager.register(session_id, api, display_name=api.acc.name, login_method="session")
    return {"ok": True, "data": {
        "session_id": session_id,
        "account": _accinfo_dict(api),
    }}


@router.post("/login/relogin")
def login_relogin(req: LoginReloginRequest):
    """强制重新登录"""
    sess_list = sessions_load()
    if req.index < 0 or req.index >= len(sess_list):
        raise HTTPException(400, "会话索引越界")
    session_data = sess_list[req.index]
    if not session_data.passwd:
        raise HTTPException(400, "该会话没有保存密码")
    api = ChaoXingAPI()
    api.session.ck_clear()
    ok, resp_data = api.login_passwd(session_data.phone, session_data.passwd)
    if not ok:
        raise HTTPException(401, resp_data.get("msg2", "重登失败"))
    api.accinfo()
    save_session(api.session.ck_dump(), api.acc, session_data.passwd)
    session_id = api.acc.phone
    SessionManager.register(session_id, api, display_name=api.acc.name, login_method="relogin")
    return {"ok": True, "data": {
        "session_id": session_id,
        "account": _accinfo_dict(api),
    }}


@router.delete("/logout/{session_id}")
def logout(session_id: str):
    """注销会话"""
    SessionManager.remove(session_id)
    return {"ok": True, "message": "会话已注销"}
