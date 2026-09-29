"""App settings, loaded from environment variables and the .env file."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # "production" = login required, secure cookies, serve the built portal
    environment: Literal["development", "production"] = "development"

    # Where the database and the secret key files are kept (a cloud disk in production)
    data_dir: Path = BACKEND_DIR / "data"

    # LLM: Google Gemini, free tier (key from https://aistudio.google.com/apikey)
    gemini_api_key: str = ""
    llm_model: str = "gemini-3.1-flash-lite"
    # Backups, in order, when the main model is busy or its free daily limit is reached.
    # Each free model has its own limit (gemini-3.8-flash: only 20 requests per day).
    llm_fallback_models: str = "gemini-3.5-flash-lite,gemini-3.8-flash"
    # Meeting summaries need more care and are few per day: try this model first
    # (gemini-3.8-flash: 20 free calls per day), then the models above.
    meeting_llm_model: str = "gemini-3.8-flash"
    llm_max_tokens: int = 16000
    # Space between LLM calls. The free tier allows only a few calls per minute.
    llm_min_seconds_between_calls: float = 6.0

    # Database. Empty = SQLite file in data_dir. Later: postgresql+psycopg://...
    database_url: str = ""

    # Portal login. Empty password = no login (only allowed in development).
    portal_password: str = ""
    # Key that signs the login cookie. Empty = a key is created in data_dir/session.key.
    session_secret: str = ""
    session_days: int = 7

    # The portal's address (the React dev server in development, the app URL in production)
    frontend_origin: str = "http://localhost:5173"

    # Google (Gmail) OAuth - from Google Cloud Console -> Credentials -> OAuth client (Web)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"

    # Encryption key for saved OAuth tokens. Empty = a key is created in data_dir/token.key.
    token_encryption_key: str = ""

    # Email agent
    email_sync_minutes: int = 5  # check Gmail for new unread emails every N minutes (0 = off)
    email_sync_max: int = 50  # max unread emails to fetch per sync
    email_max_chars_for_llm: int = 6000  # longer emails are cut before the LLM reads them

    # Meeting agent: with auto-summarize on (Settings page), check for new transcripts
    meeting_sync_minutes: int = 10

    # Meeting recorder (Settings -> Auto-record): local Whisper speech-to-text, free and private.
    # Models: small (fast, weak Arabic) / medium / large-v3-turbo (best Arabic dialect, slower).
    # Downloaded once into data_dir/whisper (large-v3-turbo: ~1.6 GB).
    whisper_model: str = "large-v3-turbo"
    # The main language of the meetings ("ar", "en", ...). English words inside an Arabic
    # meeting are still written. Empty = Whisper guesses per piece (can guess wrong languages).
    whisper_language: str = "ar"
    # When the calendar end time comes but people still talk, keep recording 5 more minutes,
    # up to this many extra minutes.
    record_max_extra_minutes: int = 30
    keep_recordings: bool = False  # keep the audio files after the transcript is made
    recorder_check_seconds: int = 20  # how often to look for a meeting starting now (0 = off)
    record_start_early_seconds: int = 60  # start this early, so the first words are not lost
    # Stop by itself when nobody talks for this many minutes (you left the meeting). Before
    # anybody has talked it waits twice as long (people join late). 0 = only at the end time.
    silence_stop_minutes: int = 5
    # Separate the other people's voices on the speakers track ("Speaker 1", "Speaker 2" ...)
    # with sherpa-onnx (free, on this computer; models ~37 MB in data_dir/speakers).
    speaker_separation: bool = True
    # How different two voices must be to count as two people. Smaller = more speakers.
    speaker_threshold: float = 0.5

    # Daily planner: hour of the morning plan and of the end-of-day summary (-1 = off)
    morning_plan_hour: int = 8
    evening_summary_hour: int = 18

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{(self.data_dir / 'portal.db').as_posix()}"

    @property
    def login_required(self) -> bool:
        return bool(self.portal_password)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def secret_from_file(name: str) -> bytes:
    """A random secret kept in data_dir/<name>, created the first time it is needed."""
    from cryptography.fernet import Fernet

    path = get_settings().data_dir / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(Fernet.generate_key())
    return path.read_bytes().strip()
