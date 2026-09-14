"""本地 SenseVoiceSmall 语音识别

移植自 ``D:\\Project\\search_via_bilibili`` 的 ``LocalSenseVoiceTranscriber``,
去除了对原项目 ``paths.py`` 的依赖, 模型目录改由 config 中的 ``transcript.model_root`` 注入。

特性:
* 懒加载(funasr 首次 import 耗时较长, 只在真正需要时执行)
* cuda / cpu 自动选择
* FSMN-VAD 切片(max_single_segment_time=30000), 句级时间戳
* 本地目录缺失时回退 modelscope 本地缓存快照
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .errors import TranscriptionError

SUPPORTED_LANGUAGES = ("auto", "zh", "en", "yue", "ja", "ko", "nospeech")
SENSEVOICE_DIRNAME = "sensevoice-small"
VAD_DIRNAME = "fsmn-vad"

_SENSEVOICE_MODEL_ID = "iic/SenseVoiceSmall"
_VAD_MODEL_ALIAS = "fsmn-vad"
_VAD_MODEL_ID = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
# 安装提示(出现在所有需要用户干预的报错里)
_INSTALL_HINT = "请执行 scripts/install-asr.ps1 安装 ASR 依赖并下载模型"


@dataclass(slots=True)
class TranscriptSegment:
    """句级转录片段"""

    start_ms: int
    end_ms: int
    text: str


@dataclass(slots=True)
class Transcript:
    """一段完整转录结果"""

    text: str
    language: Optional[str] = None
    segments: list[TranscriptSegment] = field(default_factory=list)
    raw: Any = None

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "text": self.text,
            "language": self.language,
            "segments": [asdict(segment) for segment in self.segments],
        }
        if self.raw is not None:
            value["raw"] = _jsonable(self.raw)
        return value


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    return str(value)


def _milliseconds(value: Any) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    return round(number)


def _parse_local_result(result: Any, postprocess: Callable[[str], str]) -> Transcript:
    if not isinstance(result, list) or not result or not isinstance(result[0], dict):
        raise TranscriptionError("SenseVoice 返回了非预期的结果结构")
    item = result[0]
    raw_text = str(item.get("text") or "")
    language = item.get("language")
    if not language:
        language = next(
            (code for code in SUPPORTED_LANGUAGES[1:] if raw_text.startswith(f"<|{code}|>")),
            None,
        )
    text = postprocess(raw_text).strip()
    segments = []
    for sentence in item.get("sentence_info") or []:
        if not isinstance(sentence, dict):
            continue
        segment_text = postprocess(str(sentence.get("text") or "")).strip()
        if segment_text:
            segments.append(
                TranscriptSegment(
                    start_ms=_milliseconds(sentence.get("start")),
                    end_ms=_milliseconds(sentence.get("end")),
                    text=segment_text,
                )
            )
    return Transcript(text=text, language=language, segments=segments, raw=item)


def model_directory_status(path: str | Path) -> dict[str, object]:
    """校验模型目录是否完整

    Args:
        path: 模型目录
    Returns:
        dict: ``{"path", "exists", "ready", "missing_files"}``
    """
    model_path = Path(path).expanduser()
    required_files = ("model.pt", "config.yaml")
    missing = [name for name in required_files if not (model_path / name).is_file()]
    return {
        "path": str(model_path),
        "exists": model_path.is_dir(),
        "ready": model_path.is_dir() and not missing,
        "missing_files": missing,
    }


def resolve_model_paths(model_root: str | Path) -> tuple[Path, Path]:
    """根据 model_root 推导 SenseVoice 与 FSMN-VAD 模型目录

    兼容两种布局:
    * ``model_root/{sensevoice-small,fsmn-vad}``(推荐, 与 search_via_bilibili 一致)
    * ``model_root`` 自身即为 SenseVoice 模型目录

    Args:
        model_root: 模型根目录
    Returns:
        tuple[Path, Path]: (SenseVoice 目录, FSMN-VAD 目录)
    """
    root = Path(model_root).expanduser()
    sensevoice = root / SENSEVOICE_DIRNAME
    vad = root / VAD_DIRNAME
    if not sensevoice.is_dir() and model_directory_status(root)["ready"]:
        # model_root 直接指向 SenseVoice 模型目录的布局
        return root, vad
    return sensevoice, vad


def model_root_status(model_root: str | Path) -> dict[str, object]:
    """返回模型根目录的完整就绪状态

    Args:
        model_root: 模型根目录
    Returns:
        dict: 含 ``ready`` 与两个子模型状态的字典
    """
    sensevoice, vad = resolve_model_paths(model_root)
    sv_status = model_directory_status(sensevoice)
    vad_status = model_directory_status(vad)
    return {
        "model_root": str(Path(model_root).expanduser()),
        "sensevoice": sv_status,
        "vad": vad_status,
        # FSMN-VAD 缺失时 funasr 会回退到内置 VAD, 只有主模型是硬性要求
        "ready": bool(sv_status["ready"]),
    }


def _looks_like_path(name: str) -> bool:
    """判断模型名是否为本地路径而非 modelscope 仓库 id"""
    if not name:
        return False
    if name.startswith("iic/"):
        return False
    return Path(name).is_absolute() or "/" in name or "\\" in name


def _resolve_cached_model_path(model_name: str) -> Optional[Path]:
    """返回 modelscope 本地缓存中的完整模型快照(若存在)"""

    cache_id = {
        _SENSEVOICE_MODEL_ID: _SENSEVOICE_MODEL_ID,
        _VAD_MODEL_ID: _VAD_MODEL_ID,
    }.get(model_name)
    if cache_id is None:
        return None
    try:
        from modelscope.hub.snapshot_download import snapshot_download

        path = Path(snapshot_download(cache_id, local_files_only=True))
    except Exception:  # noqa: BLE001 - 缓存缺失时必须保留原始加载错误
        return None
    if not path.is_dir():
        return None
    if not (path / "config.yaml").is_file() and not (path / "configuration.json").is_file():
        return None
    return path


def _compact_model_error(exc: Exception) -> str:
    """精简 funasr 冗长的可选依赖导入报告"""

    message = str(exc).strip()
    first_line = message.splitlines()[0] if message else exc.__class__.__name__
    if " is not registered." in first_line and "Recorded import failures:" in message:
        return f"{first_line} FunASR 可能因可选依赖导入失败而注册表不完整。"
    return message


def _is_unregistered_model_error(exc: Exception, model_name: str) -> bool:
    lines = str(exc).strip().splitlines()
    return bool(lines) and lines[0].startswith(f"model '{model_name}' is not registered.")


def _cached_retry_kwargs(
    model_name: str,
    model_kwargs: dict[str, Any],
    exc: Exception,
) -> Optional[dict[str, Any]]:
    """仅把未注册的仓库别名替换为本地缓存快照"""

    retry_kwargs = dict(model_kwargs)
    changed = False
    if _is_unregistered_model_error(exc, model_name) and model_name == _SENSEVOICE_MODEL_ID:
        cached_model = _resolve_cached_model_path(model_name)
        if cached_model is None:
            return None
        retry_kwargs["model"] = str(cached_model)
        changed = True
        cached_vad = _resolve_cached_model_path(_VAD_MODEL_ID)
        if cached_vad is not None and retry_kwargs.get("vad_model") == _VAD_MODEL_ALIAS:
            retry_kwargs["vad_model"] = str(cached_vad)
    elif _is_unregistered_model_error(exc, _VAD_MODEL_ALIAS):
        cached_vad = _resolve_cached_model_path(_VAD_MODEL_ID)
        if cached_vad is None:
            return None
        retry_kwargs["vad_model"] = str(cached_vad)
        changed = True
    return retry_kwargs if changed else None


class LocalSenseVoiceTranscriber:
    """本地 SenseVoiceSmall 转录器(进程内单例复用)"""

    def __init__(
        self,
        *,
        model: str | Path | None = None,
        vad_model: str | Path | None = None,
        device: str = "auto",
        model_factory: Optional[Callable[..., Any]] = None,
        postprocess: Optional[Callable[[str], str]] = None,
    ) -> None:
        self.model_name = str(model or _SENSEVOICE_MODEL_ID)
        self.vad_model_name = str(vad_model or _VAD_MODEL_ALIAS)
        self.device = device
        self._model_factory = model_factory
        self._postprocess = postprocess
        self._model: Any = None
        self._selected_device: Optional[str] = None

    @classmethod
    def from_model_root(
        cls,
        model_root: str | Path,
        *,
        device: str = "auto",
        **kwargs: Any,
    ) -> "LocalSenseVoiceTranscriber":
        """按 config 的 ``transcript.model_root`` 构造转录器

        Args:
            model_root: 模型根目录
            device: ``auto`` / ``cpu`` / ``cuda:0``
        Returns:
            LocalSenseVoiceTranscriber: 实例
        """
        sensevoice, vad = resolve_model_paths(model_root)
        return cls(
            model=str(sensevoice),
            vad_model=str(vad) if vad.is_dir() else _VAD_MODEL_ALIAS,
            device=device,
            **kwargs,
        )

    def _resolve_runtime(self) -> tuple[Callable[..., Any], Callable[[str], str], str]:
        try:
            import torch
            from funasr import AutoModel
            from funasr.utils.postprocess_utils import rich_transcription_postprocess
        except ImportError as exc:
            if self._model_factory is None or self._postprocess is None:
                raise TranscriptionError(
                    f"本地转录依赖缺失(funasr / torch), {_INSTALL_HINT}"
                ) from exc
            torch = None  # type: ignore[assignment]
            AutoModel = self._model_factory  # type: ignore[assignment,misc]
            rich_transcription_postprocess = self._postprocess  # type: ignore[assignment]

        selected_device = self.device
        if selected_device == "auto":
            selected_device = "cuda:0" if torch is not None and torch.cuda.is_available() else "cpu"
        return (
            self._model_factory or AutoModel,
            self._postprocess or rich_transcription_postprocess,
            selected_device,
        )

    def load(self) -> str:
        """加载模型(懒加载, 重复调用直接复用)

        Returns:
            str: 实际使用的 device
        Raises:
            TranscriptionError: 依赖缺失或模型加载失败
        """
        model_factory, _, selected_device = self._resolve_runtime()
        if self._model is None:
            if (
                self._model_factory is None
                and _looks_like_path(self.model_name)
                and not Path(self.model_name).is_dir()
            ):
                raise TranscriptionError(
                    f"SenseVoice 模型目录不存在: {self.model_name}, {_INSTALL_HINT}"
                )
            if (
                self._model_factory is None
                and _looks_like_path(self.vad_model_name)
                and not Path(self.vad_model_name).is_dir()
            ):
                raise TranscriptionError(
                    f"FSMN-VAD 模型目录不存在: {self.vad_model_name}, {_INSTALL_HINT}"
                )
            model_kwargs = {
                "model": self.model_name,
                "trust_remote_code": False,
                "disable_update": True,
                "vad_model": self.vad_model_name,
                "vad_kwargs": {"max_single_segment_time": 30000},
                "device": selected_device,
            }
            try:
                self._model = model_factory(**model_kwargs)
            except Exception as exc:  # noqa: BLE001 - 需要按错误类型决定是否回退缓存
                retry_kwargs = _cached_retry_kwargs(self.model_name, model_kwargs, exc)
                if retry_kwargs is None:
                    raise TranscriptionError(
                        f"SenseVoice 模型加载失败: {_compact_model_error(exc)}"
                    ) from exc
                try:
                    self._model = model_factory(**retry_kwargs)
                except Exception as fallback_exc:  # noqa: BLE001
                    raise TranscriptionError(
                        "从本地缓存快照加载 SenseVoice 模型失败: "
                        f"{_compact_model_error(fallback_exc)}"
                    ) from fallback_exc
        self._selected_device = selected_device
        return selected_device

    @property
    def device_in_use(self) -> Optional[str]:
        """实际使用的设备(未加载时为 None)"""
        return self._selected_device

    def transcribe(
        self,
        input_path: str | Path,
        *,
        language: str = "auto",
        use_itn: bool = True,
    ) -> Transcript:
        """转录一个 16kHz 单声道 wav 文件

        Args:
            input_path: 音频路径
            language: ``auto`` / ``zh`` / ``en`` / ``yue`` / ``ja`` / ``ko``
            use_itn: 是否启用逆文本正则化(数字、标点)
        Returns:
            Transcript: 转录结果
        Raises:
            TranscriptionError: 音频缺失或转录失败
        """
        path = Path(input_path)
        if not path.is_file():
            raise TranscriptionError(f"音频文件不存在: {path}")
        _, postprocess, _ = self._resolve_runtime()
        self.load()
        try:
            result = self._model.generate(
                input=str(path.resolve()),
                cache={},
                language=language,
                use_itn=use_itn,
                batch_size_s=60,
                merge_vad=True,
                merge_length_s=15,
                sentence_timestamp=True,
            )
        except Exception as exc:  # noqa: BLE001 - 统一转换为管道异常
            raise TranscriptionError(f"SenseVoice 转录失败 {path}: {exc}") from exc
        return _parse_local_result(result, postprocess)


__all__ = [
    "SUPPORTED_LANGUAGES",
    "SENSEVOICE_DIRNAME",
    "VAD_DIRNAME",
    "Transcript",
    "TranscriptSegment",
    "LocalSenseVoiceTranscriber",
    "model_directory_status",
    "model_root_status",
    "resolve_model_paths",
]