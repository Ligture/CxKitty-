"""
Worker 函数 — 从 webui_backend.py 移植并适配多会话架构

关键变更:
- 所有函数接受 session_id 作为第一个参数
- 使用 SessionManager.get_api(session_id) 而非 SessionStore.get()
- 使用 TaskOrchestrator (per-session) 而非 TaskManager (全局单例)
- 使用 CallbackFactory 实例 (per-session) 而非 WebUICallbacks 类方法
- 使用 ConfigService.get_snapshot() 而非 config.reload_config()
"""

import threading
import time
import traceback

import config
from cxapi import ChaoXingAPI
from cxapi.chapters import ChapterContainer
from cxapi.classes import ClassContainer
from cxapi.exam import ExamDto
from cxapi.exception import APIError, ChapterNotOpened, TaskPointError
from cxapi.task_point import PointDocumentDto, PointVideoDto, PointWorkDto
from logger import Logger
from resolver import DocumetResolver, MediaPlayResolver, QuestionResolver
from resolver.question import clear_searcher_cache

from server.database import SessionManager, TaskOrchestrator
from server.services.callback_factory import CallbackFactory
from server.services.config_service import ConfigService

logger = Logger("Worker")


def _task_wait(wait_sec: int, text: str, callback_factory: CallbackFactory, task_state) -> None:
    """课间等待，逐秒发 tick (多会话适配版)"""
    for i in range(wait_sec):
        if task_state.cancel_flag.is_set():
            return
        callback_factory._emit("task:wait", {
            "seconds_remaining": wait_sec - i,
            "message": text,
        })
        time.sleep(1.0)


