"""Who is speaking on the "Others" track of the meeting recorder (speaker diarization).

The speakers track has all the other people mixed together. This splits it by voice:
1. a segmentation model finds where each voice starts and stops,
2. a voice-print model (speaker embedding) makes a print of every piece,
3. pieces with close prints are the same person -> "Speaker 1", "Speaker 2" ... in the order
   they first speak.
A voice has no name: the Meeting agent finds the names from what is said and from the people
who joined the call, and the voice memory (services/voice_memory.py) knows voices from
earlier meetings by their voice print.

sherpa-onnx runs on this computer: free and offline. The two models (about 46 MB) are
downloaded once from the sherpa-onnx GitHub releases into data_dir/speakers, and checked
with SHA-256 so a broken or changed file is never used.
"""

import hashlib
import logging
import os
import tarfile
import threading
import urllib.request
from pathlib import Path

import numpy as np

from app.config import get_settings

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
_RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
# pyannote segmentation 3.0 (MIT licence): where each voice starts and stops
SEGMENTATION_URL = (
    f"{_RELEASES}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
)
SEGMENTATION_SHA256 = "24615ee884c897d9d2ba09bb4d30da6bb1b15e685065962db5b02e76e4996488"
SEGMENTATION_MODEL_SHA256 = "220ad67ca923bef2fa91f2390c786097bf305bceb5e261d4af67b38e938e1079"
# NVIDIA NeMo TitaNet small: the voice prints. Of five models tried on a two-voice test it
# told the voices apart best for its speed (same voice 0.88, different voices 0.23).
EMBEDDING_URL = f"{_RELEASES}/speaker-recongition-models/nemo_en_titanet_small.onnx"
EMBEDDING_SHA256 = "ad4a1802485d8b34c722d2a9d04249662f2ece5d28a7a039063ca22f515a789e"

Turn = tuple[float, float, int]  # (start, end, speaker number 0, 1, ...) in seconds
Word = tuple[float, float, str]  # (start, end, text) from Whisper
Line = tuple[float, str, str]  # (start, "Speaker 1", text)

_diarizer = None
_extractor = None
_lock = threading.Lock()


# ---- models ------------------------------------------------------------------------------


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_good(path: Path, sha256: str) -> bool:
    return path.exists() and _sha256(path.read_bytes()) == sha256


def _download(url: str, sha256: str) -> bytes:
    log.info("Downloading %s", url)
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 (fixed https URL)
        data = response.read()
    if _sha256(data) != sha256:
        raise RuntimeError(f"The downloaded file is not the expected one: {url}")
    return data


def _write(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(path)  # only a complete file gets the real name


def _models() -> tuple[Path, Path]:
    """The two model files, downloaded when missing (or broken)."""
    folder = get_settings().data_dir / "speakers"
    folder.mkdir(parents=True, exist_ok=True)
    segmentation = folder / "segmentation.onnx"
    embedding = folder / "titanet_small.onnx"
    if not _is_good(segmentation, SEGMENTATION_MODEL_SHA256):
        archive = folder / "segmentation.tar.bz2"
        _write(archive, _download(SEGMENTATION_URL, SEGMENTATION_SHA256))
        with tarfile.open(archive) as tar:  # take only the model, not the example scripts
            member = tar.getmember("sherpa-onnx-pyannote-segmentation-3-0/model.onnx")
            data = tar.extractfile(member).read()
        if _sha256(data) != SEGMENTATION_MODEL_SHA256:
            raise RuntimeError("The speaker segmentation model is not the expected one.")
        _write(segmentation, data)
        archive.unlink()
    if not _is_good(embedding, EMBEDDING_SHA256):
        _write(embedding, _download(EMBEDDING_URL, EMBEDDING_SHA256))
    return segmentation, embedding


def _threads() -> int:
    return max(1, (os.cpu_count() or 2) // 2)


def _get_extractor():
    """The voice-print model alone (for the voice memory)."""
    global _extractor
    with _lock:
        if _extractor is None:
            import sherpa_onnx

            _, embedding = _models()
            _extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
                sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                    model=str(embedding), num_threads=_threads()
                )
            )
    return _extractor


