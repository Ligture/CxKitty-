"""课程路由"""

from fastapi import APIRouter, HTTPException
from cxapi.chapters import ChapterContainer
from cxapi.classes import ClassContainer

from server.database import SessionManager

router = APIRouter(prefix="/api/sessions/{session_id}", tags=["courses"])


def _get_api(session_id: str):
    api = SessionManager.get_api(session_id)
    if not api or not api.acc:
        raise HTTPException(401, "未登录")
    return api


@router.get("/courses")
def list_courses(session_id: str):
    """获取课程列表"""
    api = _get_api(session_id)
    classes: ClassContainer = api.fetch_classes()
    courses = []
    for idx, cla in enumerate(classes.classes):
        courses.append({
            "index": idx,
            "course_id": cla.course_id,
            "class_id": cla.class_id,
            "name": cla.name,
            "teacher_name": cla.teacher_name,
            "state": cla.state.name,
            "state_value": cla.state.value,
        })
    return {"ok": True, "data": courses}


@router.get("/courses/{index}/chapters")
def get_chapters(session_id: str, index: int):
    """获取课程章节及完成状态"""
    api = _get_api(session_id)
    classes: ClassContainer = api.fetch_classes()
    if index < 0 or index >= len(classes.classes):
        raise HTTPException(400, "课程索引越界")
    class_meta = classes.classes[index]
    chapters_data = classes.get_chapters_by_index(index)
    chap = ChapterContainer(
        session=api.session,
        acc=api.acc,
        courseid=class_meta.course_id,
        classid=class_meta.class_id,
        name=class_meta.name,
        cpi=class_meta.cpi,
        chapters=chapters_data,
    )
    chap.fetch_point_status()
    chapters = []
    for ci, c in enumerate(chap.chapters):
        chapters.append({
            "index": ci,
            "chapter_id": c.chapter_id,
            "label": c.label,
            "name": c.name,
            "layer": c.layer,
            "point_total": c.point_total,
            "point_finished": c.point_finished,
            "is_finished": c.point_total > 0 and c.point_total == c.point_finished,
        })
    return {"ok": True, "data": {"course_name": class_meta.name, "chapters": chapters}}


@router.get("/courses/{index}/exams")
def get_exams(session_id: str, index: int):
    """获取课程考试列表"""
    api = _get_api(session_id)
    classes: ClassContainer = api.fetch_classes()
    if index < 0 or index >= len(classes.classes):
        raise HTTPException(400, "课程索引越界")
    exam_list = classes.get_exam_by_index(index)
    exams = []
    for ei, em in enumerate(exam_list):
        exams.append({
            "index": ei,
            "exam_id": em.exam_id,
            "name": em.name,
            "status": em.status.name,
            "expire_time": em.expire_time,
        })
    return {"ok": True, "data": exams}
