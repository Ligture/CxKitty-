"""任务路由 — 启动 / 取消 / 状态"""

from fastapi import APIRouter, HTTPException, Request

from server.database import SessionManager, TaskOrchestrator
from server.models.tasks import TaskStartRequest, ExamStartRequest
from server.services.workers import run_task_worker, run_exam_worker

router = APIRouter(prefix="/api/sessions/{session_id}", tags=["tasks"])


def _require_session(session_id: str):
    if not SessionManager.get(session_id):
        raise HTTPException(401, "未登录或会话已失效")


def _get_sio(request: Request):
    """从 app.state 获取 Socket.IO server 实例"""
    return getattr(request.app.state, "sio", None)


@router.get("/tasks/status")
def get_task_status(session_id: str):
    """获取任务状态"""
    return {"ok": True, "data": TaskOrchestrator.get_status(session_id)}


@router.post("/tasks/start")
def start_task(session_id: str, req: TaskStartRequest, request: Request):
    """启动章节任务"""
    _require_session(session_id)
    if TaskOrchestrator.is_running(session_id):
        raise HTTPException(409, "该会话已有任务正在运行")

    api = SessionManager.get_api(session_id)
    course_name = ""
    try:
        classes = api.fetch_classes()
        if req.course_indices and req.course_indices[0] < len(classes.classes):
            course_name = classes.classes[req.course_indices[0]].name
    except Exception:
        pass

    overrides = req.overrides.model_dump(exclude_none=True) if req.overrides else {}
    TaskOrchestrator.start(
        session_id=session_id,
        target=run_task_worker,
        task_type="task",
        task_params={
            "session_id": session_id,
            "courses_indices": req.course_indices,
            "overrides": overrides,
            "course_name": course_name,
            "sio_server": _get_sio(request),
        },
    )
    return {"ok": True, "message": "任务已开始"}


@router.post("/tasks/start-exam")
def start_exam(session_id: str, req: ExamStartRequest, request: Request):
    """启动考试任务"""
    _require_session(session_id)
    if TaskOrchestrator.is_running(session_id):
        raise HTTPException(409, "该会话已有任务正在运行")

    overrides = req.overrides.model_dump(exclude_none=True) if req.overrides else {}
    TaskOrchestrator.start(
        session_id=session_id,
        target=run_exam_worker,
        task_type="exam",
        task_params={
            "session_id": session_id,
            "exam_index": req.exam_index,
            "course_index": req.course_index,
            "export_only": req.export_only,
            "overrides": overrides,
            "sio_server": _get_sio(request),
        },
    )
    return {"ok": True, "message": "考试任务已开始"}


@router.post("/tasks/cancel")
def cancel_task(session_id: str):
    """取消任务"""
    TaskOrchestrator.cancel(session_id)
    return {"ok": True, "message": "取消请求已发出"}
