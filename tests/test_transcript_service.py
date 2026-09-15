"""转录服务(进程外模型)测试

全部用假转录器, 不加载真实模型、不依赖 GPU:

    poetry run python -m unittest discover -s tests -v
"""

from __future__ import annotations

import logging
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from transcript.asr import Transcript, TranscriptSegment
from transcript.errors import TranscriptionError
from transcript.remote import RemoteSenseVoiceTranscriber, probe_service
from transcript.server import TranscriptService, make_server


class FakeTranscriber:
    """假转录器: 记录调用、模拟耗时/失败/并发"""

    def __init__(self, text: str = "这是一段测试文稿", device: str = "cpu") -> None:
        self.text = text
        self._device = device
        self.calls: list[dict] = []
        self.delay = 0.0
        self.error: Exception | None = None
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def load(self) -> str:
        return self._device

    @property
    def device_in_use(self) -> str:
        return self._device

    def transcribe(self, input_path, *, language="auto", use_itn=True, job=None) -> Transcript:
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                time.sleep(self.delay)
            if self.error is not None:
                raise self.error
            self.calls.append(
                {
                    "path": Path(input_path),
                    "language": language,
                    "use_itn": use_itn,
                    "job": job,
                }
            )
            return Transcript(
                text=self.text,
                language="zh",
                segments=[TranscriptSegment(start_ms=0, end_ms=1200, text=self.text)],
            )
        finally:
            with self._lock:
                self.active -= 1


class ServiceTestCase(unittest.TestCase):
    """基类: 起一个测试用的服务进程内 HTTP 服务"""

    token = ""
    use_cache = False

    def setUp(self) -> None:
        # 测试期间不要污染控制台(root logger 的 lastResort)
        service_logger = logging.getLogger("TranscriptSvc")
        service_logger.propagate = False
        if not service_logger.handlers:
            service_logger.addHandler(logging.NullHandler())
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.audio = self.tmp / "audio.wav"
        self.audio.write_bytes(b"RIFF....WAVEfmt " + b"\0" * 64)

        self.transcriber = FakeTranscriber()
        self.service = TranscriptService(
            model_root=str(self.tmp / "models"),
            device="cpu",
            cache_path=str(self.tmp / "server-cache") if self.use_cache else "",
            transcriber_factory=lambda: self.transcriber,
        )
        self.httpd = make_server("127.0.0.1", 0, self.service, token=self.token)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()

    def tearDown(self) -> None:
        self.service.close()
        self.httpd.shutdown()
        self.httpd.server_close()
        self._thread.join(timeout=5)
        self._tmp.cleanup()

    def client(self, *, token: str | None = None) -> RemoteSenseVoiceTranscriber:
        return RemoteSenseVoiceTranscriber(self.url, token=self.token if token is None else token)

    def job(self, **overrides) -> dict:
        payload = {"object_id": "obj-1", "title": "示例视频", "knowledge_id": 123}
        payload.update(overrides)
        return payload


class ServiceProtocolTests(ServiceTestCase):
    def test_health_reports_service_state(self) -> None:
        client = self.client()
        info = client.health()
        self.assertTrue(info["ok"])
        self.assertEqual(info["service"], "cxkitty-transcript")
        self.assertFalse(info["model_loaded"])
        self.assertEqual(info["waiting"], 0)

    def test_transcribe_round_trip(self) -> None:
        client = self.client()
        client.load()

        transcript = client.transcribe(self.audio, language="zh", use_itn=False, job=self.job())

        self.assertEqual(transcript.text, "这是一段测试文稿")
        self.assertEqual(transcript.language, "zh")
        self.assertEqual(len(transcript.segments), 1)
        self.assertEqual(transcript.segments[0].end_ms, 1200)
        self.assertEqual(client.device_in_use, "cpu")

        call = self.transcriber.calls[0]
        self.assertEqual(call["language"], "zh")
        self.assertFalse(call["use_itn"])
        self.assertEqual(call["job"]["object_id"], "obj-1")

        info = client.health()
        self.assertEqual(info["served"], 1)
        self.assertEqual(info["failed"], 0)
        self.assertTrue(info["model_loaded"])

    def test_missing_audio_is_rejected(self) -> None:
        client = self.client()
        with self.assertRaises(TranscriptionError) as ctx:
            client.transcribe(self.tmp / "nope.wav")
        self.assertIn("音频文件不存在", str(ctx.exception))
        self.assertEqual(self.transcriber.calls, [])

    def test_relative_path_rejected_by_server(self) -> None:
        # 客户端会把路径转成绝对路径, 这里直接向服务端发一个相对路径
        response = self.client()._session.post(  # noqa: SLF001 - 直接构造非法请求体
            f"{self.url}/transcribe",
            json={"audio_path": "audio.wav"},
            timeout=5,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("绝对路径", response.json()["error"])

    def test_unknown_route_returns_404(self) -> None:
        response = self.client()._session.get(f"{self.url}/nope", timeout=5)  # noqa: SLF001
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.json()["ok"])

    def test_transcription_error_becomes_503(self) -> None:
        self.transcriber.error = TranscriptionError("模型炸了")
        client = self.client()
        with self.assertRaises(TranscriptionError) as ctx:
            client.transcribe(self.audio, job=self.job())
        self.assertIn("模型炸了", str(ctx.exception))
        self.assertEqual(client.health()["failed"], 1)

    def test_requests_are_serialized(self) -> None:
        self.transcriber.delay = 0.25
        results: list[str] = []
        errors: list[Exception] = []

        def run(index: int) -> None:
            try:
                client = self.client()
                transcript = client.transcribe(self.audio, job=self.job(object_id=f"obj-{index}"))
                results.append(transcript.text)
            except Exception as err:  # noqa: BLE001 - 测试里收集异常
                errors.append(err)

        threads = [threading.Thread(target=run, args=(i,)) for i in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 3)
        self.assertEqual(self.transcriber.max_active, 1, "服务端必须串行执行转录")