def _get_diarizer():
    global _diarizer
    with _lock:
        if _diarizer is None:
            import sherpa_onnx  # only when needed

            segmentation, embedding = _models()
            threads = _threads()
            config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
                segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                    pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                        model=str(segmentation)
                    ),
                    num_threads=threads,
                ),
                embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                    model=str(embedding), num_threads=threads
                ),
                # Voices closer than this are one person. Smaller = more speakers.
                clustering=sherpa_onnx.FastClusteringConfig(
                    threshold=get_settings().speaker_threshold
                ),
                min_duration_on=0.3,  # ignore voice pieces shorter than this (seconds)
                min_duration_off=0.5,  # join pieces of one voice with a shorter gap
            )
            if not config.validate():
                raise RuntimeError("The speaker separation models could not be loaded.")
            _diarizer = sherpa_onnx.OfflineSpeakerDiarization(config)
    return _diarizer


# ---- who speaks when ---------------------------------------------------------------------


def diarize(audio: np.ndarray) -> list[Turn]:
    """Voice turns of a 16 kHz track. Speakers are numbered in the order they first speak."""
    if audio.size < SAMPLE_RATE:  # less than a second
        return []
    result = _get_diarizer().process(audio).sort_by_start_time()
    order: dict[int, int] = {}
    return [(s.start, s.end, order.setdefault(s.speaker, len(order))) for s in result]


PRINT_MAX_SECONDS = 30  # up to this much of one person's speech makes their voice print
PRINT_MIN_SECONDS = 2  # less speech than this gives no reliable voice print (for the memory)
MERGE_MIN_SECONDS = 1  # enough speech to compare two labels when merging them


def voice_prints(
    audio: np.ndarray, turns: list[Turn], min_seconds: float = PRINT_MIN_SECONDS
) -> dict[int, np.ndarray]:
    """One voice print per speaker (a vector of length 1), from their longest turns."""
    spans: dict[int, list[tuple[float, float]]] = {}
    for start, end, speaker in turns:
        spans.setdefault(speaker, []).append((start, end))
    extractor = _get_extractor()
    prints = {}
    for speaker, parts in spans.items():
        parts.sort(key=lambda p: p[1] - p[0], reverse=True)  # long turns are the cleanest
        pieces, samples = [], 0
        for start, end in parts:
            if samples >= PRINT_MAX_SECONDS * SAMPLE_RATE:
                break
            piece = audio[int(start * SAMPLE_RATE) : int(end * SAMPLE_RATE)]
            pieces.append(piece)
            samples += piece.size
        if samples < min_seconds * SAMPLE_RATE:
            continue
        stream = extractor.create_stream()
        stream.accept_waveform(SAMPLE_RATE, np.concatenate(pieces))
        stream.input_finished()
        vector = np.array(extractor.compute(stream), dtype=np.float32)
        size = float(np.linalg.norm(vector))
        if vector.size and size > 0:
            prints[speaker] = vector / size
    return prints


def _nearest_voice(turns: list[Turn], speaker: int, candidates: set[int]) -> int | None:
    """The candidate who talks closest in time to this speaker's turns."""
    best, gap = None, float("inf")
    for start, end, n in turns:
        if n != speaker:
            continue
        for s, e, other in turns:
            if other in candidates:
                distance = max(s - end, start - e, 0.0)
                if distance < gap:
                    best, gap = other, distance
    return best


