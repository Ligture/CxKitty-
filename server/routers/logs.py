"""日志路由"""

from fastapi import APIRouter, HTTPException

import config as cfg

router = APIRouter(prefix="/api", tags=["logs"])


@router.get("/logs")
def list_logs():
    """获取日志文件列表"""
    logs = []
    if cfg.LOGS_PATH.is_dir():
        for f in sorted(cfg.LOGS_PATH.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if f.suffix == ".log":
                logs.append({
                    "name": f.name,
                    "size": f.stat().st_size,
                    "modified": f.stat().st_mtime,
                })
    return {"ok": True, "data": logs}


@router.get("/logs/{filename}")
def read_log(filename: str):
    """读取日志内容 (末尾 500 行)"""
    file_path = cfg.LOGS_PATH / filename
    if not file_path.exists():
        raise HTTPException(404, "文件不存在")
    content = file_path.read_text(encoding="utf-8", errors="replace")
    lines = content.split("\n")
    tail_lines = lines[-500:] if len(lines) > 500 else lines
    return {"ok": True, "data": {
        "name": filename,
        "size": file_path.stat().st_size,
        "lines": len(lines),
        "content": "\n".join(tail_lines),
    }}
