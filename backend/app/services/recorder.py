"""Record a meeting on this computer, as two audio tracks:

- "me"     = your microphone      -> what YOU say
- "others" = your speakers/headset -> what the OTHER people say (Windows "loopback")

Two tracks let the transcript say who spoke, without any voice recognition.
Tip: use headphones, so the others' voices do not also go into your microphone.

The audio is written to WAV files (16 kHz, mono) while recording, so long meetings do not
fill the memory. Only one recording can run at a time.
"""

import contextlib
import logging
import threading
import wave
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
CHUNK = SAMPLE_RATE // 5  # read 0.2 seconds at a time, without pause
VOICE_LEVEL = 0.01  # RMS above this = someone is talking


@dataclass
class RecordingState:
    meeting_id: int | None = None
    title: str = ""
    started_at: datetime | None = None
    scheduled_start: datetime | None = None  # calendar start (recording starts a bit earlier)
    until: datetime | None = None  # planned stop (calendar end); can be extended
    extra_minutes: int = 0  # minutes added after the calendar end because people still talked
    seconds: int = 0
    last_voice_at: datetime | None = None
    has_speaker_track: bool = True
    error: str = ""
    me_file: Path | None = None
    others_file: Path | None = None
    finished: bool = False


def _to_wav_bytes(block: np.ndarray) -> bytes:
    mono = block.mean(axis=1) if block.ndim == 2 else block
    return (np.clip(mono, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def _level(block: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(block)))) if block.size else 0.0


def _open_wav(path: Path) -> wave.Wave_write:
    w = wave.open(str(path), "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(SAMPLE_RATE)
    return w


class Recorder:
    def __init__(self) -> None:
        self.state = RecordingState()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, meeting_id: int, title: str, until: datetime, folder: Path) -> None:
        with self._lock:
            if self.running:
                raise RuntimeError("A recording is already running.")
            folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            self.state = RecordingState(
                meeting_id=meeting_id,
                title=title,
                started_at=datetime.now(),
                until=until,
                me_file=folder / f"meeting{meeting_id}-{stamp}-me.wav",
                others_file=folder / f"meeting{meeting_id}-{stamp}-others.wav",
            )
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="recorder", daemon=True)
            self._thread.start()

    def extend(self, minutes: int) -> None:
        if self.state.until:
            self.state.until += timedelta(minutes=minutes)
            self.state.extra_minutes += minutes

    def stop(self) -> RecordingState:
        """Stop and wait until the files are closed. Returns the final state."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=15)
        self.state.finished = True
        return self.state

    def _run(self) -> None:
        """Start one thread per device and wait until Stop.

        Each device MUST have its own thread: when one loop read the microphone and the
        speakers one after the other, the microphone's small buffer overflowed while waiting
        for the speakers, and Windows dropped about 40% of the speech.
        """
        import soundcard as sc  # Windows/macOS/Linux audio; imported here, only when recording

        s = self.state
        try:
            mic = sc.default_microphone()
        except Exception as e:  # no microphone
            log.exception("No microphone")
            s.error = f"Recording failed: no microphone ({e})"
            return
        try:
            speakers = sc.get_microphone(id=str(sc.default_speaker().name), include_loopback=True)
        except Exception:  # no output device: record only the microphone
            speakers = None
            s.has_speaker_track = False
            _open_wav(s.others_file).close()  # an empty "others" track

        devices = [(mic, s.me_file)] + ([(speakers, s.others_file)] if speakers else [])
        threads = [
            threading.Thread(target=self._record_device, args=(d, f), daemon=True)
            for d, f in devices
        ]
        for t in threads:
            t.start()
        while not self._stop.wait(0.5):
            s.seconds = int((datetime.now() - s.started_at).total_seconds())
            if not any(t.is_alive() for t in threads):
                break  # every device failed (the error is in s.error)
        self._stop.set()
        for t in threads:
            t.join(timeout=10)
        s.seconds = int((datetime.now() - s.started_at).total_seconds())

    def _record_device(self, device, path: Path) -> None:
        """Read one device in small pieces, all the time, and write them to its WAV file."""
        s = self.state
        try:
            with (
                contextlib.closing(_open_wav(path)) as wav,
                device.recorder(samplerate=SAMPLE_RATE, channels=1) as rec,
            ):
                while not self._stop.is_set():
                    block = rec.record(numframes=CHUNK)
                    wav.writeframes(_to_wav_bytes(block))
                    if _level(block) > VOICE_LEVEL:
                        s.last_voice_at = datetime.now()
        except Exception as e:  # e.g. the device was unplugged
            log.exception("Recording failed")
            s.error = f"Recording failed ({path.stem}): {e}"


recorder = Recorder()
