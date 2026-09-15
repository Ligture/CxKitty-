"""CxKitty 本地转录服务(进程外复用同一份 SenseVoice 模型)

多账号同时挂课时, 每个 ``main.py`` 进程各自加载一份模型会造成重复占用(实测每份常驻约
1.7GB / 提交约 3.5GB / 显存约 1.1GB)。本模块把模型单独放进一个进程, 多个主进程通过本机
HTTP 提交音频路径即可复用同一份模型; 下载、ffmpeg 提取、缓存写入仍在各自的主进程内完成。

启动::

    poetry run python -m transcript.server                       # 复用 config.yml 的模型路径
    poetry run python -m transcript.server --model-root D:/models --port 8765
    start_asr_service.bat                                        # Windows 一键启动

接口(默认只监听 127.0.0.1, 跨机部署请自行加 ``--token``)::

    GET  /health      服务 / 模型 / 队列状态
    POST /transcribe  {"audio_path": "绝对路径", "object_id": "...", ...} -> 转录结果
    POST /unload      释放模型(下次请求再懒加载)

设计要点:

* 单模型 + 单推理线程: 请求排队串行执行, 多个账号同时提交也不会把显存打爆
* 模型懒加载; ``--idle-unload`` 可在空闲若干秒后自动释放
* 可选服务端缓存(``--cache-path``): 多个账号各自的 ``transcripts/`` 目录也能复用同一份文稿
"""

from __future__ import annotations

import argparse
import gc
import hmac
import json
import logging
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from logger import Logger

from .asr import LocalSenseVoiceTranscriber, Transcript, model_root_status
from .cache import TranscriptCache, TranscriptRecord
from .errors import TranscriptError, TranscriptionError
from .remote import TOKEN_HEADER

#: 默认监听地址与端口(仅本机回环)
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
#: 请求体上限: 只传音频路径, 正常请求不足 1KB
_MAX_BODY = 64 * 1024
_SERVICE_NAME = "cxkitty-transcript"


@dataclass
class _Stats:
    """服务累计计数"""

    served: int = 0
    cached: int = 0
    failed: int = 0
    started_at: float = field(default_factory=time.monotonic)


