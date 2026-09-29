"""Who is speaking on the "Others" track of the meeting recorder (speaker diarization).

The speakers track has all the other people mixed together. This splits it by voice:
1. a segmentation model finds where each voice starts and stops,
2. a voice-print model (speaker embedding) makes a print of every piece,
3. pieces with close prints are the same person -> "Speaker 1", "Speaker 2" ... in the order
   they first speak.
A voice has no name: the Meeting agent finds the names from what is said and from the people
who joined the call.

sherpa-onnx runs on this computer: free and offline. The two models (about 37 MB) are
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
# CAM++ trained on VoxCeleb (thousands of speakers, many languages): the voice prints
EMBEDDING_URL = (
    f"{_RELEASES}/speaker-recongition-models/3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx"
)
EMBEDDING_SHA256 = "357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b"

Turn = tuple[float, float, int]  # (start, end, speaker number 0, 1, ...) in seconds
Word = tuple[float, float, str]  # (start, end, text) from Whisper
Line = tuple[float, str, str]  # (start, "Speaker 1", text)

_diarizer = None
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
    embedding = folder / "campplus_voxceleb.onnx"
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


def _get_diarizer():
    global _diarizer
    with _lock:
        if _diarizer is None:
            import sherpa_onnx  # only when needed

            segmentation, embedding = _models()
            threads = max(1, (os.cpu_count() or 2) // 2)
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