def run_task_worker(
    session_id: str,
    courses_indices: list[int],
    overrides: dict | None = None,
    sio_server=None,
):
    """章节任务 worker (多会话版)

    Args:
        session_id: 会话标识 (手机号)
        courses_indices: 课程索引列表
        overrides: 临时覆盖配置
        sio_server: Socket.IO server 实例 (用于 emit)
    """
    api = SessionManager.get_api(session_id)
    if not api or not api.acc:
        if sio_server:
            sio_server.emit("task:error", {"session_id": session_id, "error": "未登录"}, room=session_id)
        TaskOrchestrator.finish(session_id)
        return

    overrides = overrides or {}
    factory = CallbackFactory(session_id, sio_server)
    ts = TaskOrchestrator.get_or_create(session_id)

    try:
        # 加载配置快照 + 清除搜索器缓存
        cfg_snapshot = ConfigService.get_snapshot()
        clear_searcher_cache()

        classes: ClassContainer = api.fetch_classes()
        factory.install_session_callbacks(api)

        logger.info(f"[{session_id}] WebUI 任务开始: 共 {len(courses_indices)} 门课程")

        for idx in courses_indices:
            if ts.cancel_flag.is_set():
                break

            class_meta = classes.classes[idx]
            course_name = class_meta.name
            TaskOrchestrator.update_step(session_id, "scanning", course_name)

            chapters_data = classes.get_chapters_by_index(idx)
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

            # 发送章节概览
            chapter_list = []
            for ci, c in enumerate(chap.chapters):
                chapter_list.append({
                    "index": ci,
                    "label": c.label,
                    "name": c.name,
                    "point_total": c.point_total,
                    "point_finished": c.point_finished,
                    "layer": c.layer,
                })
            factory._emit("task:progress", {
                "event": "chapters_loaded",
                "course_name": course_name,
                "chapters": chapter_list,
                "total_chapters": len(chap),
            })

            # 找到第一个未完成章节，跳过已全部完成的章节
            start_ci = 0
            for ci in range(len(chap)):
                if not chap.is_finished(ci):
                    start_ci = ci
                    break
            else:
                continue  # 全部章节已完成，跳过这门课

            # 从第一个未完成章节开始遍历
            for ci in range(start_ci, len(chap)):
                if ts.cancel_flag.is_set():
                    break
                TaskOrchestrator.update_step(session_id, "chapter", course_name)

                # 始终跳过已全部完成的章节
                if chap.is_finished(ci):
                    continue

                refresh_flag = True
                task_points = chap[ci]

                for tpi, task_point in enumerate(task_points):
                    if ts.cancel_flag.is_set():
                        break
                    try:
                        task_point.fetch_attachment()
                    except ChapterNotOpened:
                        if refresh_flag:
                            chap.refresh_chapter(ci - 1)
                            refresh_flag = False
                            continue
                        else:
                            factory._emit("task:error", {
                                "error": "章节未开放",
                                "detail": f"{chap.chapters[ci].label} {chap.chapters[ci].name}",
                            })
                            break
                    refresh_flag = True

                    try:
                        current_chapter = chap.chapters[ci]
                        chapter_info = {
                            "chapter_index": ci,
                            "chapter_label": current_chapter.label,
                            "chapter_name": current_chapter.name,
                            "task_point_index": tpi,
                        }

                        # --- 测验任务点 ---
                        if isinstance(task_point, PointWorkDto):
                            work_cfg = cfg_snapshot.get("work", {})
                            work_en = overrides.get("work_enable", work_cfg.get("enable", True))
                            work_export = overrides.get("work_export", work_cfg.get("export", True))

                            if work_export and not work_en:
                                task_point.parse_attachment()
                                task_point.export(config.EXPORT_PATH / f"work_{task_point.work_id}.json")

                            if work_en:
                                if not task_point.parse_attachment():
                                    continue
                                task_point.fetch_all()
                                factory._emit("task:progress", {
                                    "event": "quiz_start",
                                    "course_name": course_name,
                                    "quiz_title": task_point.title,
                                    "total_questions": len(task_point.questions),
                                    **chapter_info,
                                })
                                resolver = QuestionResolver(
                                    exam_dto=task_point,
                                    fallback_save=overrides.get("fallback_save", work_cfg.get("fallback_save", True)),
                                    fallback_fuzzer=overrides.get("fallback_fuzzer", work_cfg.get("fallback_fuzzer", False)),
                                    cb_progress=factory.make_question_progress(),
                                    cb_submit=factory.make_question_submit(),
                                )
                                resolver.execute()
                                factory._emit("task:progress", {
                                    "event": "quiz_done",
                                    "course_name": course_name,
                                    "quiz_title": task_point.title,
                                    "completed": resolver.completed_cnt,
                                    "incompleted": resolver.incompleted_cnt,
                                    **chapter_info,
                                })
                                _task_wait(
                                    overrides.get("work_wait", work_cfg.get("wait", 15)),
                                    f"试题《{task_point.title}》已结束",
                                    factory, ts,
                                )

                        # --- 视频任务点 ---
                        elif isinstance(task_point, PointVideoDto):
                            video_cfg = cfg_snapshot.get("video", {})
                            video_en = overrides.get("video_enable", video_cfg.get("enable", True))
                            if not video_en:
                                continue
                            if not task_point.parse_attachment():
                                continue
                            if not task_point.fetch():
                                continue
                            factory._emit("task:progress", {
                                "event": "video_start",
                                "course_name": course_name,
                                "video_title": task_point.title,
                                "duration": task_point.duration,
                                **chapter_info,
                            })
                            resolver = MediaPlayResolver(
                                media_dto=task_point,
                                speed=overrides.get("video_speed", video_cfg.get("speed", 1.0)),
                                report_rate=overrides.get("video_report_rate", video_cfg.get("report_rate", 58)),
                                cb_progress=factory.make_media_progress(),
                                cb_report=factory.make_media_report(),
                            )
                            resolver.execute()
                            factory._emit("task:progress", {
                                "event": "video_done",
                                "course_name": course_name,
                                "video_title": task_point.title,
                                **chapter_info,
                            })
                            _task_wait(
                                overrides.get("video_wait", video_cfg.get("wait", 15)),
                                f"视频《{task_point.title}》已结束",
                                factory, ts,
                            )

                        # --- 文档任务点 ---
                        elif isinstance(task_point, PointDocumentDto):
                            doc_cfg = cfg_snapshot.get("document", {})
                            doc_en = overrides.get("document_enable", doc_cfg.get("enable", True))
                            if not doc_en:
                                continue
                            if not task_point.parse_attachment():
                                continue
                            factory._emit("task:progress", {
                                "event": "document_start",
                                "course_name": course_name,
                                "document_title": task_point.title,
                                **chapter_info,
                            })
                            resolver = DocumetResolver(document_dto=task_point)
                            resolver.execute()
                            factory._emit("task:progress", {
                                "event": "document_done",
                                "course_name": course_name,
                                "document_title": task_point.title,
                                **chapter_info,
                            })
                            _task_wait(
                                overrides.get("document_wait", doc_cfg.get("wait", 15)),
                                f"文档《{task_point.title}》已结束",
                                factory, ts,
                            )

                    except (TaskPointError, NotImplementedError) as e:
                        logger.error(f"[{session_id}] 任务点异常: {e}")
                        factory._emit("task:error", {
                            "error": str(e),
                            "detail": traceback.format_exc()[:500],
                        })

                    # 刷新任务点状态
                    chap.fetch_point_status()
                    chapter_list = []
                    for cii, c in enumerate(chap.chapters):
                        chapter_list.append({
                            "index": cii,
                            "label": c.label,
                            "name": c.name,
                            "point_total": c.point_total,
                            "point_finished": c.point_finished,
                        })
                    factory._emit("task:progress", {
                        "event": "chapters_updated",
                        "course_name": course_name,
                        "chapters": chapter_list,
                    })

            # 课程完成
            factory._emit("task:complete", {"course_name": course_name, "status": "success"})

        factory._emit("task:complete", {"status": "all_done"})

    except Exception as e:
        logger.error(f"[{session_id}] 任务异常: {e}")
        factory._emit("task:error", {
            "error": str(e),
            "detail": traceback.format_exc()[:1000],
        })
    finally:
        TaskOrchestrator.finish(session_id)


