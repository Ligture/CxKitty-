"""Module isolation and transcription regressions without model/GPU dependencies."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from audio_transcription import LocalSenseVoiceTranscriber, TranscriptionError
from audio_transcription.__main__ import main
from audio_transcription.asr import Transcript
from audio_transcription.extractor import extract_audio


class AudioTranscriptionTests(unittest.TestCase):
    def test_package_can_be_copied_and_imported_without_host_or_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(__file__).resolve().parents[1] / "audio_transcription"
            shutil.copytree(package, Path(directory) / "audio_transcription")
            result = subprocess.run(
                [sys.executable, "-S", "-c",
                 "import sys; import audio_transcription; "
                 "assert not any(n in sys.modules for n in "
                 "('core', 'transcript', 'torch', 'funasr', 'requests'))"],
                cwd=directory, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            help_result = subprocess.run(
                [sys.executable, "-S", "-m", "audio_transcription", "--help"],
                cwd=directory, capture_output=True,
            )
            self.assertEqual(help_result.returncode, 0, help_result.stderr)

    def test_local_model_reuse_and_segment_conversion(self):
        model = mock.Mock()
        model.generate.return_value = [{
            "text": "<|zh|>测试", "sentence_info": [
                {"start": 0, "end": 1234, "text": "<|zh|>测试"}
            ],
        }]
        factory = mock.Mock(return_value=model)
        transcriber = LocalSenseVoiceTranscriber(
            device="cpu", model_factory=factory,
            postprocess=lambda text: text.replace("<|zh|>", ""),
        )
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "input.wav"
            audio.write_bytes(b"RIFF")
            first = transcriber.transcribe(audio, language="zh", use_itn=False)
            second = transcriber.transcribe(audio)
        factory.assert_called_once()
        self.assertEqual(first.text, second.text)
        self.assertEqual(first.language, "zh")
        self.assertEqual(first.to_dict()["segments"][0]["end_ms"], 1234)
        self.assertEqual(transcriber.device_in_use, "cpu")
        self.assertFalse(model.generate.call_args_list[0].kwargs["use_itn"])

    def test_missing_input_does_not_load_model(self):
        factory = mock.Mock()
        transcriber = LocalSenseVoiceTranscriber(model_factory=factory)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(TranscriptionError):
                transcriber.transcribe(Path(directory) / "missing.wav")
        factory.assert_not_called()

    def test_extraction_timeout_removes_partial_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.mp4"
            source.write_bytes(b"video")
            target = Path(directory) / "output.wav"
            partial = target.with_name(target.name + ".part.wav")
            partial.write_bytes(b"partial")
            with mock.patch("audio_transcription.extractor.subprocess.run",
                            side_effect=subprocess.TimeoutExpired("ffmpeg", 1)):
                from audio_transcription import TranscriptError

                with self.assertRaises(TranscriptError):
                    extract_audio(source, target, ffmpeg="ffmpeg", timeout=1)
            self.assertFalse(partial.exists())
            self.assertFalse(target.exists())

    def test_cli_outputs_json_and_cleans_temporary_audio(self):
        transcriber = mock.Mock()
        transcriber.transcribe.return_value = Transcript(text="测试", language="zh")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nested" / "result.json"
            with mock.patch("audio_transcription.__main__.extract_audio",
                            side_effect=lambda source, dest: dest) as extract, \
                 mock.patch("audio_transcription.__main__.LocalSenseVoiceTranscriber",
                            return_value=transcriber):
                self.assertEqual(main(["input.mp4", "--output", str(output)]), 0)
            self.assertEqual(json.loads(output.read_text(encoding="utf8"))["text"], "测试")
            self.assertFalse(extract.call_args.args[1].parent.exists())

    def test_legacy_imports_share_classes_and_modules(self):
        import audio_transcription.asr as new
        import transcript.asr as old
        from transcript.errors import TranscriptionError as old_error

        self.assertIs(old, new)
        self.assertIs(old.Transcript, new.Transcript)
        self.assertIs(old_error, TranscriptionError)


if __name__ == "__main__":
    unittest.main()
