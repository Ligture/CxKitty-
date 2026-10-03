"""Transcribe an audio/video file without importing the host application."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from . import LocalSenseVoiceTranscriber, TranscriptError, extract_audio
from .asr import SUPPORTED_LANGUAGES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="音频/视频转录为 JSON (含句级时间戳)")
    parser.add_argument("input", type=Path, help="音频或视频文件")
    parser.add_argument("--model-root", type=Path, help="本地模型根目录")
    parser.add_argument("--device", default="auto", help="auto / cpu / cuda:0")
    parser.add_argument("--language", choices=SUPPORTED_LANGUAGES, default="auto")
    parser.add_argument("--no-itn", action="store_true", help="关闭逆文本正则化")
    parser.add_argument("--service-url", help="使用同机转录服务 (需安装 remote 扩展)")
    parser.add_argument("--token", default="", help="转录服务口令")
    parser.add_argument("--output", type=Path, help="JSON 输出文件, 默认标准输出")
    args = parser.parse_args(argv)
    try:
        if args.service_url:
            from .remote import RemoteSenseVoiceTranscriber

            transcriber = RemoteSenseVoiceTranscriber(args.service_url, token=args.token)
        elif args.model_root:
            transcriber = LocalSenseVoiceTranscriber.from_model_root(
                args.model_root, device=args.device
            )
        else:
            transcriber = LocalSenseVoiceTranscriber(device=args.device)
        with tempfile.TemporaryDirectory(prefix="audio-transcribe-") as directory:
            audio = extract_audio(args.input, Path(directory) / "audio.wav")
            result = transcriber.transcribe(
                audio, language=args.language, use_itn=not args.no_itn
            )
        payload = json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(payload + "\n", encoding="utf8")
        else:
            print(payload)
    except (TranscriptError, OSError, ImportError) as exc:
        print(f"转录失败: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
