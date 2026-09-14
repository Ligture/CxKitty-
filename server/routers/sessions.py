"""会话管理路由"""

from fastapi import APIRouter, HTTPException

import config as cfg
from utils import sessions_load, mask_phone, mask_name
from server.database import SessionManager

router = APIRouter(prefix="/api", tags=["sessions"])


@router.get("/sessions")
def list_sessions():
    """获取已保存会话列表"""
    sess_list = sessions_load()
    sessions = []
    for idx, s in enumerate(sess_list):
        sessions.append({
            "index": idx,
            "phone": mask_phone(s.phone),
            "phone_raw": s.phone,
            "puid": s.puid,
            "name": mask_name(s.name),
            "name_raw": s.name,
            "has_passwd": s.passwd is not None,
        })
    return {"ok": True, "data": sessions}


@router.get("/sessions/active")
def list_active_sessions():
    """获取当前活跃会话列表 (仪表盘用)"""
    return {"ok": True, "data": SessionManager.get_all_statuses()}


@router.delete("/sessions/{index}")
def delete_session(index: int):
    """删除已保存会话"""
    sess_list = sessions_load()
    if index < 0 or index >= len(sess_list):
        raise HTTPException(400, "索引越界")
    phone = sess_list[index].phone
    file_path = cfg.SESSIONS_PATH / f"{phone}.json"
    if file_path.exists():
        file_path.unlink()
    return {"ok": True, "message": "会话已删除"}
