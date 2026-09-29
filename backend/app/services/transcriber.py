"""Speech-to-text on this computer with Whisper (faster-whisper): free, private, offline.

The model (WHISPER_MODEL, default "large-v3-turbo") is downloaded once into data_dir/whisper.
Each audio track is transcribed on its own, then the lines are put in time order with the
speaker's name: "[10:02] Saif: I will send the price list by Thursday."
On the other people's track the voices are separated (services/speakers.py): "Speaker 1",
"Speaker 2" ... - or "Others" when that is off or fails.
"""

import logging
import threading
import wave
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

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


def transcribe_file(path: Path, words: list[str] | None = None) -> list[Segment]:
    """Text with start times (your microphone track)."""
    if not _has_audio(path):
        return []
    return [(seg.start, seg.text.strip()) for seg in _whisper(load_audio(path), words)]


def transcribe_others(path: Path, words: list[str] | None = None) -> list[Line]:
    """The other people's track, one label per voice: "Speaker 1", "Speaker 2" ...
    With speaker separation off, or when it fails, every line is "Others"."""
    if not _has_audio(path):
        return []
    audio = load_audio(path)
    separate = get_settings().speaker_separation
    segments = _whisper(audio, words, word_timestamps=separate)
    as_others = [(seg.start, "Others", seg.text.strip()) for seg in segments]
    if not separate or not segments:
        return as_others
    try:
        turns = speakers.diarize(audio)
    except Exception:
        log.exception("Speaker separation failed - the other people stay 'Others'")
        return as_others
    if not turns:
        return as_others
    word_lists = [
        [(w.start, w.end, w.word) for w in seg.words] if seg.words
        else [(seg.start, seg.end, seg.text)]  # no word times: the sentence as one piece
        for seg in segments
    ]  # fmt: skip
    return speakers.label_segments(word_lists, turns)


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
) -> str:
    return merge(
        transcribe_file(me_file, words), transcribe_others(others_file, words), started_at, me_name
    )