class TranscriptService:
    """模型持有者: 串行执行转录请求, 支持懒加载 / 空闲卸载 / 可选缓存"""

    def __init__(
        self,
        *,
        model_root: str = "",
        device: str = "auto",
        cache_path: str = "",
        idle_unload: float = 0.0,
        transcriber_factory: Optional[Callable[[], Any]] = None,
        logger: Optional[Logger] = None,
        version: str = "",
    ) -> None:
        """
        Args:
            model_root: SenseVoice / FSMN-VAD 模型根目录
            device: ``auto`` / ``cuda:0`` / ``cpu``
            cache_path: 服务端缓存目录, 留空表示不缓存
            idle_unload: 空闲多少秒后释放模型, ``0`` 表示不释放
            transcriber_factory: 测试注入用的转录器工厂(默认加载本地模型)
            logger: 日志记录器
            version: 版本号, 仅用于 ``/health``
        """
        self.model_root = str(model_root or "")
        self.device = str(device or "auto")
        self.cache_path = str(cache_path or "")
        self.idle_unload = max(0.0, float(idle_unload or 0.0))
        self.transcriber_factory = transcriber_factory
        self.version = str(version or "")
        self.logger = logger or Logger("TranscriptSvc")
        self.stats = _Stats()

        self._cache = TranscriptCache(self.cache_path) if self.cache_path else None
        self._transcriber: Optional[Any] = None
        self._run_lock = threading.Lock()  # 串行化推理(GPU 上只允许一路)
        self._model_lock = threading.Lock()  # 保护模型加载 / 卸载
        self._state_lock = threading.Lock()  # 保护排队计数
        self._waiting = 0
        self._running = False
        self._last_activity = time.monotonic()
        self._stop = threading.Event()
        self._idle_thread: Optional[threading.Thread] = None

    # ---------------- 状态 ----------------

    def status(self) -> dict[str, Any]:
        """返回服务状态(``/health`` 响应体)"""
        transcriber = self._transcriber
        with self._state_lock:
            waiting = self._waiting
            running = self._running
        return {
            "ok": True,
            "service": _SERVICE_NAME,
            "version": self.version,
            "device": transcriber.device_in_use if transcriber else None,
            "configured_device": self.device,
            "model_root": self.model_root,
            "model_loaded": transcriber is not None,
            "cache_enabled": self._cache is not None,
            "cache_path": self.cache_path,
            "idle_unload": self.idle_unload or None,
            "running": running,
            "waiting": waiting,
            "served": self.stats.served,
            "cached": self.stats.cached,
            "failed": self.stats.failed,
            "uptime": round(time.monotonic() - self.stats.started_at, 1),
        }

    def record_failure(self) -> None:
        """记录一次失败请求"""
        with self._state_lock:
            self.stats.failed += 1

    # ---------------- 转录 ----------------

    def transcribe(self, request: dict[str, Any]) -> dict[str, Any]:
        """执行一次转录请求(多客户端自动排队)

        Args:
            request: HTTP 请求体, 至少包含绝对路径 ``audio_path``;
                可带 ``object_id`` / ``title`` / ``knowledge_id`` / ``duration`` / ``language`` / ``use_itn``
        Returns:
            dict: 转录结果(``text`` / ``language`` / ``segments`` / ``device`` / ``cached`` / ``elapsed``)
        Raises:
            TranscriptError: 请求参数或音频文件不合法
            TranscriptionError: 模型不可用 / 转录失败
        """
        audio = self._resolve_audio(request.get("audio_path"))
        object_id = str(request.get("object_id") or "").strip()
        title = str(request.get("title") or "")
        job = {
            "object_id": object_id,
            "title": title,
            "knowledge_id": _as_int(request.get("knowledge_id")),
            "duration": _as_int(request.get("duration")) or 0,
        }
        started = time.monotonic()

        with self._slot():
            cached = self._load_cached(object_id)
            if cached is not None:
                with self._state_lock:
                    self.stats.cached += 1
                self.logger.info(f"服务端缓存命中 [{title or object_id}]")
                return self._result(
                    cached,
                    device=self._current_device(),
                    cached=True,
                    elapsed=time.monotonic() - started,
                )

            transcriber = self._ensure_transcriber()
            self.logger.info(f"开始转录 [{title or object_id}] {audio.name}")
            transcript = transcriber.transcribe(
                audio,
                language=str(request.get("language") or "auto"),
                use_itn=bool(request.get("use_itn", True)),
                job=job,
            )
            if not transcript.text.strip():
                raise TranscriptionError(f"转录结果为空 [{title or object_id}]")
            self._save_cached(transcript, job)

        with self._state_lock:
            self.stats.served += 1
        elapsed = time.monotonic() - started
        self.logger.info(
            f"转录完成 [{title or object_id}] {len(transcript.text)} 字 / "
            f"{len(transcript.segments)} 句, 耗时 {elapsed:.1f}s"
        )
        return self._result(
            transcript, device=self._current_device(), cached=False, elapsed=elapsed
        )

    def unload(self, *, reason: str = "手动") -> bool:
        """释放模型占用的内存与显存

        Args:
            reason: 日志中展示的原因
        Returns:
            bool: 是否真的释放了模型
        """
        with self._model_lock:
            if self._transcriber is None:
                return False
            self._transcriber = None
        gc.collect()
        torch = sys.modules.get("torch")
        if torch is not None:
            try:
                torch.cuda.empty_cache()
            except Exception:  # noqa: BLE001 - 无 CUDA 时忽略
                pass
        self.logger.info(f"已释放 SenseVoice 模型({reason}), 下次请求自动重新加载")
        return True

    def close(self) -> None:
        """停止后台线程(不卸载模型, 进程退出即可回收)"""
        self._stop.set()
        thread = self._idle_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    # ---------------- 后台空闲卸载 ----------------

    def start_idle_watch(self) -> None:
        """按 ``idle_unload`` 启动空闲卸载线程(幂等)"""
        if self.idle_unload <= 0 or self._idle_thread is not None:
            return
        self._idle_thread = threading.Thread(
            target=self._idle_loop, name="TranscriptIdleWatch", daemon=True
        )
        self._idle_thread.start()
        self.logger.info(f"空闲卸载已开启: 闲置 {self.idle_unload:.0f}s 后释放模型")

    def _idle_loop(self) -> None:
        interval = max(1.0, min(30.0, self.idle_unload / 5.0))
        while not self._stop.wait(interval):
            if self._transcriber is None or self._running:
                continue
            if time.monotonic() - self._last_activity < self.idle_unload:
                continue
            self.unload(reason=f"空闲 {self.idle_unload:.0f}s")

    # ---------------- 内部实现 ----------------

    @contextmanager
    def _slot(self) -> Iterator[None]:
        """排队 + 串行执行(同时供 ``/health`` 读取队列深度)"""
        with self._state_lock:
            self._waiting += 1
        try:
            self._run_lock.acquire()
        finally:
            with self._state_lock:
                self._waiting -= 1
        with self._state_lock:
            self._running = True
        try:
            yield
        finally:
            with self._state_lock:
                self._running = False
            self._last_activity = time.monotonic()
            self._run_lock.release()

    def _ensure_transcriber(self) -> Any:
        """返回进程内单例转录器(首次调用加载模型)"""
        with self._model_lock:
            if self._transcriber is not None:
                return self._transcriber
            if self.transcriber_factory is not None:
                transcriber = self.transcriber_factory()
            else:
                if not self.model_root:
                    raise TranscriptionError(
                        "未配置模型目录, 请用 --model-root 指定(或在 config.yml 设置 transcript.model_root)"
                    )
                status = model_root_status(self.model_root)
                if not status["ready"]:
                    raise TranscriptionError(
                        f"SenseVoice 模型未就绪: {status['sensevoice']} "
                        "(可执行 scripts/install-asr.ps1 下载模型)"
                    )
                transcriber = LocalSenseVoiceTranscriber.from_model_root(
                    self.model_root, device=self.device
                )
            self.logger.info(f"正在加载 SenseVoiceSmall 模型, device={self.device} (首次较慢)")
            started = time.monotonic()
            device = transcriber.load()
            self._transcriber = transcriber
            self.logger.info(f"模型加载完成 device={device}, 耗时 {time.monotonic() - started:.1f}s")
            return transcriber

    def _current_device(self) -> Optional[str]:
        transcriber = self._transcriber
        return transcriber.device_in_use if transcriber else None

    @staticmethod
    def _resolve_audio(raw: Any) -> Path:
        if not raw:
            raise TranscriptError("请求缺少 audio_path")
        path = Path(str(raw)).expanduser()
        if not path.is_absolute():
            raise TranscriptError(f"audio_path 必须是绝对路径: {raw}")
        if not path.is_file():
            raise TranscriptError(f"音频文件不存在: {path}")
        return path

    def _load_cached(self, object_id: str) -> Optional[TranscriptRecord]:
        if self._cache is None or not object_id:
            return None
        record = self._cache.load(object_id)
        if record is None or not record.text.strip():
            return None
        return record

    def _save_cached(self, transcript: Transcript, job: dict[str, Any]) -> None:
        if self._cache is None or not job["object_id"]:
            return
        record = TranscriptRecord.from_transcript(
            transcript,
            object_id=job["object_id"],
            title=job["title"],
            knowledge_id=job["knowledge_id"],
            duration=job["duration"],
        )
        try:
            self._cache.save(record)
        except TranscriptError as err:  # 缓存失败不影响本次结果
            self.logger.warning(f"服务端缓存写入失败: {err}")

    @staticmethod
    def _result(
        transcript: Any,
        *,
        device: Optional[str],
        cached: bool,
        elapsed: float,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "text": transcript.text,
            "language": transcript.language,
            "segments": [asdict(segment) for segment in transcript.segments],
            "device": device,
            "cached": bool(cached),
            "elapsed": round(float(elapsed), 3),
        }


