"""Speech-to-text on this computer with Whisper (faster-whisper): free, private, offline.

The model (WHISPER_MODEL, default "large-v3-turbo") is downloaded once into data_dir/whisper.
Each audio track is transcribed on its own, then the lines are put in time order with the
speaker's name: "[10:02] Saif: I will send the price list by Thursday."
On the other people's track the voices are separated (services/speakers.py): "Speaker 1",
"Speaker 2" ... - or "Others" when that is off or fails. Echo of the others' voices on your
microphone is removed, so their words (and tasks) never get your name.
"""

import bisect
import logging
import re
import threading
import wave
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from app.agents.linker import normalize
from app.config import get_settings
from app.services import speakers

log = logging.getLogger(__name__)

_model = None
_model_lock = threading.Lock()


def _get_model():
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel  # heavy import, only when needed

            settings = get_settings()
            _model = WhisperModel(
                settings.whisper_model,
                device="cpu",
                compute_type="int8",  # small and fast on a normal CPU
                download_root=str(settings.data_dir / "whisper"),
            )
    return _model


Segment = tuple[float, str]  # (seconds from the start, text)
Line = tuple[float, str, str]  # (seconds from the start, who, text)

# A hint for Whisper about the language and style of the meetings.
PROMPT = "اجتماع عمل باللهجة الأردنية مع كلمات إنجليزية. A work meeting in Arabic and English."


TARGET_PEAK = 0.9  # quiet recordings are made louder up to this level (1.0 = maximum)
MAX_GAIN = 30.0  # ... but never more than 30x, so pure room noise is not blown up


def load_audio(path: Path) -> np.ndarray:
    """16 kHz mono WAV -> float samples, made louder when the recording is quiet."""
    with wave.open(str(path), "rb") as w:
        samples = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    audio = samples.astype(np.float32) / 32768.0
    peak = float(np.percentile(np.abs(audio), 99.9)) if audio.size else 0.0
    if peak > 0:
        audio = np.clip(audio * min(TARGET_PEAK / peak, MAX_GAIN), -1.0, 1.0)
    return audio


def _has_audio(path: Path | None) -> bool:
    return bool(path) and path.exists() and path.stat().st_size >= 1000


def _whisper(audio: np.ndarray, words: list[str] | None, word_timestamps: bool = False) -> list:
    """Whisper's pieces of text. Silence is skipped (VAD), so a silent track gives [].

    `words` = names and terms from Settings -> Meeting words, given to Whisper as hints.
    """
    language = get_settings().whisper_language or None
    segments, _info = _get_model().transcribe(
        audio,
        language=language,  # the main language; guessing it per piece can give wrong languages
        multilingual=language is None,
        # Skip silence (also stops Whisper from inventing text in silence). Short pauses stay
        # inside one piece, so Whisper hears whole sentences - one or two words alone are
        # guessed badly, especially in spoken Arabic.
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 1200, "speech_pad_ms": 400},
        beam_size=5,  # checks 5 options for each piece: slower, but more accurate
        initial_prompt=PROMPT,
        hotwords=", ".join(words) if words else None,  # names and terms to listen for
        condition_on_previous_text=False,  # fewer repeated or invented sentences
        word_timestamps=word_timestamps,  # when each word was said (to split by voice)
    )
    return [seg for seg in segments if seg.text.strip()]


def transcribe_mine(path: Path, words: list[str] | None = None) -> list[speakers.Word]:
    """Your microphone track: (start, end, text) pieces."""
    if not _has_audio(path):
        return []
    return [(seg.start, seg.end, seg.text.strip()) for seg in _whisper(load_audio(path), words)]


@dataclass
class OthersTrack:
    lines: list[Line] = field(default_factory=list)  # (start, "Speaker 1", text)
    heard: list[speakers.Word] = field(default_factory=list)  # every word with its time
    voices: dict[str, list[float]] = field(default_factory=dict)  # "Speaker 1" -> voice print
    # When each voice talked, in seconds from the start (to match Google Meet's captions)
    times: dict[str, list[tuple[float, float]]] = field(default_factory=dict)


