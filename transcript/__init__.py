"""视频转录管道

刷课过程中把章节视频下载 -> 提取音频 -> 本地 SenseVoiceSmall 转录 -> 按章节缓存文稿,
答题时把章节文稿作为上下文交给 AI 搜索器, 降低单 AI 搜索器的错误率。

模块布局::

    transcript/
    ├── downloader.py   流式下载(走 SessionWraper, 自动继承代理配置)
    ├── extractor.py    ffmpeg subprocess 音频提取(16k 单声道 wav)
    ├── asr.py          移植的 LocalSenseVoiceTranscriber + 模型目录就绪校验
    ├── cache.py        transcripts/{object_id}.json 读写
    ├── worker.py       单线程后台 worker(queue.Queue), 模型进程内单例
    ├── context.py      章节文稿注册表 knowledge_id -> 拼合文本
    └── errors.py       管道异常定义

管道整体是"尽力而为的增强": 任何环节失败都退化为现状(仅题库搜索器作答),
不会影响刷课主流程。
"""

from .context import (
    clear as clear_context,
    get_current_knowledge_id,
    get_text,
    has_text,
    register,
    set_current_knowledge_id,
    wait_for_text,
)
from .errors import TranscriptError, TranscriptionError
from .worker import (
    VideoJob,
    TranscriptWorker,
    enqueue_video,
    get_worker,
    is_enabled,
    log_startup_report,
    prime_chapter,
    service_status,
    settings,
    startup_report,
)

__all__ = [
    # 异常
    "TranscriptError",
    "TranscriptionError",
    # 配置 / 生命周期
    "settings",
    "is_enabled",
    "startup_report",
    "log_startup_report",
    "service_status",
    "get_worker",
    # 任务入队
    "VideoJob",
    "TranscriptWorker",
    "enqueue_video",
    "prime_chapter",
    # 章节文稿注册表
    "set_current_knowledge_id",
    "get_current_knowledge_id",
    "register",
    "has_text",
    "get_text",
    "wait_for_text",
    "clear_context",
]