def _read_version() -> str:
    """从 pyproject.toml 读取版本号

    不导入 ``utils``: 那会连带拉起 ``cxapi`` 依赖链(且与 ``utils`` 存在循环导入),
    对只负责推理的服务进程没有意义。
    """

    candidates = [
        Path(__file__).resolve().parent.parent / "pyproject.toml",
        Path("pyproject.toml"),
    ]
    for path in candidates:
        try:
            return path.read_text(encoding="utf8").split("version = ")[1].split("\n")[0].strip('"')
        except (OSError, IndexError):
            continue
    return ""


def _as_int(value: Any) -> Optional[int]:
    """把可选的 id / 时长转换成 int"""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class _TranscriptHTTPServer(ThreadingHTTPServer):
    """带服务与口令引用的 HTTP 服务器"""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self, address: tuple[str, int], service: TranscriptService, token: str = ""
    ) -> None:
        self.service = service
        self.token = str(token or "")
        super().__init__(address, _RequestHandler)


class _RequestHandler(BaseHTTPRequestHandler):
    """极简 JSON 路由: /health /transcribe /unload"""

    server_version = "CxKittyTranscript/1.0"
    protocol_version = "HTTP/1.1"

    @property
    def _service(self) -> TranscriptService:
        return self.server.service  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003 - 覆盖基类
        self._service.logger.debug(f"{self.address_string()} {fmt % args}")

    def _authorized(self) -> bool:
        token = getattr(self.server, "token", "")
        if not token:
            return True
        provided = self.headers.get(TOKEN_HEADER) or ""
        return hmac.compare_digest(provided, token)

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):  # 客户端提前断开
            pass

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        if length <= 0:
            return {}
        if length > _MAX_BODY:
            raise TranscriptError(f"请求体过大({length} 字节)")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as err:
            raise TranscriptError(f"请求体不是合法 JSON: {err}") from err
        if not isinstance(data, dict):
            raise TranscriptError("请求体必须是 JSON 对象")
        return data

    def do_GET(self) -> None:  # noqa: N802 - 覆盖基类
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path != "/health":
            self._send(404, {"ok": False, "error": f"未知接口 {path}"})
            return
        if not self._authorized():
            self._send(401, {"ok": False, "error": "口令校验失败"})
            return
        self._send(200, self._service.status())

    def do_POST(self) -> None:  # noqa: N802 - 覆盖基类
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path not in ("/transcribe", "/unload"):
            self._send(404, {"ok": False, "error": f"未知接口 {path}"})
            return
        if not self._authorized():
            self._send(401, {"ok": False, "error": "口令校验失败"})
            return
        try:
            if path == "/unload":
                unloaded = self._service.unload(reason="客户端请求")
                self._send(200, {"ok": True, "unloaded": unloaded})
                return
            self._send(200, self._service.transcribe(self._read_json()))
        except TranscriptionError as err:
            self._service.record_failure()
            self._service.logger.warning(f"转录失败: {err}")
            self._send(503, {"ok": False, "error": str(err)})
        except TranscriptError as err:
            self._service.record_failure()
            self._service.logger.warning(f"请求被拒绝: {err}")
            self._send(400, {"ok": False, "error": str(err)})
        except Exception as err:  # noqa: BLE001 - 服务端绝不因单个请求崩溃
            self._service.record_failure()
            self._service.logger.error(f"处理请求异常: {err}", exc_info=True)
            self._send(500, {"ok": False, "error": f"服务内部错误: {err}"})


