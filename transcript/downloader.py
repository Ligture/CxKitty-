"""视频下载器

流式下载任务点视频到本地, 复用 ``SessionWraper`` 以自动继承 Cookie、代理配置与风控处理。
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional

from core.logger import Logger

from .errors import TranscriptError

# Windows / Linux 通用非法文件名字符
_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# Windows 保留设备名
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_MAX_STEM_LENGTH = 80
_DEFAULT_CHUNK_SIZE = 1024 * 256


def sanitize_filename(name: str, *, fallback: str = "video", max_length: int = _MAX_STEM_LENGTH) -> str:
    """清洗文件名中的非法字符

    Args:
        name: 原始文件名(不含扩展名)
        fallback: 清洗后为空时的回退名称
        max_length: 最大长度, 超出部分截断
    Returns:
        str: 可安全用于文件系统的名称
    """
    cleaned = _ILLEGAL_CHARS.sub("_", str(name or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Windows 不允许文件名以点或空格结尾
    cleaned = cleaned.rstrip(". ")
    if cleaned.upper() in _RESERVED_NAMES:
        cleaned = f"{cleaned}_"
    if not cleaned:
        cleaned = fallback
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip(". ")
    return cleaned or fallback


def video_path(video_dir: Path, object_id: str, title: str) -> Path:
    """生成视频本地保存路径

    Args:
        video_dir: 视频保存目录
        object_id: 任务点 objectid(唯一标识, 天然去重)
        title: 视频标题
    Returns:
        Path: 形如 ``videos/{object_id}_{清洗后标题}.mp4``
    """
    stem = sanitize_filename(f"{object_id}_{title}", fallback=str(object_id))
    return Path(video_dir) / f"{stem}.mp4"


def audio_path(audio_dir: Path, object_id: str) -> Path:
    """生成音频提取目标路径

    Args:
        audio_dir: 音频保存目录
        object_id: 任务点 objectid
    Returns:
        Path: 形如 ``audios/{object_id}.wav``
    """
    return Path(audio_dir) / f"{sanitize_filename(str(object_id), fallback='audio')}.wav"


def download_file(
    session,
    url: str,
    dest: Path,
    *,
    logger: Optional[Logger] = None,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
    timeout: tuple[float, float] = (15.0, 120.0),
    headers: Optional[dict] = None,
    max_retry: int = 3,
    retry_delay: float = 3.0,
    progress_cb=None,
) -> Path:
    """流式下载文件

    Args:
        session: ``requests.Session`` 兼容对象(通常为 ``SessionWraper``)
        url: 下载直链
        dest: 目标文件路径
        logger: 日志记录器
        chunk_size: 分块大小
        timeout: (连接超时, 读取超时)
        headers: 附加请求头
        max_retry: 失败重试次数
        retry_delay: 重试间隔秒数
        progress_cb: 进度回调 ``cb(written_bytes, total_bytes)``, total 未知时为 0
    Returns:
        Path: 下载完成的文件路径
    Raises:
        TranscriptError: 重试耗尽后仍失败
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    last_error: Optional[Exception] = None

    for attempt in range(1, max_retry + 1):
        written = 0
        try:
            with session.get(url, stream=True, timeout=timeout, headers=headers) as resp:
                resp.raise_for_status()
                try:
                    total = int(resp.headers.get("Content-Length") or 0)
                except (TypeError, ValueError):
                    total = 0
                with open(tmp, "wb") as fp:
                    for chunk in resp.iter_content(chunk_size=chunk_size):
                        if not chunk:
                            continue
                        fp.write(chunk)
                        written += len(chunk)
                        if progress_cb is not None:
                            progress_cb(written, total)
            if written == 0:
                raise TranscriptError(f"下载内容为空: {url}")
            if total and written < total:
                raise TranscriptError(f"下载不完整 {written}/{total} 字节: {url}")
            tmp.replace(dest)
            if logger is not None:
                logger.info(f"视频下载完成 {dest.name} ({written / 1048576:.1f} MiB)")
            return dest
        except Exception as err:  # noqa: BLE001 - 任何网络异常都走重试
            last_error = err
            if logger is not None:
                logger.warning(
                    f"视频下载失败(第 {attempt}/{max_retry} 次) -> {err.__class__.__name__} {err}"
                )
            if attempt < max_retry:
                time.sleep(retry_delay)
        finally:
            if tmp.exists() and (not dest.exists() or written == 0):
                try:
                    tmp.unlink()
                except OSError:
                    pass

    raise TranscriptError(f"视频下载失败: {url} -> {last_error}") from last_error


__all__ = [
    "sanitize_filename",
    "video_path",
    "audio_path",
    "download_file",
]