"""faster-whisper worker, run in its own interpreter (usually via `uv run`).

Usage:
  whisper_worker.py full  AUDIO MODEL            -> [[start, text], ...]
  whisper_worker.py clips AUDIO MODEL LEN T1 ... -> ["text", ...]  (one per clip)

Results are printed to stdout as JSON. English only for now.
"""
import json
import os
import subprocess
import sys

import numpy as np

os.environ.setdefault("HF_HUB_VERBOSITY", "error")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

from faster_whisper import WhisperModel

SR = 16000


def decode(audio, start=None, length=None):
    # Decode with system ffmpeg rather than faster-whisper's PyAV path, which
    # breaks whenever PyAV changes its open() signature.
    cmd = ["ffmpeg", "-nostdin", "-loglevel", "error"]
    if start is not None:
        cmd += ["-ss", f"{start:.2f}", "-t", f"{length:.2f}"]
    cmd += ["-i", audio, "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"]
    pcm = subprocess.run(cmd, check=True, stdout=subprocess.PIPE).stdout
    return np.frombuffer(pcm, np.float32)


def main():
    mode, audio, model = sys.argv[1:4]
    m = WhisperModel(model, device="cpu", compute_type="int8")
    if mode == "full":
        segments, _ = m.transcribe(decode(audio), language="en", vad_filter=True)
        out = []
        for s in segments:
            out.append([round(s.start, 2), s.text.strip()])
            print(f"\r  transcribed {int(s.end) // 60:02d}:{int(s.end) % 60:02d}", end="", file=sys.stderr, flush=True)
        print(file=sys.stderr)
    elif mode == "clips":
        length = float(sys.argv[4])
        out = []
        for t in sys.argv[5:]:
            # VAD keeps Whisper from hallucinating text over music/silence.
            segments, _ = m.transcribe(decode(audio, float(t), length), language="en",
                                       vad_filter=True, condition_on_previous_text=False)
            out.append(" ".join(s.text.strip() for s in segments))
    else:
        sys.exit(f"unknown mode {mode}")
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
