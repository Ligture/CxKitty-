"""Compatibility alias for audio_transcription.remote."""

import sys
from audio_transcription import remote as _implementation

sys.modules[__name__] = _implementation
