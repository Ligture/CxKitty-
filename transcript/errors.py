"""Compatibility alias for audio_transcription.errors."""

import sys
from audio_transcription import errors as _implementation

sys.modules[__name__] = _implementation
