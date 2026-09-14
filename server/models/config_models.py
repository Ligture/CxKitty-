"""配置相关 Pydantic 模型"""

from pydantic import BaseModel
from typing import Optional


class ProxyConfig(BaseModel):
    enable: bool = False
    HTTP: str = ""
    HTTPS: str = ""


class VideoConfig(BaseModel):
    enable: bool = True
    wait: int = 15
    speed: float = 1.0
    report_rate: int = 58
    download: bool = True


class TranscriptConfig(BaseModel):
    """视频转录管道配置 (下载 -> ffmpeg 提取音频 -> SenseVoiceSmall -> 章节文稿)"""

    enable: bool = False
    model_root: str = ""
    device: str = "auto"
    language: str = "auto"
    use_itn: bool = True
    cache_path: str = "transcripts/"
    video_path: str = "videos/"
    audio_path: str = "audios/"
    keep_video: bool = False
    keep_audio: bool = False


class WorkConfig(BaseModel):
    enable: bool = True
    export: bool = True
    wait: int = 15
    fallback_fuzzer: bool = False
    fallback_save: bool = False


class DocumentConfig(BaseModel):
    enable: bool = True
    wait: int = 15


class ExamConfig(BaseModel):
    fallback_fuzzer: bool = False
    persubmit_delay: int = 15
    confirm_submit: bool = True


class SearcherField(BaseModel):
    key: str
    label: str
    type: str  # "hidden" | "text" | "password" | "url" | "textarea" | "select" | "switch" | "number"
    default: object = None
    placeholder: str = ""
    required: bool = False
    options: list[str] = []
    rows: int = 3
    help: str = ""


class SearcherTemplate(BaseModel):
    label: str
    icon: str = ""
    color: str = ""
    desc: str = ""
    fields: list[SearcherField] = []


class FullConfig(BaseModel):
    multi_session: bool = True
    mask_acc: bool = True
    tui_max_height: int = 25
    fetch_uploaded_face: bool = True
    session_path: str = "session"
    log_path: str = "logs"
    export_path: str = "export"
    face_image_path: str = "faces"
    proxies: ProxyConfig = ProxyConfig()
    video: VideoConfig = VideoConfig()
    transcript: TranscriptConfig = TranscriptConfig()
    work: WorkConfig = WorkConfig()
    document: DocumentConfig = DocumentConfig()
    exam: ExamConfig = ExamConfig()
    searchers: list[dict] = []
