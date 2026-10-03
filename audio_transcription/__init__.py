"""Reusable audio transcription, independent of CxKitty configuration.

Heavy model dependencies are imported only when a local model is used.
"""

from .asr import (
    SUPPORTED_LANGUAGES,
    LocalSenseVoiceTranscriber,
    Transcript,
    TranscriptSegment,
    model_directory_status,
    model_root_status,
    resolve_model_paths,
)
from .errors import TranscriptError, TranscriptionError
from .extractor import extract_audio, ffmpeg_status, find_ffmpeg

__all__ = [
    "SUPPORTED_LANGUAGES",
    "LocalSenseVoiceTranscriber",
    "Transcript",
    "TranscriptSegment",
    "TranscriptError",
    "TranscriptionError",
    "model_directory_status",
    "model_root_status",
    "resolve_model_paths",
    "extract_audio",
    "ffmpeg_status",
    "find_ffmpeg",
]