def run_exam_worker(
    session_id: str,
    exam_index: int,
    course_index: int,
    export_only: bool = False,
    overrides: dict | None = None,
    sio_server=None,
):
    """考试任务 worker (多会话版)

    Args:
        session_id: 会话标识 (手机号)
        exam_index: 考试在列表中的索引
        course_index: 课程在 classes 中的索引
        export_only: 仅导出试卷
        overrides: 临时覆盖配置
        sio_server: Socket.IO server 实例
    """
    api = SessionManager.get_api(session_id)
    if not api or not api.acc:
        if sio_server:
            sio_server.emit("task:error", {"session_id": session_id, "error": "未登录"}, room=session_id)
        TaskOrchestrator.finish(session_id)
        return

    overrides = overrides or {}
    factory = CallbackFactory(session_id, sio_server)

    try:
        cfg_snapshot = ConfigService.get_snapshot()
        clear_searcher_cache()

        classes: ClassContainer = api.fetch_classes()
        factory.install_session_callbacks(api)

        exams_list = classes.get_exam_by_index(course_index)
        if exam_index >= len(exams_list):
            factory._emit("task:error", {"error": "考试索引越界"})
            TaskOrchestrator.finish(session_id)
            return

        exam_meta = exams_list[exam_index]
        class_meta = classes.classes[course_index]

        exam = ExamDto(
            session=api.session,
            acc=api.acc,
            exam_id=exam_meta.exam_id,
            course_id=class_meta.course_id,
            class_id=class_meta.class_id,
            cpi=class_meta.cpi,
            enc_task=exam_meta.enc_task,
        )

        exam.get_meta()

        if export_only:
            export_path = config.EXPORT_PATH / f"exam_{exam.exam_id}.json"
            exam.export(export_path)
            factory._emit("task:exam_exported", {
                "exam_title": exam.title,
                "path": str(export_path),
                "remain_time": exam.remain_time_str,
            })
            TaskOrchestrator.finish(session_id)
            return

        exam.start()

        # 发送考试元数据
        answer_sheet = exam.get_answer_sheet()
        total_questions = sum(len(v) for v in answer_sheet.values())
        factory._emit("task:exam_meta", {
            "title": exam.title,
            "remain_time": exam.remain_time_str,
            "total_questions": total_questions,
            "answer_sheet": answer_sheet,
        })

        exam_cfg = cfg_snapshot.get("exam", {})
        resolver = QuestionResolver(
            exam_dto=exam,
            fallback_save=False,
            fallback_fuzzer=overrides.get("exam_fallback_fuzzer", exam_cfg.get("fallback_fuzzer", False)),
            persubmit_delay=overrides.get("exam_persubmit_delay", exam_cfg.get("persubmit_delay", 15)),
            cb_progress=factory.make_question_progress(),
            cb_submit=factory.make_question_submit(),
        )

        if overrides.get("exam_confirm_submit", exam_cfg.get("confirm_submit", True)):
            resolver.reg_confirm_submit_cb(factory.make_confirm_submit())

        resolver.execute()

        # 如果设置了确认提交但用户未响应
        ts = TaskOrchestrator.get_or_create(session_id)
        if ts.confirm_event and not ts.confirm_event.is_set():
            factory._emit("task:complete", {
                "status": "exam_done",
                "title": exam.title,
                "auto_submitted": True,
            })

    except Exception as e:
        logger.error(f"[{session_id}] 考试任务异常: {e}")
        factory._emit("task:error", {
            "error": str(e),
            "detail": traceback.format_exc()[:1000],
        })
    finally:
        TaskOrchestrator.finish(session_id)
