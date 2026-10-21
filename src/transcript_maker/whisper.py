"""Run the faster-whisper worker in a suitable interpreter."""
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

WORKER = Path(__file__).resolve().parent / "whisper_worker.py"


def _python_cmd():
    # Use the current interpreter if faster-whisper is already installed
    # (e.g. `uv tool install 'transcript-maker[whisper]'`), otherwise let uv
    # build a throwaway Python 3.12 env, where ctranslate2 wheels exist.
    if importlib.util.find_spec("faster_whisper"):
        return [sys.executable]
    if shutil.which("uv"):
        return ["uv", "run", "--quiet", "--no-project", "--python", "3.12",
                "--with", "faster-whisper", "python"]
    sys.exit("error: Whisper needs either faster-whisper installed or `uv` on PATH")


def _run(args):
    cmd = _python_cmd() + ["-I", str(WORKER)] + [str(a) for a in args]
    res = subprocess.run(cmd, check=True, text=True, stdout=subprocess.PIPE)
    return json.loads(res.stdout)


def transcribe(audio, model):
    """Full transcription -> [(start_seconds, text), ...]."""
    return [(float(s), t) for s, t in _run(["full", audio, model])]


def transcribe_clips(audio, model, starts, length):
    """Transcribe short clips -> [text, ...], one per start time."""
    return _run(["clips", audio, model, length] + [f"{t:.2f}" for t in starts])