def transcribe_others(
    path: Path, words: list[str] | None = None, max_voices: int | None = None
) -> OthersTrack:
    """The other people's track, one label per voice: "Speaker 1", "Speaker 2" ...
    With speaker separation off, or when it fails, every line is "Others".
    `max_voices` = how many other people joined the call, when known."""
    if not _has_audio(path):
        return OthersTrack()
    audio = load_audio(path)
    separate = get_settings().speaker_separation
    segments = _whisper(audio, words, word_timestamps=separate)
    pieces = [
        [(w.start, w.end, w.word) for w in seg.words] if seg.words
        else [(seg.start, seg.end, seg.text)]  # no word times: the sentence as one piece
        for seg in segments
    ]  # fmt: skip
    track = OthersTrack(
        lines=[(seg.start, "Others", seg.text.strip()) for seg in segments],
        heard=[word for piece in pieces for word in piece],
    )
    if not separate or not segments:
        return track
    try:
        turns = speakers.diarize(audio)
    except Exception:
        log.exception("Speaker separation failed - the other people stay 'Others'")
        return track
    if not turns:
        return track
    try:
        turns = speakers.merge_voices(
            audio, turns, max_voices, get_settings().voice_merge_threshold
        )
    except Exception:
        log.exception("Merging the voices failed - keeping the separation as it is")
    track.lines = speakers.label_segments(pieces, turns)
    for start, end, n in turns:
        track.times.setdefault(speakers.label(n), []).append((start, end))
    try:
        prints = speakers.voice_prints(audio, turns)
        track.voices = {speakers.label(n): v.round(5).tolist() for n, v in prints.items()}
    except Exception:
        log.exception("Voice prints failed - the voices are not recognized this time")
    return track


# ---- echo: the others' voices on your microphone -----------------------------------------

ECHO_WINDOW = 1.0  # seconds around your line
ECHO_SHARE = 0.7  # this share of your line's words heard from the others at that time = echo
ECHO_MIN_WORDS = 3  # shorter lines ("OK", "تمام") are kept


def _word_set(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", normalize(text)) if len(w) > 1}


def remove_echo(mine: list[speakers.Word], heard: list[speakers.Word]) -> tuple[list[Segment], int]:
    """Without headphones the other people's voices also reach your microphone. Their words
    would get YOUR name, and their tasks would look like yours. A line on your microphone
    whose words were heard from the others at the same time is that echo: it is dropped.
    (Your answer a few seconds later, even with the same words, is kept.)"""
    heard = sorted(heard)
    starts = [start for start, _, _ in heard]
    heard_words = [_word_set(text) for _, _, text in heard]
    kept, dropped = [], 0
    for start, end, text in mine:
        words = _word_set(text)
        if len(words) >= ECHO_MIN_WORDS:
            nearby: set[str] = set()
            first = bisect.bisect_left(starts, start - ECHO_WINDOW - 30)  # a piece is < 30 s
            last = bisect.bisect_right(starts, end + ECHO_WINDOW)
            for i in range(first, last):
                if heard[i][1] > start - ECHO_WINDOW:
                    nearby |= heard_words[i]
            if len(words & nearby) >= ECHO_SHARE * len(words):
                dropped += 1
                continue
        kept.append((start, text))
    return kept, dropped


# ---- both tracks ---------------------------------------------------------------------------


@dataclass
class Transcript:
    text: str
    voices: dict[str, list[float]] = field(default_factory=dict)  # "Speaker 1" -> voice print
    echo_removed: int = 0  # lines on your microphone that were really the others' voices
    times: dict[str, list[tuple[float, float]]] = field(default_factory=dict)  # voice -> talk


def merge(me: list[Segment], others: list[Line], started_at: datetime, me_name: str) -> str:
    """Both tracks as one transcript in time order, one line per sentence."""
    lines = [(t, me_name, text) for t, text in me] + list(others)
    lines.sort(key=lambda line: line[0])
    return "\n".join(
        f"[{started_at + timedelta(seconds=t):%H:%M}] {who}: {text}" for t, who, text in lines
    )


def transcribe_meeting(
    me_file: Path,
    others_file: Path,
    started_at: datetime,
    me_name: str,
    words: list[str] | None = None,
    max_voices: int | None = None,
) -> Transcript:
    others = transcribe_others(others_file, words, max_voices)
    mine, echo = remove_echo(transcribe_mine(me_file, words), others.heard)
    if echo:
        log.info("Dropped %s echo line(s) from the microphone", echo)
    text = merge(mine, others.lines, started_at, me_name)
    return Transcript(text, others.voices, echo, others.times)