def merge_voices(
    audio: np.ndarray, turns: list[Turn], max_voices: int | None = None, similar: float = 0.6
) -> list[Turn]:
    """One person often gets several labels (short turns, call audio: 3 trainees got 8 labels).
    1. A label with very little speech ("سامعيني") joins the voice that talks next to it.
    2. Labels whose voice prints are close are one person. A whole label's print is much more
       reliable than the short pieces the separation compared.
    3. With the number of people in the call known, there are never more voices than people.
    Speakers are numbered again in the order they first speak."""
    if not turns:
        return turns
    seconds: dict[int, float] = {}
    for start, end, n in turns:
        seconds[n] = seconds.get(n, 0.0) + end - start
    prints = voice_prints(audio, turns, MERGE_MIN_SECONDS)
    into = {n: n for n in seconds}  # speaker -> the voice it now belongs to
    for n in seconds:
        if n not in prints and prints:
            into[n] = _nearest_voice(turns, n, set(prints))

    groups = {n: prints[n] * seconds[n] for n in prints}  # sum of prints, weighted by speech

    def unit(v: np.ndarray) -> np.ndarray:
        return v / np.linalg.norm(v)

    while len(groups) > 1:
        keys = list(groups)
        score, a, b = max(
            (float(unit(groups[x]) @ unit(groups[y])), x, y)
            for i, x in enumerate(keys)
            for y in keys[i + 1 :]
        )
        too_many = max_voices is not None and max_voices >= 1 and len(groups) > max_voices
        if score < similar and not too_many:
            break
        groups[a] = groups[a] + groups.pop(b)
        for n, target in into.items():
            if target == b:
                into[n] = a

    order: dict[int, int] = {}
    return [(s, e, order.setdefault(into[n], len(order))) for s, e, n in sorted(turns)]


def best_match(
    voice: np.ndarray, known: dict[str, np.ndarray], threshold: float, margin: float = 0.1
) -> tuple[str | None, float]:
    """The remembered person with this voice: (name, similarity), or (None, best similarity).
    A name only when the voice is close enough AND clearly closer than to anybody else."""
    scores = sorted(((float(voice @ v), name) for name, v in known.items()), reverse=True)
    if not scores:
        return None, 0.0
    best, name = scores[0]
    second = scores[1][0] if len(scores) > 1 else -1.0
    if best >= threshold and best - second >= margin:
        return name, best
    return None, best


def speaker_at(start: float, end: float, turns: list[Turn]) -> int | None:
    """The speaker who talks most in this time, or the nearest one within a second."""
    best, most = None, 0.0
    for t_start, t_end, speaker in turns:
        overlap = min(end, t_end) - max(start, t_start)
        if overlap > most:
            best, most = speaker, overlap
    if best is None and turns:  # a word in a short gap between turns
        middle = (start + end) / 2
        gap, speaker = min((min(abs(middle - s), abs(middle - e)), n) for s, e, n in turns)
        if gap <= 1.0:
            best = speaker
    return best


def _smooth(speakers: list[int | None]) -> list[int | None]:
    """One or two words of another voice inside one person's talk are a separation mistake."""
    result = list(speakers)
    i = 0
    while i < len(result):
        j = i
        while j < len(result) and result[j] == result[i]:
            j += 1
        before = result[i - 1] if i > 0 else None
        after = result[j] if j < len(result) else None
        if j - i <= 2 and before is not None and before == after:
            result[i:j] = [before] * (j - i)
        i = j
    return result


def label(speaker: int | None) -> str:
    return "Others" if speaker is None else f"Speaker {speaker + 1}"


def label_segments(segments: list[list[Word]], turns: list[Turn]) -> list[Line]:
    """Whisper's sentences, split where the voice changes: (start, "Speaker 1", text)."""
    lines: list[Line] = []
    for words in segments:
        if not words:
            continue
        found = [speaker_at(s, e, turns) for s, e, _ in words]
        speakers = _smooth(found)
        start, current, parts = words[0][0], speakers[0], []
        for (w_start, _, text), speaker in zip(words, speakers, strict=True):
            if parts and speaker != current and speaker is not None:
                lines.append((start, label(current), "".join(parts).strip()))
                start, parts = w_start, []
            if speaker is not None:
                current = speaker
            parts.append(text)
        lines.append((start, label(current), "".join(parts).strip()))
    return [line for line in lines if line[2]]
