"""转录缓存读写

缓存文件位于 ``{cache_path}/{object_id}.json``, 以任务点 objectid 为键天然去重,
重复刷课时直接命中, 无需重复下载与转录。

Schema::

    {
      "object_id": "...", "title": "...", "knowledge_id": 12345,
      "duration": 1800, "transcribed_at": 1697000000,
      "language": "zh", "text": "全文...",
      "segments": [{"start_ms": 0, "end_ms": 5200, "text": "..."}]
    }
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator, Optional

from .asr import Transcript, TranscriptSegment
from .downloader import sanitize_filename
from .errors import TranscriptError

_CACHE_SUFFIX = ".json"


@dataclass
class TranscriptRecord:
    """一条转录缓存记录"""

    object_id: str
    title: str = ""
    knowledge_id: Optional[int] = None
    duration: int = 0
    transcribed_at: int = 0
    language: Optional[str] = None
    text: str = ""
    segments: list[TranscriptSegment] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "object_id": self.object_id,
            "title": self.title,
            "knowledge_id": self.knowledge_id,
            "duration": self.duration,
            "transcribed_at": self.transcribed_at,
            "language": self.language,
            "text": self.text,
            "segments": [asdict(segment) for segment in self.segments],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TranscriptRecord":
        """从 dict 构造记录, 容忍缺字段的旧缓存"""
        segments = []
        raw_segments = data.get("segments")
        if isinstance(raw_segments, list):
            for item in raw_segments:
                if not isinstance(item, dict):
                    continue
                segments.append(
                    TranscriptSegment(
                        start_ms=int(item.get("start_ms") or 0),
                        end_ms=int(item.get("end_ms") or 0),
                        text=str(item.get("text") or ""),
                    )
                )
        knowledge_id = data.get("knowledge_id")
        try:
            knowledge_id = int(knowledge_id) if knowledge_id is not None else None
        except (TypeError, ValueError):
            knowledge_id = None
        return cls(
            object_id=str(data.get("object_id") or ""),
            title=str(data.get("title") or ""),
            knowledge_id=knowledge_id,
            duration=int(data.get("duration") or 0),
            transcribed_at=int(data.get("transcribed_at") or 0),
            language=data.get("language"),
            text=str(data.get("text") or ""),
            segments=segments,
        )

    @classmethod
    def from_transcript(
        cls,
        transcript: Transcript,
        *,
        object_id: str,
        title: str = "",
        knowledge_id: Optional[int] = None,
        duration: int = 0,
    ) -> "TranscriptRecord":
        """由转录结果构造缓存记录"""
        return cls(
            object_id=str(object_id),
            title=title,
            knowledge_id=knowledge_id,
            duration=int(duration or 0),
            transcribed_at=int(time.time()),
            language=transcript.language,
            text=transcript.text,
            segments=list(transcript.segments),
        )


class TranscriptCache:
    """转录缓存目录读写器(线程安全: 每个方法自带原子写)"""

    def __init__(self, cache_dir: str | Path = "data/transcripts") -> None:
        self.cache_dir = Path(cache_dir)

    def path_for(self, object_id: str) -> Path:
        """返回某个任务点的缓存文件路径"""
        return self.cache_dir / f"{sanitize_filename(str(object_id), fallback='transcript')}{_CACHE_SUFFIX}"

    def exists(self, object_id: str) -> bool:
        """缓存是否已存在"""
        return self.path_for(object_id).is_file()

    def load(self, object_id: str) -> Optional[TranscriptRecord]:
        """读取缓存, 不存在或损坏时返回 None"""
        return self.load_path(self.path_for(object_id))

    def load_path(self, path: str | Path) -> Optional[TranscriptRecord]:
        """读取指定缓存文件, 不存在或损坏时返回 None"""
        path = Path(path)
        if not path.is_file():
            return None
        try:
            with open(path, "r", encoding="utf8") as fp:
                data = json.load(fp)
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        return TranscriptRecord.from_dict(data)

    def save(self, record: TranscriptRecord) -> Path:
        """原子写入缓存文件

        Args:
            record: 转录记录
        Returns:
            Path: 写入的缓存文件路径
        Raises:
            TranscriptError: 写入失败
        """
        path = self.path_for(record.object_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        try:
            with open(tmp, "w", encoding="utf8") as fp:
                json.dump(record.to_dict(), fp, ensure_ascii=False, indent=2)
            tmp.replace(path)
        except OSError as err:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            raise TranscriptError(f"转录缓存写入失败 {path}: {err}") from err
        return path

    def iter_records(self) -> Iterator[TranscriptRecord]:
        """遍历缓存目录下的全部记录"""
        if not self.cache_dir.is_dir():
            return
        for path in sorted(self.cache_dir.glob(f"*{_CACHE_SUFFIX}")):
            record = self.load_path(path)
            if record is not None:
                yield record


__all__ = ["TranscriptRecord", "TranscriptCache"]