"""章节文稿注册表

以 ``knowledge_id``(章节 id)为键, 保存该章节下所有视频的转录全文, 供答题搜索器读取。

* 主线程写: 任务点入队时的缓存命中, 以及启动时的章节预热
* 后台 worker 写: 转录完成后注册
* 搜索器线程(实为主线程内串行调用)读: ``wait_for_text``

内部使用 ``threading.RLock`` 保护, 键为章节 id, 值为 ``[(object_id, text), ...]``,
按注册顺序拼接即为任务点顺序。
"""

from __future__ import annotations

import threading
import time
from typing import Optional

_JOIN_SEPARATOR = "\n\n"

_lock = threading.RLock()
# knowledge_id -> [(object_id, text), ...]
_chapters: dict[int, list[tuple[str, str]]] = {}
# 主线程在进入章节测验前设置的当前章节指针
_current_knowledge_id: Optional[int] = None


def normalize_knowledge_id(knowledge_id) -> Optional[int]:
    """把章节 id 规整为 int, 非法值返回 None"""
    if knowledge_id is None:
        return None
    try:
        return int(knowledge_id)
    except (TypeError, ValueError):
        return None


def set_current_knowledge_id(knowledge_id) -> Optional[int]:
    """设置"当前章节"指针(答题前由主线程调用)

    Args:
        knowledge_id: 章节 id
    Returns:
        Optional[int]: 生效的章节 id
    """
    global _current_knowledge_id
    value = normalize_knowledge_id(knowledge_id)
    with _lock:
        _current_knowledge_id = value
    return value


def get_current_knowledge_id() -> Optional[int]:
    """读取当前章节指针"""
    with _lock:
        return _current_knowledge_id


def register(knowledge_id, object_id: str, text: str) -> bool:
    """注册(或更新)一个视频的转录文稿

    Args:
        knowledge_id: 所属章节 id
        object_id: 视频任务点 objectid
        text: 转录全文
    Returns:
        bool: 是否成功注册(文稿为空或章节 id 非法时返回 False)
    """
    kid = normalize_knowledge_id(knowledge_id)
    text = (text or "").strip()
    if kid is None or not text:
        return False
    with _lock:
        entries = _chapters.setdefault(kid, [])
        for index, (existing_id, _existing_text) in enumerate(entries):
            if existing_id == object_id:
                entries[index] = (object_id, text)
                return True
        entries.append((object_id, text))
    return True


def has_text(knowledge_id) -> bool:
    """指定章节是否已有可用文稿"""
    kid = normalize_knowledge_id(knowledge_id)
    if kid is None:
        return False
    with _lock:
        return bool(_chapters.get(kid))


def get_text(knowledge_id) -> Optional[str]:
    """获取指定章节的拼合文稿

    Args:
        knowledge_id: 章节 id
    Returns:
        Optional[str]: 拼合后的文稿, 无内容时返回 None
    """
    kid = normalize_knowledge_id(knowledge_id)
    if kid is None:
        return None
    with _lock:
        entries = list(_chapters.get(kid, ()))
    if not entries:
        return None
    return _JOIN_SEPARATOR.join(text for _, text in entries if text)


def wait_for_text(knowledge_id, timeout: float = 0.0, poll_interval: float = 1.0) -> Optional[str]:
    """等待章节文稿就绪(用于答题时"弃权而非阻塞")

    Args:
        knowledge_id: 章节 id
        timeout: 最长等待秒数, <=0 表示只检查一次
        poll_interval: 轮询间隔秒数
    Returns:
        Optional[str]: 就绪的文稿, 超时仍无内容时返回 None
    """
    deadline = time.monotonic() + max(0.0, float(timeout or 0.0))
    poll_interval = max(0.05, float(poll_interval or 0.0))
    while True:
        text = get_text(knowledge_id)
        if text:
            return text
        if time.monotonic() >= deadline:
            return None
        time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))


def chapter_sizes() -> dict[int, int]:
    """返回各章节已注册的视频数量(调试用)"""
    with _lock:
        return {kid: len(entries) for kid, entries in _chapters.items()}


def clear(knowledge_id=None) -> None:
    """清空注册表, 或只清理指定章节

    Args:
        knowledge_id: 章节 id, 为 None 时清空全部
    """
    kid = normalize_knowledge_id(knowledge_id)
    with _lock:
        if kid is None:
            _chapters.clear()
        else:
            _chapters.pop(kid, None)


__all__ = [
    "set_current_knowledge_id",
    "get_current_knowledge_id",
    "register",
    "has_text",
    "get_text",
    "wait_for_text",
    "chapter_sizes",
    "clear",
]