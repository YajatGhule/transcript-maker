#!/usr/bin/env python3
"""Fetch a YouTube video's transcript as clean, timestamped text.

Strategy:
  1. Use YouTube's own captions (manual first, then auto-generated) via yt-dlp.
  2. If none exist (or --whisper is given), download the audio and transcribe it
     locally with faster-whisper (run through `uv`, no global install needed).

Output is written to ~/.cache/yt-transcript/<video_id>/transcript.txt and the
path is printed on the last line as `TRANSCRIPT_FILE=<path>`.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

CACHE = Path(os.environ.get("YT_TRANSCRIPT_CACHE", Path.home() / ".cache" / "yt-transcript"))
HERE = Path(__file__).resolve().parent
PARAGRAPH_SECONDS = 30


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, text=True, **kw)


def fmt_ts(sec):
    sec = int(sec)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def parse_ts(ts):
    parts = ts.replace(",", ".").split(":")
    parts = [float(p) for p in parts]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def vtt_to_segments(text):
    """Parse VTT into (start_seconds, line) pairs, removing the rolling
    duplicate lines that YouTube auto-captions produce."""
    segments = []
    last = None
    start = None
    for block in re.split(r"\n\s*\n", text):
        lines = block.strip().splitlines()
        for i, line in enumerate(lines):
            if "-->" in line:
                start = parse_ts(line.split("-->")[0].strip())
                body = lines[i + 1:]
                break
        else:
            continue
        for raw in body:
            clean = re.sub(r"<[^>]+>", "", raw)
            clean = clean.replace("&nbsp;", " ").replace("&amp;", "&").replace("&gt;", ">").replace("&lt;", "<")
            clean = re.sub(r"\s+", " ", clean).strip()
            if not clean or clean == last:
                continue
            segments.append((start, clean))
            last = clean
    return segments


def group(segments, timestamps=True):
    out, buf, para_start = [], [], None
    for start, text in segments:
        if para_start is None:
            para_start = start
        if start - para_start >= PARAGRAPH_SECONDS and buf:
            out.append((para_start, " ".join(buf)))
            buf, para_start = [], start
        buf.append(text)
    if buf:
        out.append((para_start, " ".join(buf)))
    if timestamps:
        return "\n\n".join(f"[{fmt_ts(s)}] {t}" for s, t in out)
    return "\n\n".join(t for _, t in out)


def pick_track(info, lang):
    """Return (kind, track_lang) or None. kind is 'subs' or 'auto'."""
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    manual = {k: v for k, v in manual.items() if k != "live_chat"}

    def match(pool, prefer):
        for cand in prefer:
            if cand in pool:
                return cand
        for k in pool:
            if k.split("-")[0] == lang:
                return k
        return None

    m = match(manual, [lang, f"{lang}-orig"])
    if m:
        return "subs", m
    a = match(auto, [f"{lang}-orig", lang])
    if a:
        return "auto", a
    # Fall back to the video's original language.
    orig = next((k for k in auto if k.endswith("-orig")), None)
    if orig:
        return "auto", orig
    if manual:
        return "subs", next(iter(manual))
    return None


def fetch_captions(url, info, workdir, lang):
    track = pick_track(info, lang)
    if not track:
        return None, None
    kind, tlang = track
    flag = "--write-subs" if kind == "subs" else "--write-auto-subs"
    log(f"Downloading {'manual' if kind == 'subs' else 'auto-generated'} captions ({tlang})...")
    run(["yt-dlp", "--quiet", "--no-warnings", "--skip-download", flag,
         "--sub-langs", tlang, "--sub-format", "vtt/best", "--convert-subs", "vtt",
         "-o", str(workdir / "subs.%(ext)s"), url])
    vtts = sorted(workdir.glob("subs*.vtt"))
    if not vtts:
        return None, None
    segs = vtt_to_segments(vtts[0].read_text(encoding="utf-8", errors="replace"))
    return segs, f"{'manual' if kind == 'subs' else 'auto'} captions ({tlang})"


def whisper(url, workdir, model, lang):
    log("Downloading audio for local transcription...")
    run(["yt-dlp", "--quiet", "--no-warnings", "-f", "bestaudio/best", "-x",
         "--audio-format", "mp3", "--audio-quality", "5",
         "-o", str(workdir / "audio.%(ext)s"), url])
    audio = next(workdir.glob("audio.*"))
    log(f"Transcribing with faster-whisper ({model}) — this can take a while on CPU...")
    cmd = ["uv", "run", "--quiet", "--no-project", "--python", "3.12", "--with", "faster-whisper",
           "python", "-I", str(HERE / "whisper_transcribe.py"), str(audio), model]
    if lang:
        cmd.append(lang)
    res = run(cmd, stdout=subprocess.PIPE)
    segs = [(float(s), t) for s, t in json.loads(res.stdout)]
    return segs, f"faster-whisper {model}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("--lang", help="preferred language (default: en for captions, auto-detect for Whisper)")
    ap.add_argument("--whisper", action="store_true", help="skip YouTube captions; transcribe audio locally")
    ap.add_argument("--model", default="small", help="faster-whisper model (tiny/base/small/medium/large-v3)")
    ap.add_argument("--no-timestamps", action="store_true")
    ap.add_argument("--video", action="store_true", help="also download the video file")
    args = ap.parse_args()

    for tool in ("yt-dlp", "ffmpeg"):
        if not shutil.which(tool):
            sys.exit(f"error: {tool} not found in PATH")

    log("Fetching video metadata...")
    info = json.loads(run(["yt-dlp", "-J", "--no-warnings", "--no-playlist", args.url],
                          stdout=subprocess.PIPE).stdout)
    vid = info["id"]
    workdir = CACHE / vid
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)

    segs, source = (None, None)
    if not args.whisper:
        segs, source = fetch_captions(args.url, info, workdir, args.lang or "en")
    if not segs:
        if not args.whisper:
            log("No usable captions found; falling back to Whisper.")
        segs, source = whisper(args.url, workdir, args.model, args.lang)

    if args.video:
        log("Downloading video...")
        run(["yt-dlp", "--quiet", "--no-warnings", "-o", str(workdir / "%(title)s [%(id)s].%(ext)s"), args.url])

    body = group(segs, timestamps=not args.no_timestamps)
    header = [
        f"Title: {info.get('title')}",
        f"Channel: {info.get('channel') or info.get('uploader')}",
        f"Uploaded: {info.get('upload_date')}",
        f"Duration: {fmt_ts(info.get('duration') or 0)}",
        f"URL: {info.get('webpage_url') or args.url}",
        f"Transcript source: {source}",
        f"Words: {len(body.split())}",
    ]
    if info.get("chapters"):
        header.append("Chapters:")
        header += [f"  [{fmt_ts(c['start_time'])}] {c['title']}" for c in info["chapters"]]
    out = workdir / "transcript.txt"
    out.write_text("\n".join(header) + "\n\n---\n\n" + body + "\n", encoding="utf-8")
    print("\n".join(header))
    print(f"TRANSCRIPT_FILE={out}")


if __name__ == "__main__":
    main()
