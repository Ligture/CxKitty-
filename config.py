import threading
import warnings
from pathlib import Path

import yaml

_config_lock = threading.Lock()

try:
    with open("config.yml", "r", encoding="utf8") as fp:
        conf: dict = yaml.load(fp, yaml.FullLoader)
except FileNotFoundError:
    conf = {}
    warnings.warn("Config file not found", RuntimeWarning)

# 路径配置
SESSIONS_PATH = Path(conf.get("session_path", "session"))
LOGS_PATH = Path(conf.get("log_path", "logs"))
EXPORT_PATH = Path(conf.get("export_path"))
FACE_PATH = Path(conf.get("face_image_path"))

#Proxy 配置
HTPP: dict = conf.get("proxies", {})
HTTP_EN: bool = HTPP.get("enable", True)
HTTPS: list = HTPP.get("HTTPS", [])
HTTP: list = HTPP.get("HTTP", [])

# 创建导出目录
if not EXPORT_PATH.exists():
    EXPORT_PATH.mkdir(parents=True)

# 基本配置
MULTI_SESS: bool = conf.get("multi_session", True)
TUI_MAX_HEIGHT: int = conf.get("tui_max_height", 25)
MASKACC: bool = conf.get("mask_acc", True)
FETCH_UPLOADED_FACE: bool = conf.get("fetch_uploaded_face", True)

# 任务配置
WORK: dict = conf.get("work", {})
VIDEO: dict = conf.get("video", {})
DOCUMENT: dict = conf.get("document", {})
EXAM: dict = conf.get("exam", {})

# 视频转录管道配置 (下载 -> ffmpeg 提取音频 -> SenseVoiceSmall -> 章节文稿)
TRANSCRIPT: dict = conf.get("transcript", {})

# 任务使能配置
WORK_EN: bool = WORK.get("enable", True)
VIDEO_EN: bool = VIDEO.get("enable", True)
DOCUMENT_EN: bool = DOCUMENT.get("enable", True)

# 视频下载 / 转录使能
VIDEO_DOWNLOAD: bool = VIDEO.get("download", True)
TRANSCRIPT_EN: bool = TRANSCRIPT.get("enable", False)

# 任务延时配置
WORK_WAIT: int = WORK.get("wait", 15)
VIDEO_WAIT: int = VIDEO.get("wait", 15)
DOCUMENT_WAIT: int = DOCUMENT.get("wait", 15)

# 搜索器配置
SEARCHERS: list = conf.get("searchers", [])


def reload_config():
    """重新从 config.yml 加载配置 (供 WebUI worker 线程使用, 线程安全)"""
    import config as cfg
    with _config_lock:
        with open("config.yml", "r", encoding="utf8") as fp:
            new_conf = yaml.load(fp, yaml.FullLoader) or {}
        cfg.WORK = new_conf.get("work", {})
        cfg.VIDEO = new_conf.get("video", {})
        cfg.DOCUMENT = new_conf.get("document", {})
        cfg.EXAM = new_conf.get("exam", {})
        cfg.TRANSCRIPT = new_conf.get("transcript", {})
        cfg.SEARCHERS = new_conf.get("searchers", [])
        cfg.WORK_EN = cfg.WORK.get("enable", True)
        cfg.VIDEO_EN = cfg.VIDEO.get("enable", True)
        cfg.DOCUMENT_EN = cfg.DOCUMENT.get("enable", True)
        cfg.VIDEO_DOWNLOAD = cfg.VIDEO.get("download", True)
        cfg.TRANSCRIPT_EN = cfg.TRANSCRIPT.get("enable", False)
        cfg.WORK_WAIT = cfg.WORK.get("wait", 15)
        cfg.VIDEO_WAIT = cfg.VIDEO.get("wait", 15)
        cfg.DOCUMENT_WAIT = cfg.DOCUMENT.get("wait", 15)
