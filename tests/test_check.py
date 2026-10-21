import random

from transcript_maker import check, cli

SPEECH = ("so today we are going to talk about how to make a great video and why "
          "planning matters more than gear because the story is what people remember "
          "when they close the tab and go back to their day").split()


def captions_from(words, per_line=6, secs_per_word=0.4):
    return [(i * secs_per_word, " ".join(words[i:i + per_line]))
            for i in range(0, len(words), per_line)]


def fake_whisper(monkeypatch, words, secs_per_word=0.4):
    """Make Whisper 'hear' exactly the true speech for each clip."""
    def clips(audio, model, starts, length):
        return [" ".join(w for i, w in enumerate(words)
                         if s <= i * secs_per_word < s + length) for s in starts]
    monkeypatch.setattr(check.whisper, "transcribe_clips", clips)


def test_words_normalizes():
    assert check.words("[Music] I'm GONNA go, um, OK?") == ["im", "going", "to", "go", "okay"]


def test_drop_loops():
    heard = check.words("or show him or show him or show him how")
    assert check.drop_loops(heard) == ["or", "show", "him", "how"]
    assert check.drop_loops(["that", "that", "is"]) == ["that", "that", "is"]


def test_recall():
    assert check.recall(["a", "b", "c"], ["x", "a", "b", "c", "y"]) == 1.0
    assert check.recall(["a", "b", "c", "d"], ["a", "q", "q", "q"]) == 0.25
    assert check.recall([], ["a"]) == 0.0


def test_pick_starts_spread_and_bounded():
    starts = check.pick_starts(600, 8, 5, random.Random(0))
    assert len(starts) == 8 and starts == sorted(starts)
    assert all(0 <= s <= 595 for s in starts)
    assert check.pick_starts(3, 8, 5, random.Random(0)) == [0.0]


def test_good_captions_trusted(monkeypatch):
    fake_whisper(monkeypatch, SPEECH)
    rep = check.check(captions_from(SPEECH), "x", 16, "m", samples=3, seed=1)
    assert rep.conclusive and rep.trusted and rep.score > 0.9


def test_cooked_captions_rejected(monkeypatch):
    fake_whisper(monkeypatch, SPEECH)
    rng = random.Random(0)
    # Simulate bad ASR: most words misheard.
    cooked = [w if rng.random() < 0.3 else "blah" for w in SPEECH]
    rep = check.check(captions_from(cooked), "x", 16, "m", samples=3, seed=1)
    assert rep.conclusive and not rep.trusted


def test_silence_is_inconclusive_and_kept(monkeypatch):
    monkeypatch.setattr(check.whisper, "transcribe_clips", lambda a, m, s, l: ["" for _ in s])
    rep = check.check(captions_from(SPEECH), "x", 16, "m", samples=3, seed=1)
    assert not rep.conclusive and rep.trusted


def test_vtt_rolling_duplicates_removed():
    vtt = """WEBVTT

00:00:00.000 --> 00:00:02.000
hello<00:00:00.500><c> world</c>

00:00:02.000 --> 00:00:02.010
hello world

00:00:02.010 --> 00:00:04.000
hello world
how<00:00:02.500><c> are</c><00:00:03.000><c> you</c>
"""
    assert cli.vtt_to_segments(vtt) == [(0.0, "hello world"), (2.01, "how are you")]


def test_vtt_whitespace_only_first_line():
    vtt = "WEBVTT\n\n00:00:00.660 --> 00:00:44.780 align:start position:0%\n \n[Music]\n\n" \
          "00:00:44.790 --> 00:00:46.000 align:start position:0%\n \nhi<00:00:45.000><c> there</c>\n"
    assert cli.vtt_to_segments(vtt) == [(0.66, "[Music]"), (44.79, "hi there")]


def test_pick_track_prefers_manual_then_orig():
    assert cli.pick_track({"subtitles": {"en-US": [1]}, "automatic_captions": {"en": [1]}}) == ("subs", "en-US")
    assert cli.pick_track({"automatic_captions": {"en": [1], "en-orig": [1]}}) == ("auto", "en-orig")
    assert cli.pick_track({"automatic_captions": {"fr": [1]}}) is None
