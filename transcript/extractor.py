"""Compatibility alias for audio_transcription.extractor."""

import sys
from audio_transcription import extractor as _implementation

sys.modules[__name__] = _implementation
