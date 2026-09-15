"""后台转录 worker

单线程队列串行消费: 下载视频 -> ffmpeg 提取音频 -> SenseVoiceSmall 转录 -> 写缓存 -> 注册章节文稿。

设计约束(见 docs/video-transcript-plan.md §7):
* 单 worker 串行, 不并发下载/转录, 避免 CPU/IO 争抢与风控
* 模型懒加载, 进程内单例复用
* worker 线程绝不触碰 rich Live/Layout, 进度只走 logger
* 任何环节失败都只记录日志并放弃当前任务, 不影响刷课主流程
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import logging
import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import config as cfg
from logger import Logger

from . import context
from .asr import LocalSenseVoiceTranscriber, model_root_status
from .cache import TranscriptCache, TranscriptRecord
from .downloader import audio_path, download_file, video_path
from .errors import TranscriptError, TranscriptionError
from .extractor import extract_audio, ffmpeg_status
from .remote import DEFAULT_SERVICE_URL, RemoteSenseVoiceTranscriber, probe_service

_DEFAULT_SETTINGS = {
    "enable": False,
    # local = 进程内加载模型; service = 交给独立的 transcript.server 进程(多账号复用同一份模型)
    "mode": "local",
    "service_url": "",
    "service_token": "",
    "service_timeout": 900,
    "service_fallback_local": False,
    "model_root": "",
    "device": "auto",
    "language": "auto",
    "use_itn": True,
    "cache_path": "transcripts/",
    "video_path": "videos/",
    "audio_path": "audios/",
    "keep_video": False,
    "keep_audio": False,
}
_STOP = object()
_worker_lock = threading.Lock()
_worker: Optional["TranscriptWorker"] = None


def settings() -> dict:
    """读取 ``transcript`` 配置段(带默认值)

    Returns:
        dict: 规范化后的配置字典
    """
    raw = getattr(cfg, "TRANSCRIPT", None)
    if not isinstance(raw, dict):
        raw = {}
    result = dict(_DEFAULT_SETTINGS)
    for key in _DEFAULT_SETTINGS:
        if key in raw and raw[key] is not None:
            result[key] = raw[key]
    result["enable"] = bool(result["enable"])
    result["keep_video"] = bool(result["keep_video"])
    result["keep_audio"] = bool(result["keep_audio"])
    result["use_itn"] = bool(result["use_itn"])
    result["model_root"] = str(result["model_root"] or "")
    result["device"] = str(result["device"] or "auto")
    result["language"] = str(result["language"] or "auto")
    mode = str(result["mode"] or "local").strip().lower()
    if mode == "remote":  # 语义化别名
        mode = "service"
    result["mode"] = mode if mode in ("local", "service") else "local"
    result["service_url"] = str(result["service_url"] or "").strip()
    result["service_token"] = str(result["service_token"] or "")
    result["service_fallback_local"] = bool(result["service_fallback_local"])
    try:
        result["service_timeout"] = max(1.0, float(result["service_timeout"] or 900))
    except (TypeError, ValueError):
        result["service_timeout"] = 900.0
    return result


def service_status(sett: Optional[dict] = None) -> dict:
    """探测转录服务是否可用(不抛异常, 供启动报告使用)

    Args:
        sett: 配置字典, 省略时读取当前配置
    Returns:
        dict: ``{"ready", "url", "detail", "info"}``
    """
    sett = settings() if sett is None else sett
    url = sett.get("service_url") or DEFAULT_SERVICE_URL
    return probe_service(url, token=sett.get("service_token") or "")


def is_enabled() -> bool:
    """转录管道是否开启(含 ``video.download`` 开关)"""
    if not settings()["enable"]:
        return False
    video = getattr(cfg, "VIDEO", None) or {}
    return bool(video.get("download", True))


@dataclass
class VideoJob:
    """一个待转录的视频任务"""

    object_id: str
    title: str = ""
    knowledge_id: Optional[int] = None
    duration: int = 0
    url: str = ""
    cookies: dict = field(default_factory=dict)


class TranscriptWorker:
    """单线程转录 worker"""

    def __init__(self, *, name: str = "TranscriptWorker") -> None:
        self.logger = Logger("Transcript")
        self._attach_log_handler()
        self.name = name
        self._queue: "queue.Queue" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._session = None
        self._transcriber: Optional[LocalSenseVoiceTranscriber] = None
        self._cache: Optional[TranscriptCache] = None
        self._cache_dir: Optional[Path] = None
        self._counters = {"queued": 0, "done": 0, "cached": 0, "failed": 0}
        # 章节 id -> 尚未处理完的任务数, 供搜索器判断"是否值得等待文稿"
        self._pending_chapters: dict[int, int] = {}

    def _attach_log_handler(self) -> None:
        """给转录日志单独挂文件 handler

        CxKitty 的 ``Logger`` 默认不挂 handler, 后台管道的 info 级进度会被丢弃;
        这里直接写 ``logs/transcript.log`` 并关闭向 root logger 传播,
        避免 worker 线程往 stderr 输出而干扰主线程的 rich Live 渲染(TUI 隔离)。
        """
        try:
            raw = self.logger.logger
            if getattr(raw, "_cxkitty_transcript_handler", False):
                return
            cfg.LOGS_PATH.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(cfg.LOGS_PATH / "transcript.log", encoding="utf8")
            handler.setLevel(logging.INFO)
            handler.setFormatter(logging.Formatter(self.logger.fmt))
            raw.addHandler(handler)
            raw.propagate = False
            raw._cxkitty_transcript_handler = True  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - 挂 handler 失败不应影响管道运行
            pass

    # ---------------- 队列控制 ----------------

    def start(self) -> None:
        """启动后台线程(幂等)"""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
            self._thread.start()
            self.logger.info("转录 worker 线程已启动")

    def submit(self, job: VideoJob) -> bool:
        """提交任务(非阻塞)

        Args:
            job: 视频任务
        Returns:
            bool: 是否成功入队
        """
        self.start()
        self._counters["queued"] += 1
        self._mark_pending(job.knowledge_id, 1)
        self._queue.put(job)
        self.logger.info(
            f"视频已加入转录队列(待处理 {self._queue.qsize()}) [{job.title or job.object_id}]"
        )
        return True

    def stop(self, timeout: float = 5.0) -> None:
        """请求停止后台线程(处理完当前任务后退出)"""
        if self._thread is None or not self._thread.is_alive():
            return
        self._queue.put(_STOP)
        self._thread.join(timeout=timeout)
        self.logger.info("转录 worker 线程已停止")

    def status(self) -> dict:
        """返回 worker 运行状态(供日志展示)"""
        return {
            "alive": bool(self._thread is not None and self._thread.is_alive()),
            "pending": self._queue.qsize(),
            "model_loaded": self._transcriber is not None,
            "device": self._transcriber.device_in_use if self._transcriber else None,
            "chapters": context.chapter_sizes(),
            "pending_chapters": dict(self._pending_chapters),
            **self._counters,
        }

    def _mark_pending(self, knowledge_id, delta: int) -> None:
        """增减某章节的待处理任务计数"""
        kid = context.normalize_knowledge_id(knowledge_id)
        if kid is None:
            return
        with self._lock:
            value = self._pending_chapters.get(kid, 0) + delta
            if value > 0:
                self._pending_chapters[kid] = value
            else:
                self._pending_chapters.pop(kid, None)

    def has_pending_for(self, knowledge_id) -> bool:
        """该章节是否还有正在排队/处理中的转录任务

        答题时用来判断"值得为文稿等待"还是"直接弃权"。
        """
        kid = context.normalize_knowledge_id(knowledge_id)
        if kid is None:
            return False
        with self._lock:
            return bool(self._pending_chapters.get(kid))

    # ---------------- 线程主体 ----------------

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                self._queue.task_done()
                return
            try:
                self._process(item)
            except (TranscriptError, TranscriptionError) as err:
                self._counters["failed"] += 1
                self.logger.error(
                    f"转录任务失败 [{getattr(item, 'title', '') or getattr(item, 'object_id', '')}] "
                    f"-> {err.__class__.__name__} {err}"
                )
            except Exception as err:  # noqa: BLE001 - worker 线程必须永不中断
                self._counters["failed"] += 1
                self.logger.error(
                    f"转录任务异常 [{getattr(item, 'object_id', '')}] -> {err.__class__.__name__} {err}",
                    exc_info=True,
                )
            finally:
                self._mark_pending(getattr(item, "knowledge_id", None), -1)
                self._queue.task_done()

    def _process(self, job: VideoJob) -> None:
        sett = settings()
        cache = self._get_cache(sett)

        # 1. 缓存命中直接注册
        record = cache.load(job.object_id)
        if record is not None and record.text.strip():
            self._counters["cached"] += 1
            knowledge_id = job.knowledge_id if job.knowledge_id is not None else record.knowledge_id
            context.register(knowledge_id, job.object_id, record.text)
            self.logger.info(f"转录缓存命中 [{job.title or job.object_id}]")
            return

        if not job.url:
            raise TranscriptError("视频无 http 直链(可能为 hls/m3u8), 无法下载")

        # 2. 下载视频
        video_dir = Path(sett["video_path"])
        audio_dir = Path(sett["audio_path"])
        video_file = video_path(video_dir, job.object_id, job.title)
        if video_file.is_file():
            self.logger.info(f"复用已下载视频 {video_file.name}")
        else:
            session = self._get_session(job.cookies)
            download_file(session, job.url, video_file, logger=self.logger)

        # 3. 提取音频
        audio_file = audio_path(audio_dir, job.object_id)
        if audio_file.is_file():
            self.logger.info(f"复用已提取音频 {audio_file.name}")
        else:
            extract_audio(video_file, audio_file, logger=self.logger)

        # 4. 转录
        try:
            transcriber = self._get_transcriber(sett)
            transcript = transcriber.transcribe(
                audio_file,
                language=sett["language"],
                use_itn=sett["use_itn"],
                job={
                    "object_id": job.object_id,
                    "title": job.title,
                    "knowledge_id": job.knowledge_id,
                    "duration": job.duration,
                },
            )
        except Exception:
            # 失败时丢弃音频(可由视频重新提取), 保留视频以便重试或人工排查
            self._safe_unlink(audio_file)
            raise
        if not transcript.text.strip():
            self._safe_unlink(audio_file)
            raise TranscriptError(f"转录结果为空 [{job.title or job.object_id}]")

        # 5. 写缓存 + 注册章节文稿
        record = TranscriptRecord.from_transcript(
            transcript,
            object_id=job.object_id,
            title=job.title,
            knowledge_id=job.knowledge_id,
            duration=job.duration,
        )
        path = cache.save(record)
        context.register(job.knowledge_id, job.object_id, record.text)
        self._counters["done"] += 1
        self.logger.info(
            f"转录完成 {path.name} ({len(record.segments)} 句 / {len(record.text)} 字)"
        )

        # 6. 清理临时文件
        if not sett["keep_audio"]:
            self._safe_unlink(audio_file)
        if not sett["keep_video"]:
            self._safe_unlink(video_file)

    # ---------------- 资源管理 ----------------

    def _get_cache(self, sett: dict) -> TranscriptCache:
        cache_dir = Path(sett["cache_path"])
        if self._cache is None or self._cache_dir != cache_dir:
            self._cache = TranscriptCache(cache_dir)
            self._cache_dir = cache_dir
        return self._cache

    def _get_session(self, cookies: dict):
        """构造 worker 专属会话, 避免与主线程共用同一个 requests.Session"""
        if self._session is None:
            from cxapi.session import SessionWraper

            self._session = SessionWraper()
            self.logger.info("转录 worker 已创建独立会话(继承代理配置)")
        if cookies:
            try:
                self._session.ck_load(cookies)
            except Exception as err:  # noqa: BLE001 - Cookie 同步失败不影响匿名直链下载
                self.logger.warning(f"Cookie 同步失败 -> {err.__class__.__name__} {err}")
        return self._session

    def _get_transcriber(self, sett: dict):
        """返回转录后端(进程内模型 / 独立转录服务), 进程内单例复用"""
        if self._transcriber is not None:
            return self._transcriber
        if sett["mode"] == "service":
            try:
                return self._connect_service(sett)
            except TranscriptionError as err:
                if not sett["service_fallback_local"]:
                    raise
                self.logger.warning(f"转录服务不可用({err}), 回退进程内模型")
        return self._load_local_model(sett)

    def _connect_service(self, sett: dict) -> RemoteSenseVoiceTranscriber:
        """连接独立转录服务(多账号共享同一份模型)"""
        url = sett["service_url"] or DEFAULT_SERVICE_URL
        transcriber = RemoteSenseVoiceTranscriber(
            url,
            token=sett["service_token"],
            timeout=sett["service_timeout"],
        )
        self.logger.info(f"正在连接转录服务 {url} ...")
        device = transcriber.load()
        self.logger.info(f"转录服务就绪 {url} (device={device})")
        self._transcriber = transcriber
        return transcriber

    def _load_local_model(self, sett: dict) -> LocalSenseVoiceTranscriber:
        """在进程内加载 SenseVoice(与刷课主进程同进程)"""
        model_root = sett["model_root"]
        if not model_root:
            raise TranscriptionError(
                f"未配置 transcript.model_root, 请在 {cfg.CONFIG_PATH} 中指向 SenseVoiceSmall 模型目录"
            )
        status = model_root_status(model_root)
        if not status["ready"]:
            raise TranscriptionError(
                f"SenseVoice 模型未就绪: {status['sensevoice']}(可执行 scripts/install-asr.ps1 下载模型)"
            )
        transcriber = LocalSenseVoiceTranscriber.from_model_root(
            model_root, device=sett["device"]
        )
        self.logger.info(f"正在加载 SenseVoiceSmall 模型, device={sett['device']} (首次较慢)")
        device = transcriber.load()
        self.logger.info(f"SenseVoiceSmall 模型加载完成, device={device}")
        self._transcriber = transcriber
        return self._transcriber

    @staticmethod
    def _safe_unlink(path: Path) -> None:
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass


def get_worker() -> TranscriptWorker:
    """获取进程内单例 worker"""
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = TranscriptWorker()
        return _worker


def reset_worker() -> None:
    """丢弃单例(测试 / 配置重载用)"""
    global _worker
    with _worker_lock:
        _worker = None


def enqueue_video(video_dto, session=None) -> bool:
    """把视频任务点加入后台转录队列(主线程调用, 立即返回)

    Args:
        video_dto: ``PointVideoDto``(需已 ``fetch()`` 成功, 含 ``http`` 直链)
        session: 主线程会话, 用于导出 Cookie 给 worker
    Returns:
        bool: 是否已入队或已命中缓存
    """
    sett = settings()
    if not sett["enable"]:
        return False
    if not is_enabled():
        return False

    object_id = str(getattr(video_dto, "object_id", "") or "")
    if not object_id:
        return False
    title = str(getattr(video_dto, "title", "") or "")
    knowledge_id = getattr(video_dto, "knowledge_id", None)
    url = str(getattr(video_dto, "http", "") or "")
    logger = get_worker().logger

    if not url:
        logger.warning(f"视频无 http 直链(可能为 hls/m3u8), 跳过转录 [{title or object_id}]")
        return False

    # 缓存命中: 主线程直接注册, 无需排队等待
    cached = TranscriptCache(sett["cache_path"]).load(object_id)
    if cached is not None and cached.text.strip():
        context.register(knowledge_id or cached.knowledge_id, object_id, cached.text)
        logger.info(f"转录缓存命中 [{title or object_id}]")
        return True

    cookies = {}
    if session is not None:
        try:
            cookies = session.ck_dump()
        except Exception:  # noqa: BLE001 - Cookie 导出失败时退回匿名下载
            cookies = {}

    job = VideoJob(
        object_id=object_id,
        title=title,
        knowledge_id=knowledge_id,
        duration=int(getattr(video_dto, "duration", 0) or 0),
        url=url,
        cookies=cookies,
    )
    return get_worker().submit(job)


def prime_chapter(knowledge_id) -> int:
    """把缓存中属于该章节的文稿注册进上下文(主线程调用, 耗时极低)

    用于"视频任务点已完成因此不会重新入队"的场景——上轮刷课转录出的文稿依然可用。

    Args:
        knowledge_id: 章节 id
    Returns:
        int: 本次注册的文稿数量
    """
    sett = settings()
    if not sett["enable"]:
        return 0
    kid = context.normalize_knowledge_id(knowledge_id)
    if kid is None:
        return 0
    cache = TranscriptCache(sett["cache_path"])
    count = 0
    for record in cache.iter_records():
        if record.knowledge_id != kid or not record.text.strip():
            continue
        if context.register(kid, record.object_id, record.text):
            count += 1
    if count:
        get_worker().logger.info(f"章节 {kid} 预热 {count} 份文稿")
    return count


def _module_version(module_name: str) -> str:
    """读取已安装包的版本号(仅查元数据, 不导入模块)"""

    try:
        return importlib.metadata.version(module_name)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"
    except Exception:  # noqa: BLE001 - 元数据异常时不影响探测
        return "unknown"


def dependency_status() -> dict:
    """探测 ASR 相关依赖是否安装

    只查 ``find_spec`` / 包元数据, **不导入模块**: 导入 torch + funasr + modelscope 会连带
    加载整套 CUDA 运行库, 实测提交约 1.7GB 内存(常驻约 0.7GB)。启动探测若走 ``__import__``,
    即使本次运行一次转录都没有(全部命中缓存 / 未开启转录)也要白白付出这份开销。

    探测只回答"是否已安装"; 依赖损坏导致的真实导入失败仍会在转录时抛出并附带安装提示。
    """
    result: dict = {"torch": None, "funasr": None, "modelscope": None, "missing": []}
    for module_name in ("torch", "funasr", "modelscope"):
        try:
            installed = importlib.util.find_spec(module_name) is not None
        except Exception:  # noqa: BLE001 - 包损坏时按未安装处理
            installed = False
        if not installed:
            result["missing"].append(module_name)
            continue
        result[module_name] = _module_version(module_name)
    return result


def startup_report() -> dict:
    """启动探测报告(模式 / ffmpeg / 模型或服务 / ASR 依赖)"""
    sett = settings()
    model_root = sett["model_root"]
    mode = sett["mode"]
    return {
        "enable": sett["enable"],
        "mode": mode,
        "ffmpeg": ffmpeg_status(),
        "model_root": model_root,
        "models": model_root_status(model_root) if model_root else {"ready": False},
        "dependencies": dependency_status(),
        "service": service_status(sett) if mode == "service" else None,
    }


def log_startup_report() -> dict:
    """记录启动探测结果, 仅在不可用时输出警告

    Returns:
        dict: ``startup_report()`` 的结果
    """
    report = startup_report()
    logger = get_worker().logger
    if not report["enable"]:
        logger.info("视频转录管道未开启 (transcript.enable = false)")
        return report
    problems = []
    if not report["ffmpeg"]["ready"]:
        problems.append(report["ffmpeg"]["hint"])

    if report["mode"] == "service":
        service = report["service"] or {}
        info = service.get("info") or {}
        if service.get("ready"):
            device = info.get("device") or info.get("configured_device") or "unknown"
            loaded = "已加载" if info.get("model_loaded") else "按需加载"
            logger.info(
                f"转录服务就绪 {service.get('url')} (device={device}, 模型{loaded}, "
                f"已转录 {info.get('served', 0)} 次 / 缓存命中 {info.get('cached', 0)} 次)"
            )
        else:
            problems.append(
                f"转录服务不可用: {service.get('url')} -> {service.get('detail')} "
                "(请先启动 `python -m transcript.server`)"
            )
    else:
        if not report["models"].get("ready"):
            problems.append(
                f"SenseVoice 模型未就绪: {report['model_root'] or '(未配置 model_root)'} "
                "(可执行 scripts/install-asr.ps1 下载)"
            )
        if missing := report["dependencies"]["missing"]:
            problems.append(f"缺少 ASR 依赖: {', '.join(missing)}")
        if not problems:
            logger.info("视频转录管道就绪 (ffmpeg / 模型 / 依赖均已就绪)")

    for problem in problems:
        logger.warning(f"视频转录不可用 -> {problem}")
    return report


__all__ = [
    "VideoJob",
    "TranscriptWorker",
    "settings",
    "is_enabled",
    "get_worker",
    "reset_worker",
    "enqueue_video",
    "prime_chapter",
    "dependency_status",
    "startup_report",
    "log_startup_report",
    "service_status",
]