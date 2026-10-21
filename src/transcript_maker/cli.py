"""Get a clean, timestamped transcript of a YouTube video (English only for now).

Strategy:
  1. Use YouTube's English captions via yt-dlp (manual first, then auto-generated).
  2. Auto-generated captions are spot-checked: random 5-second clips are run
     through Whisper and compared with the captions. If they don't match well
     enough ("cooked" captions), the whole video is transcribed with Whisper.
  3. No English captions at all (or --whisper): transcribe with Whisper.

The transcript is printed to stdout and saved to
~/.cache/yt-transcript/<video_id>/transcript.txt. Progress goes to stderr.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__, check, whisper

CACHE = Path(os.environ.get("YT_TRANSCRIPT_CACHE", Path.home() / ".cache" / "yt-transcript"))
PARAGRAPH_SECONDS = 30
LANG = "en"

verbose = False


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, text=True, **kw)


def fmt_ts(sec):
    sec = int(sec)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def parse_ts(ts):
    parts = [float(p) for p in ts.replace(",", ".").split(":")]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def vtt_to_segments(text):
    """Parse VTT into (start_seconds, line) pairs, removing the rolling
    duplicate lines that YouTube auto-captions produce."""
    segments = []
    last = None
    # Split on truly empty lines only: auto-captions start some cues with a
    # whitespace-only line, which must not be treated as a cue boundary.
    for block in re.split(r"\n{2,}", text.replace("\r\n", "\n")):
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


def pick_track(info):
    """Return ('subs' | 'auto', track_lang) for the best English track, or None."""
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    for k in [LANG, f"{LANG}-orig"] + sorted(manual):
        if k in manual and k.split("-")[0] == LANG:
            return "subs", k
    # `en-orig` is YouTube's own speech recognition; plain `en` on a non-English
    # video is a machine translation of it, so only use it as a last resort.
    for k in [f"{LANG}-orig", LANG]:
        if k in auto:
            return "auto", k
    return None


def fetch_captions(url, info, workdir):
    track = pick_track(info)
    if not track:
        return None, None
    kind, tlang = track
    flag = "--write-subs" if kind == "subs" else "--write-auto-subs"
    log(f"Downloading {'manual' if kind == 'subs' else 'auto-generated'} captions ({tlang})...")
    try:
        run(["yt-dlp", "--quiet", "--no-warnings", "--skip-download", flag,
             "--sub-langs", tlang, "--sub-format", "vtt/best", "--convert-subs", "vtt",
             "--retries", "3", "-o", str(workdir / "subs.%(ext)s"), url])
    except subprocess.CalledProcessError:
        # Usually YouTube rate-limiting subtitle requests (HTTP 429).
        log("Caption download failed.")
        return None, None
    vtts = sorted(workdir.glob("subs*.vtt"))
    if not vtts:
        return None, None
    segs = vtt_to_segments(vtts[0].read_text(encoding="utf-8", errors="replace"))
    return segs, kind


def get_audio(url, workdir):
    found = list(workdir.glob("audio.*"))
    if found:
        return found[0]
    log("Downloading audio...")
    run(["yt-dlp", "--quiet", "--no-warnings", "--no-playlist", "-f", "bestaudio/best",
         "-o", str(workdir / "audio.%(ext)s"), url])
    return next(workdir.glob("audio.*"))


def run_check(args, segs, url, info, workdir):
    audio = get_audio(url, workdir)
    log(f"Spot-checking captions: Whisper ({args.model}) on {args.samples} random "
        f"{args.clip_length:g}s clips...")
    report = check.check(segs, audio, info.get("duration") or 0, args.model,
                         samples=args.samples, length=args.clip_length,
                         threshold=args.threshold, seed=args.seed)
    if verbose or args.check_only:
        for s in report.samples:
            score = "skip" if s.score is None else f"{s.score:.0%}"
            log(f"  [{fmt_ts(s.start)}] {score:>4}  whisper : {s.heard or '-'}")
            log(f"               captions: {s.captions or '-'}")
    (workdir / "check.json").write_text(json.dumps(
        {"score": report.score, "threshold": report.threshold, "trusted": report.trusted,
         "samples": [s.__dict__ for s in report.samples]}, indent=2))
    if not args.check_only:
        log(f"Caption check: {report.summary()}")
    return report


def build_parser():
    ap = argparse.ArgumentParser(prog="transcript-maker", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", help="YouTube video URL or ID")
    ap.add_argument("-o", "--output", type=Path, help="also write the transcript to this file")
    ap.add_argument("--print-path", action="store_true",
                    help="print only the header and TRANSCRIPT_FILE=<path> instead of the transcript")
    ap.add_argument("--no-timestamps", action="store_true", help="plain paragraphs without [mm:ss]")
    ap.add_argument("--video", action="store_true", help="also download the video file")
    ap.add_argument("-v", "--verbose", action="store_true", help="show each spot-check comparison")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    w = ap.add_argument_group("whisper")
    w.add_argument("--whisper", action="store_true", help="skip captions; transcribe everything with Whisper")
    w.add_argument("--model", default="small.en",
                   help="faster-whisper model: tiny.en, base.en, small.en (default), medium.en, large-v3")

    c = ap.add_argument_group("caption spot-check")
    c.add_argument("--no-check", action="store_true", help="trust auto-captions without checking")
    c.add_argument("--always-check", action="store_true", help="check manual captions too")
    c.add_argument("--check-only", action="store_true", help="run the spot-check, print the verdict, exit")
    c.add_argument("--samples", type=int, default=8, help="number of random clips (default 8)")
    c.add_argument("--clip-length", type=float, default=5.0, help="seconds per clip (default 5)")
    c.add_argument("--threshold", type=float, default=0.7,
                   help="minimum average word match to trust captions (default 0.7)")
    c.add_argument("--seed", type=int, help="random seed, for reproducible clip choice")
    return ap


def main(argv=None):
    global verbose
    args = build_parser().parse_args(argv)
    verbose = args.verbose
    for tool in ("yt-dlp", "ffmpeg"):
        if not shutil.which(tool):
            sys.exit(f"error: {tool} not found in PATH")

    try:
        return _main(args)
    except subprocess.CalledProcessError as e:
        sys.exit(f"error: {Path(e.cmd[0]).name} failed (exit {e.returncode})")
    except KeyboardInterrupt:
        sys.exit(130)


def _main(args):
    url = args.url
    log("Fetching video metadata...")
    info = json.loads(run(["yt-dlp", "-J", "--no-warnings", "--no-playlist", url],
                          stdout=subprocess.PIPE).stdout)
    url = info.get("webpage_url") or url
    workdir = CACHE / info["id"]
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)

    segs, kind, source, report = None, None, None, None
    if not args.whisper:
        segs, kind = fetch_captions(url, info, workdir)
        if segs:
            source = f"{'manual' if kind == 'subs' else 'auto-generated'} captions"
        else:
            log("No English captions found.")

    if segs and (args.check_only or args.always_check or (kind == "auto" and not args.no_check)):
        report = run_check(args, segs, url, info, workdir)
        if args.check_only:
            print(report.summary())
            return 0 if report.trusted else 1
        if not report.trusted:
            log("Captions failed the spot-check; transcribing with Whisper instead.")
            segs = None
    elif args.check_only:
        sys.exit("error: no English captions to check")

    if not segs:
        audio = get_audio(url, workdir)
        log(f"Transcribing with Whisper ({args.model}) - this can take a while on CPU...")
        segs = whisper.transcribe(audio, args.model)
        source = f"Whisper ({args.model})"

    if args.video:
        log("Downloading video...")
        run(["yt-dlp", "--quiet", "--no-warnings", "--no-playlist",
             "-o", str(workdir / "%(title)s [%(id)s].%(ext)s"), url])

    body = group(segs, timestamps=not args.no_timestamps) or "(no speech detected)"
    header = [
        f"Title: {info.get('title')}",
        f"Channel: {info.get('channel') or info.get('uploader')}",
        f"Uploaded: {info.get('upload_date')}",
        f"Duration: {fmt_ts(info.get('duration') or 0)}",
        f"URL: {url}",
        f"Transcript source: {source}",
    ]
    if report:
        header.append(f"Caption check: {report.summary()}")
    header.append(f"Words: {len(body.split())}")
    if info.get("chapters"):
        header.append("Chapters:")
        header += [f"  [{fmt_ts(c['start_time'])}] {c['title']}" for c in info["chapters"]]
    text = "\n".join(header) + "\n\n---\n\n" + body + "\n"

    out = workdir / "transcript.txt"
    out.write_text(text, encoding="utf-8")
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    if args.print_path:
        print("\n".join(header))
        print(f"TRANSCRIPT_FILE={out}")
    else:
        sys.stdout.write(text)
        log(f"Saved to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
