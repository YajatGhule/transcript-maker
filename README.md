# Transcript Maker

Clean, timestamped transcripts of YouTube videos, from the command line or straight into a [Claude Code](https://claude.com/claude-code) chat.

YouTube's auto-generated captions are fast to fetch but sometimes **cooked**: misheard, missing chunks, out of sync, or machine-translated. Transcript Maker spot-checks them against [Whisper](https://github.com/SYSTRAN/faster-whisper) before trusting them:

1. Fetch the English captions (manual first, then auto-generated) with `yt-dlp`.
2. For auto-generated captions, pick random 5-second clips spread across the video, transcribe each with Whisper, and measure how many of Whisper's words appear (in order) in the captions at that timestamp.
3. If the average match is below the threshold (default 70%), throw the captions away and transcribe the whole video with Whisper.
4. No English captions at all? Go straight to Whisper.

Clips with no speech (music, silence) are skipped. If too few clips have speech to judge, the captions are kept.

English only for now.

## Install

Requires [`yt-dlp`](https://github.com/yt-dlp/yt-dlp), `ffmpeg` and [`uv`](https://github.com/astral-sh/uv).

```bash
uv tool install git+https://github.com/YajatGhule/transcript-maker
```

The core is pure Python with no dependencies. Whisper (faster-whisper, CPU) is run on demand in an isolated Python 3.12 env via `uv`, so nothing heavy gets installed until the first time it's needed. To install it up front instead: `uv tool install 'transcript-maker[whisper] @ git+https://github.com/YajatGhule/transcript-maker'`.

## Usage

```bash
transcript-maker https://youtu.be/VIDEO_ID              # transcript to stdout
transcript-maker VIDEO_ID -o talk.txt                   # also save to a file
transcript-maker VIDEO_ID --check-only -v               # just judge the captions, show each clip
transcript-maker VIDEO_ID --whisper --model medium.en   # skip captions, best quality
```

Example spot-check (`-v`):

```
  [01:31] 100%  whisper : vlogs I make. Let's call them planned and unplanned. So a planned vlog is when I have this
               captions: is two main styles of vlogs i make lets call them planned and unplanned so a planned vlog is when i have this vision or idea that
  ...
captions trusted - 89% word match over 7 clips (threshold 70%)
```

| Option | Description |
| --- | --- |
| `-o FILE` | Also write the transcript to `FILE` |
| `--print-path` | Print only the header and `TRANSCRIPT_FILE=<path>` (used by the Claude skill) |
| `--no-timestamps` | Plain paragraphs without `[mm:ss]` markers |
| `--video` | Also download the video file |
| `-v` | Show each spot-check comparison |
| `--whisper` | Skip captions; transcribe everything with Whisper |
| `--model NAME` | `tiny.en`, `base.en`, `small.en` (default), `medium.en`, `large-v3` |
| `--no-check` | Trust auto-captions without checking (fastest) |
| `--always-check` | Spot-check manual captions too |
| `--check-only` | Print the verdict and exit (status 0 = trusted, 1 = cooked) |
| `--samples N` | Number of random clips (default 8) |
| `--clip-length S` | Seconds per clip (default 5) |
| `--threshold F` | Minimum average word match to trust captions (default 0.7) |
| `--seed N` | Fix the random clip choice |

Output goes to `~/.cache/yt-transcript/<video_id>/` (override with `YT_TRANSCRIPT_CACHE`): `transcript.txt`, plus `check.json` with the per-clip results when a spot-check ran.

## Claude Code skill

`skill/youtube-transcript` is a Claude Code skill that runs the CLI and reads the transcript into the chat. Install the CLI, then:

```bash
git clone https://github.com/YajatGhule/transcript-maker.git
ln -s "$PWD/transcript-maker/skill/youtube-transcript" ~/.claude/skills/youtube-transcript
```

Then paste a YouTube link into Claude Code and ask about it, or run `/youtube-transcript <url>`.

## Development

```bash
uv run --with pytest --with-editable . pytest
```

## License

MIT
