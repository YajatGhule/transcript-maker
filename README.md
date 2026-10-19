# Transcript Maker

A [Claude Code](https://claude.com/claude-code) skill that grabs the transcript of a YouTube video and loads it straight into your chat, so you can summarize it, quote it, or ask questions about it.

- Uses YouTube's own captions when available (manual first, then auto-generated) — takes seconds.
- No captions? Downloads just the audio and transcribes it locally with [faster-whisper](https://github.com/SYSTRAN/faster-whisper) on CPU.
- Clean, timestamped paragraphs (`[mm:ss]`) plus a header with title, channel, upload date, duration and chapters.

## Requirements

- [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) and `ffmpeg` on your `PATH`
- Python 3
- [`uv`](https://github.com/astral-sh/uv) — only for the Whisper fallback (it fetches faster-whisper into an isolated Python 3.12 env on first use)

## Install

```bash
git clone https://github.com/YajatGhule/transcript-maker.git
ln -s "$PWD/transcript-maker/skill/youtube-transcript" ~/.claude/skills/youtube-transcript
```

(or copy `skill/youtube-transcript` into `~/.claude/skills/`).

## Usage

In Claude Code, just paste a YouTube link and ask about it, or run:

```
/youtube-transcript https://youtu.be/VIDEO_ID
```

The script also works standalone:

```bash
python3 skill/youtube-transcript/scripts/yt_transcript.py URL [options]
```

| Option | Description |
| --- | --- |
| `--lang xx` | Preferred language (default `en` for captions, auto-detect for Whisper) |
| `--whisper` | Skip YouTube captions and transcribe the audio locally |
| `--model NAME` | Whisper model: `tiny`, `base`, `small` (default), `medium`, `large-v3` |
| `--no-timestamps` | Plain paragraphs without `[mm:ss]` markers |
| `--video` | Also download the video file |

Transcripts are saved to `~/.cache/yt-transcript/<video_id>/transcript.txt` (override with `YT_TRANSCRIPT_CACHE`).

## License

MIT
