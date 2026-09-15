"""音频提取器

调用 ffmpeg 将视频转码为 SenseVoiceSmall 所需的 16kHz 单声道 wav。
启动时探测 ffmpeg 是否可用, 未安装时给出明确提示(可用 ``imageio-ffmpeg`` 自带二进制兜底)。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

from core.logger import Logger

from .errors import TranscriptError

# SenseVoiceSmall 期望的采样率
TARGET_SAMPLE_RATE = 16000
# 提取超时(秒): 30 分钟视频通常 < 1 分钟
_DEFAULT_TIMEOUT = 900
_CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
_FFMPEG_CANDIDATE: Optional[str] = None
_FFMPEG_PROBED = False


def find_ffmpeg() -> Optional[str]:
    """探测可用的 ffmpeg 可执行文件

    Returns:
        Optional[str]: ffmpeg 路径, 未找到时为 None
    """
    global _FFMPEG_CANDIDATE, _FFMPEG_PROBED
    if _FFMPEG_PROBED:
        return _FFMPEG_CANDIDATE

    _FFMPEG_PROBED = True
    if path := shutil.which("ffmpeg"):
        _FFMPEG_CANDIDATE = path
        return _FFMPEG_CANDIDATE
    # 备选: pip 包 imageio-ffmpeg 自带的 ffmpeg 二进制
    try:
        import imageio_ffmpeg  # type: ignore[import-not-found]

        _FFMPEG_CANDIDATE = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - 可选依赖缺失属于正常情况
        _FFMPEG_CANDIDATE = None
    return _FFMPEG_CANDIDATE


def ffmpeg_status() -> dict:
    """返回 ffmpeg 就绪状态(供启动探测)

    Returns:
        dict: ``{"ready": bool, "path": str|None, "hint": str}``
    """
    path = find_ffmpeg()
    if path:
        return {"ready": True, "path": path, "hint": ""}
    return {
        "ready": False,
        "path": None,
        "hint": (
            "未找到 ffmpeg, 视频转录不可用。"
            "请安装 ffmpeg 并加入 PATH, 或执行 `pip install imageio-ffmpeg` 使用其自带二进制。"
        ),
    }


def extract_audio(
    video_path: Path,
    audio_dest: Path,
    *,
    logger: Optional[Logger] = None,
    ffmpeg: Optional[str] = None,
    timeout: int = _DEFAULT_TIMEOUT,
    sample_rate: int = TARGET_SAMPLE_RATE,
) -> Path:
    """从视频中提取单声道 wav 音频

    Args:
        video_path: 源视频路径
        audio_dest: 目标 wav 路径
        logger: 日志记录器
        ffmpeg: ffmpeg 可执行文件路径, 默认自动探测
        timeout: 子进程超时(秒)
        sample_rate: 目标采样率
    Returns:
        Path: 提取出的 wav 路径
    Raises:
        TranscriptError: ffmpeg 缺失 / 转码失败 / 超时
    """
    video_path = Path(video_path)
    audio_dest = Path(audio_dest)
    if not video_path.is_file():
        raise TranscriptError(f"视频文件不存在: {video_path}")

    ffmpeg = ffmpeg or find_ffmpeg()
    if not ffmpeg:
        raise TranscriptError(
            "未找到 ffmpeg, 无法提取音频。请安装 ffmpeg 并加入 PATH, "
            "或执行 `pip install imageio-ffmpeg`。"
        )

    audio_dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = audio_dest.with_name(audio_dest.name + ".part.wav")
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-i", str(video_path),
        "-vn",
        "-ac", "1",
        "-ar", str(sample_rate),
        "-acodec", "pcm_s16le",
        str(tmp),
    ]
    if logger is not None:
        logger.info(f"开始提取音频 {video_path.name} -> {audio_dest.name}")
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as err:
        _cleanup(tmp)
        raise TranscriptError(f"ffmpeg 提取音频超时({timeout}s): {video_path.name}") from err
    except OSError as err:
        _cleanup(tmp)
        raise TranscriptError(f"无法启动 ffmpeg({ffmpeg}): {err}") from err

    if completed.returncode != 0 or not tmp.is_file():
        detail = (completed.stderr or b"").decode("utf8", errors="ignore").strip()
        detail = detail.splitlines()[-1] if detail else ""
        _cleanup(tmp)
        raise TranscriptError(
            f"ffmpeg 提取音频失败(code={completed.returncode}): {video_path.name} {detail}"
        )

    tmp.replace(audio_dest)
    if logger is not None:
        logger.info(f"音频提取完成 {audio_dest.name} ({audio_dest.stat().st_size / 1048576:.1f} MiB)")
    return audio_dest


def _cleanup(path: Path) -> None:
    """删除残留的临时文件"""
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


__all__ = ["TARGET_SAMPLE_RATE", "find_ffmpeg", "ffmpeg_status", "extract_audio"]