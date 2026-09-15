"""进程外转录服务客户端

把 ASR 推理挪到独立的 ``transcript.server`` 进程后, 多个刷课主进程(多账号)可以复用同一份
SenseVoice 模型——本机实测每份模型常驻约 1.7GB / 提交约 3.5GB / 显存约 1.1GB, 多开时浪费明显。

本模块只负责"把音频文件交给服务端, 取回转录结果", 与 ``LocalSenseVoiceTranscriber``
保持同一套调用接口(``load()`` / ``device_in_use`` / ``transcribe()``), 方便 worker 互换。
下载视频、ffmpeg 提取音频、写本地缓存仍然在主进程内完成。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import requests

from .asr import Transcript, TranscriptSegment
from .errors import TranscriptionError

#: 服务默认监听地址(仅本机)
DEFAULT_SERVICE_URL = "http://127.0.0.1:8765"
#: 共享口令请求头
TOKEN_HEADER = "X-Transcript-Token"
#: 连接与读取 health 的超时(秒), 与转录本身的长超时区分开
_CONNECT_TIMEOUT = 5.0
_HEALTH_TIMEOUT = 10.0


def _headers(token: str) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if token:
        headers[TOKEN_HEADER] = token
    return headers


def _payload(response: requests.Response) -> dict[str, Any]:
    """解析服务端 JSON 响应, 非 200 时抛出带服务端描述的异常"""

    try:
        data = response.json()
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    if response.status_code != 200:
        detail = str(data.get("error") or "").strip() or response.text.strip()
        raise TranscriptionError(f"转录服务返回 {response.status_code}: {detail or '未知错误'}")
    return data


class RemoteSenseVoiceTranscriber:
    """通过本地 HTTP 服务转录(与服务端共享同一份 SenseVoice 模型)"""

    def __init__(
        self,
        url: str = DEFAULT_SERVICE_URL,
        *,
        token: str = "",
        timeout: float = 900.0,
        session: Optional[requests.Session] = None,
    ) -> None:
        """
        Args:
            url: 服务地址, 如 ``http://127.0.0.1:8765``
            token: 与服务端一致的口令, 留空表示不校验
            timeout: 单次转录的读取超时(秒), 长视频按需调大
            session: 复用的 requests 会话(测试注入用)
        """
        self.url = str(url or DEFAULT_SERVICE_URL).rstrip("/")
        self.token = str(token or "")
        self.timeout = max(1.0, float(timeout or 900.0))
        self._session = session or requests.Session()
        self._device: Optional[str] = None
        self._loaded = False

    # ---------------- 与 LocalSenseVoiceTranscriber 对齐的接口 ----------------

    def load(self) -> str:
        """连接服务并确认可用, 返回服务端设备名

        Returns:
            str: 服务端设备(如 ``cuda:0`` / ``cpu``)
        Raises:
            TranscriptionError: 服务不可达或返回异常
        """
        info = self.health()
        # 模型尚未加载时用服务端配置的设备名兜底(auto / cpu / cuda:0)
        self._device = str(info.get("device") or info.get("configured_device") or "unknown")
        self._loaded = True
        return self._device

    @property
    def device_in_use(self) -> Optional[str]:
        """服务端设备(连接成功后可知)"""
        return self._device

    def health(self) -> dict[str, Any]:
        """读取服务端状态

        Returns:
            dict: ``/health`` 返回的原始字典
        Raises:
            TranscriptionError: 服务不可达
        """
        try:
            response = self._session.get(
                f"{self.url}/health",
                headers=_headers(self.token),
                timeout=(_CONNECT_TIMEOUT, _HEALTH_TIMEOUT),
            )
        except requests.RequestException as err:
            raise TranscriptionError(f"无法连接转录服务 {self.url}: {err}") from err
        return _payload(response)

    def transcribe(
        self,
        input_path: str | Path,
        *,
        language: str = "auto",
        use_itn: bool = True,
        job: Optional[dict[str, Any]] = None,
    ) -> Transcript:
        """请求服务端转录一个音频文件

        Args:
            input_path: 16kHz 单声道 wav 路径(服务端与客户端同机, 直接传绝对路径)
            language: ``auto`` / ``zh`` / ``en`` / ``yue`` / ``ja`` / ``ko``
            use_itn: 是否启用逆文本正则化
            job: 任务点元信息(``object_id`` / ``title`` / ``knowledge_id`` / ``duration``),
                供服务端按 object_id 缓存并跨账号去重
        Returns:
            Transcript: 转录结果
        Raises:
            TranscriptionError: 本地文件缺失或服务端返回错误
        """
        path = Path(input_path)
        if not path.is_file():
            raise TranscriptionError(f"音频文件不存在: {path}")

        payload: dict[str, Any] = {
            "audio_path": str(path.resolve()),
            "language": language,
            "use_itn": bool(use_itn),
        }
        for key in ("object_id", "title", "knowledge_id", "duration"):
            if job and job.get(key) is not None:
                payload[key] = job[key]

        try:
            response = self._session.post(
                f"{self.url}/transcribe",
                json=payload,
                headers=_headers(self.token),
                timeout=(_CONNECT_TIMEOUT, self.timeout),
            )
        except requests.RequestException as err:
            self._device = None
            raise TranscriptionError(f"转录服务请求失败 {self.url}: {err}") from err

        data = _payload(response)
        self._device = str(data.get("device") or self._device or "unknown")
        self._loaded = True
        return _to_transcript(data)

    def unload(self) -> bool:
        """请求服务端释放模型(显存 / 内存), 下次请求会自动重新加载

        Returns:
            bool: 服务端是否真的卸载了模型
        """
        try:
            response = self._session.post(
                f"{self.url}/unload",
                headers=_headers(self.token),
                timeout=(_CONNECT_TIMEOUT, _HEALTH_TIMEOUT),
            )
        except requests.RequestException as err:
            raise TranscriptionError(f"无法连接转录服务 {self.url}: {err}") from err
        data = _payload(response)
        self._device = None
        return bool(data.get("unloaded"))


def probe_service(
    url: str = DEFAULT_SERVICE_URL,
    *,
    token: str = "",
    timeout: float = _CONNECT_TIMEOUT,
) -> dict[str, Any]:
    """探测服务是否可用(不抛异常, 供启动报告使用)

    Args:
        url: 服务地址
        token: 共享口令
        timeout: 连接超时(秒)
    Returns:
        dict: ``{"ready": bool, "url": str, "detail": str, "info": dict}``
    """
    target = str(url or DEFAULT_SERVICE_URL).rstrip("/")
    try:
        response = requests.get(
            f"{target}/health",
            headers=_headers(token),
            timeout=(max(0.1, float(timeout)), _HEALTH_TIMEOUT),
        )
        data = _payload(response)
    except TranscriptionError as err:
        return {"ready": False, "url": target, "detail": str(err), "info": {}}
    except requests.RequestException as err:
        return {"ready": False, "url": target, "detail": f"无法连接: {err}", "info": {}}
    return {"ready": True, "url": target, "detail": "", "info": data}


def _to_transcript(data: dict[str, Any]) -> Transcript:
    """把服务端 JSON 还原成 Transcript"""

    segments = []
    raw_segments = data.get("segments")
    if isinstance(raw_segments, list):
        for item in raw_segments:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            segments.append(
                TranscriptSegment(
                    start_ms=int(item.get("start_ms") or 0),
                    end_ms=int(item.get("end_ms") or 0),
                    text=text,
                )
            )
    return Transcript(
        text=str(data.get("text") or "").strip(),
        language=data.get("language"),
        segments=segments,
        raw=data,
    )


__all__ = [
    "DEFAULT_SERVICE_URL",
    "TOKEN_HEADER",
    "RemoteSenseVoiceTranscriber",
    "probe_service",
]
