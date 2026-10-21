"""Spot-check auto-generated captions against Whisper.

Pick random 5-second clips spread across the video, transcribe each with
Whisper, and measure how many of Whisper's words show up (in order) in the
captions around the same timestamp. If the captions are "cooked" (garbled,
missing chunks, out of sync), the match rate drops and we fall back to a
full Whisper transcription.
"""
import random
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from . import whisper

FILLERS = {"um", "uh", "uhm", "umm", "hmm", "mm", "mhm", "er", "ah"}
MIN_WORDS = 3     # clips where Whisper hears fewer words are music/silence: skipped
SLACK = 1.5       # seconds of caption context on each side of a clip
MAX_WORD_SPAN = 8 # cap when spreading a caption line's words over time


# Whisper and YouTube disagree on these spellings; normalize both sides.
EXPAND = {"gonna": ["going", "to"], "wanna": ["want", "to"], "gotta": ["got", "to"],
          "kinda": ["kind", "of"], "sorta": ["sort", "of"], "ok": ["okay"]}


def words(text):
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)|♪", " ", text.lower())
    text = text.replace("’", "'").replace("'", "")
    out = []
    for w in re.findall(r"[a-z0-9]+", text):
        if w not in FILLERS:
            out.extend(EXPAND.get(w, [w]))
    return out


def drop_loops(ws, max_n=8):
    """Remove immediately repeated n-grams: Whisper sometimes loops on a phrase
    at a clip's cut-off edge ("show him or show him or show him...")."""
    out = []
    for w in ws:
        out.append(w)
        for n in range(1, max_n + 1):
            if len(out) >= 2 * n and out[-n:] == out[-2 * n:-n] and (n > 1 or len(out) >= 3 and out[-3] == w):
                del out[-n:]
                break
    return out


def timed_words(segments):
    """Spread each caption line's words evenly until the next line starts."""
    out = []
    for i, (start, text) in enumerate(segments):
        end = segments[i + 1][0] if i + 1 < len(segments) else start + 3
        end = min(max(end, start + 0.5), start + MAX_WORD_SPAN)
        ws = words(text)
        for j, w in enumerate(ws):
            out.append((start + (end - start) * j / max(len(ws), 1), w))
    return out


def recall(heard, reference):
    """Fraction of Whisper's words found, in order, in the caption words."""
    if not heard:
        return 0.0
    sm = SequenceMatcher(None, heard, reference, autojunk=False)
    return sum(b.size for b in sm.get_matching_blocks()) / len(heard)


def pick_starts(duration, n, length, rng):
    """One random start per equal slice of the video, so samples spread out."""
    usable = duration - length
    if usable <= 0:
        return [0.0]
    n = max(1, min(n, int(usable // length)))
    span = usable / n
    return [round(i * span + rng.uniform(0, span), 2) for i in range(n)]


@dataclass
class Sample:
    start: float
    heard: str
    captions: str
    score: float | None  # None = skipped (too little speech)


@dataclass
class Report:
    samples: list = field(default_factory=list)
    threshold: float = 0.0

    @property
    def scored(self):
        return [s for s in self.samples if s.score is not None]

    @property
    def score(self):
        sc = self.scored
        return sum(s.score for s in sc) / len(sc) if sc else None

    @property
    def conclusive(self):
        return len(self.scored) >= 2

    @property
    def trusted(self):
        # Too little speech to judge (music videos etc.): keep the captions.
        return not self.conclusive or self.score >= self.threshold

    def summary(self):
        if not self.conclusive:
            return f"inconclusive ({len(self.scored)}/{len(self.samples)} clips had speech) - kept captions"
        verdict = "captions trusted" if self.trusted else "captions cooked"
        return (f"{verdict} - {self.score:.0%} word match over {len(self.scored)} clips "
                f"(threshold {self.threshold:.0%})")


def check(segments, audio, duration, model, samples=8, length=5.0, threshold=0.7, seed=None):
    rng = random.Random(seed)
    starts = pick_starts(duration, samples, length, rng)
    heard = whisper.transcribe_clips(audio, model, starts, length)
    caption_words = timed_words(segments)
    report = Report(threshold=threshold)
    for start, text in zip(starts, heard):
        ref = [w for t, w in caption_words if start - SLACK <= t <= start + length + SLACK]
        hw = drop_loops(words(text))
        score = recall(hw, ref) if len(hw) >= MIN_WORDS else None
        report.samples.append(Sample(start, text, " ".join(ref), score))
    return report
