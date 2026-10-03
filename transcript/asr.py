"""Compatibility alias for audio_transcription.asr."""

import sys
from audio_transcription import asr as _implementation

sys.modules[__name__] = _implementation