def make_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    service: Optional[TranscriptService] = None,
    *,
    token: str = "",
) -> _TranscriptHTTPServer:
    """创建(但不启动)HTTP 服务器; ``port=0`` 由系统分配端口(测试用)"""
    if service is None:
        service = TranscriptService()
    return _TranscriptHTTPServer((host, int(port)), service, token)


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器"""
    parser = argparse.ArgumentParser(
        prog="python -m transcript.server",
        description="CxKitty 本地转录服务: 多账号复用同一份 SenseVoice 模型",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="监听地址(默认仅本机 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"监听端口(默认 {DEFAULT_PORT})")
    parser.add_argument("--model-root", default=None, help="模型根目录, 默认取 config.yml")
    parser.add_argument("--device", default=None, help="auto / cuda:0 / cpu, 默认取 config.yml")
    parser.add_argument(
        "--cache-path",
        default=None,
        help="服务端缓存目录(多账号共享可跨账号去重), 默认取 config.yml 的 transcript.cache_path",
    )
    parser.add_argument("--no-cache", action="store_true", help="关闭服务端缓存")
    parser.add_argument(
        "--idle-unload",
        type=float,
        default=None,
        help="空闲多少秒后释放模型(0=不释放, 默认 0)",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="共享口令, 客户端用 transcript.service_token 填写; 跨机部署务必设置",
    )
    return parser


def _build_logger() -> Logger:
    """给服务日志挂上控制台与文件 handler(幂等)"""
    logger = Logger("TranscriptSvc")
    raw = logger.logger
    if getattr(raw, "_cxkitty_service_handler", False):
        return logger
    raw.propagate = False
    formatter = logging.Formatter(logger.fmt)
    stream = logging.StreamHandler(sys.stdout)
    stream.setLevel(logging.INFO)
    stream.setFormatter(formatter)
    raw.addHandler(stream)
    try:
        import config as cfg

        cfg.LOGS_PATH.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(cfg.LOGS_PATH / "transcript.log", encoding="utf8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        raw.addHandler(file_handler)
    except Exception:  # noqa: BLE001 - 目录不可写时只保留控制台
        pass
    raw._cxkitty_service_handler = True  # type: ignore[attr-defined]
    return logger


def main(argv: Optional[list[str]] = None) -> int:
    """服务进程入口"""
    args = build_parser().parse_args(argv)

    import config as cfg

    transcript_cfg = getattr(cfg, "TRANSCRIPT", None)
    if not isinstance(transcript_cfg, dict):
        transcript_cfg = {}

    model_root = (
        args.model_root
        if args.model_root is not None
        else str(transcript_cfg.get("model_root") or "")
    )
    device = args.device if args.device is not None else str(transcript_cfg.get("device") or "auto")
    cache_path = (
        ""
        if args.no_cache
        else (
            args.cache_path
            if args.cache_path is not None
            else str(transcript_cfg.get("cache_path") or "")
        )
    )
    token = args.token if args.token is not None else str(transcript_cfg.get("service_token") or "")
    idle_unload = 0.0 if args.idle_unload is None else max(0.0, args.idle_unload)

    version = _read_version()

    logger = _build_logger()
    service = TranscriptService(
        model_root=model_root,
        device=device,
        cache_path=cache_path,
        idle_unload=idle_unload,
        logger=logger,
        version=version,
    )
    try:
        httpd = make_server(args.host, args.port, service, token=token)
    except OSError as err:
        logger.error(f"无法监听 {args.host}:{args.port} -> {err}")
        print(f"端口被占用或地址不可用: {args.host}:{args.port} ({err})")
        return 1

    service.start_idle_watch()
    host, port = str(httpd.server_address[0]), int(httpd.server_address[1])
    if host not in ("127.0.0.1", "localhost", "::1") and not token:
        logger.warning("正在监听非本机地址且未设置 --token, 任何能访问该端口的人都可以提交转录请求")

    console_lines = [
        "",
        "  CxKitty 转录服务已启动",
        f"  地址    : http://{host}:{port}",
        f"  模型    : {model_root or '(未配置, 请用 --model-root 指定)'}",
        f"  设备    : {device} (懒加载, 首个请求时才占用显存/内存)",
        f"  缓存    : {cache_path or '(已关闭)'}",
        f"  空闲卸载: {f'{idle_unload:.0f}s' if idle_unload > 0 else '关闭'}",
        f"  口令    : {'已启用' if token else '未启用(仅本机可用)'}",
        f"  客户端  : transcript.mode=service / service_url=http://127.0.0.1:{port}",
        "  停止    : Ctrl+C",
        "",
    ]
    print("\n".join(console_lines), flush=True)
    logger.info(f"转录服务启动 http://{host}:{port} model_root={model_root or '(未配置)'}")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n收到中断, 正在停止服务...", flush=True)
    finally:
        service.close()
        httpd.server_close()
        status = service.status()
        logger.info(
            f"转录服务停止 (累计转录 {status['served']} / 缓存命中 {status['cached']} / 失败 {status['failed']})"
        )
        print(
            f"服务已停止: 转录 {status['served']} 次, 缓存命中 {status['cached']} 次, 失败 {status['failed']} 次",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
