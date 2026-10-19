"""Transcribe an audio file with faster-whisper; print [[start, text], ...] as JSON.

Usage: whisper_transcribe.py AUDIO MODEL [LANG]
"""
import json
import subprocess
import sys

import numpy as np

from faster_whisper import WhisperModel

audio, model = sys.argv[1], sys.argv[2]
lang = sys.argv[3] if len(sys.argv) > 3 else None

m = WhisperModel(model, device="cpu", compute_type="int8")
# Decode with system ffmpeg rather than faster-whisper's PyAV path, which
# breaks whenever PyAV changes its open() signature.
pcm = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", audio,
                      "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
                     check=True, stdout=subprocess.PIPE).stdout
segments, info = m.transcribe(np.frombuffer(pcm, np.float32), language=lang, vad_filter=True)
print(f"Detected language: {info.language}", file=sys.stderr)
json.dump([[round(s.start, 2), s.text.strip()] for s in segments], sys.stdout)