class ServiceCacheTests(ServiceTestCase):
    use_cache = True

    def test_second_request_hits_server_cache(self) -> None:
        client = self.client()
        first = client.transcribe(self.audio, job=self.job())
        second = client.transcribe(self.audio, job=self.job())

        self.assertEqual(first.text, second.text)
        self.assertEqual(len(self.transcriber.calls), 1, "缓存命中时不应再次推理")
        info = client.health()
        self.assertEqual(info["served"], 1)
        self.assertEqual(info["cached"], 1)

    def test_cache_file_is_written_with_job_metadata(self) -> None:
        client = self.client()
        client.transcribe(self.audio, job=self.job())
        cached = list(Path(self.service.cache_path).glob("*.json"))
        self.assertEqual(len(cached), 1)
        payload = cached[0].read_text(encoding="utf8")
        self.assertIn("obj-1", payload)
        self.assertIn("示例视频", payload)
        self.assertIn("123", payload)


class ServiceTokenTests(ServiceTestCase):
    token = "secret-token"

    def test_health_requires_token(self) -> None:
        with self.assertRaises(TranscriptionError) as ctx:
            self.client(token="").health()
        self.assertIn("401", str(ctx.exception))

    def test_transcribe_with_token(self) -> None:
        transcript = self.client().transcribe(self.audio, job=self.job())
        self.assertEqual(transcript.text, "这是一段测试文稿")

    def test_wrong_token_rejected(self) -> None:
        with self.assertRaises(TranscriptionError):
            self.client(token="wrong").health()


class ServiceLifecycleTests(ServiceTestCase):
    def test_unload_endpoint(self) -> None:
        client = self.client()
        client.transcribe(self.audio, job=self.job())
        self.assertTrue(client.health()["model_loaded"])

        self.assertTrue(client.unload())
        self.assertFalse(client.health()["model_loaded"])
        self.assertFalse(client.unload(), "重复卸载应返回 False")

    def test_idle_unload_releases_model(self) -> None:
        self.service.idle_unload = 0.2
        self.service.start_idle_watch()
        client = self.client()
        client.transcribe(self.audio, job=self.job())
        self.assertTrue(client.health()["model_loaded"])

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if not client.health()["model_loaded"]:
                break
            time.sleep(0.2)
        self.assertFalse(client.health()["model_loaded"])

    def test_probe_service_reports_unreachable(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self._thread.join(timeout=5)

        result = probe_service(self.url, timeout=0.5)
        self.assertFalse(result["ready"])
        self.assertTrue(result["detail"])


class WorkerSettingsTests(unittest.TestCase):
    """配置解析: 服务模式的键要能正确归一化"""

    def setUp(self) -> None:
        import transcript.worker as worker

        self.worker = worker
        self._original = getattr(worker.cfg, "TRANSCRIPT", None)

    def tearDown(self) -> None:
        self.worker.cfg.TRANSCRIPT = self._original

    def test_service_mode_normalized(self) -> None:
        self.worker.cfg.TRANSCRIPT = {
            "enable": True,
            "mode": "remote",
            "service_url": "  http://127.0.0.1:9999  ",
            "service_timeout": "30",
            "service_fallback_local": 1,
        }
        sett = self.worker.settings()
        self.assertEqual(sett["mode"], "service")
        self.assertEqual(sett["service_url"], "http://127.0.0.1:9999")
        self.assertEqual(sett["service_timeout"], 30.0)
        self.assertTrue(sett["service_fallback_local"])

    def test_invalid_mode_falls_back_to_local(self) -> None:
        self.worker.cfg.TRANSCRIPT = {"enable": True, "mode": "云端", "service_timeout": "abc"}
        sett = self.worker.settings()
        self.assertEqual(sett["mode"], "local")
        self.assertEqual(sett["service_timeout"], 900.0)

    def test_service_status_reports_unreachable_without_raising(self) -> None:
        status = self.worker.service_status({"service_url": "", "service_token": ""})
        self.assertIn("ready", status)
        if not status["ready"]:
            self.assertTrue(status["detail"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
