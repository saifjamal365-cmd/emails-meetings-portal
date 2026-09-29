"""Encrypt and decrypt saved OAuth tokens (Fernet = AES with a secret key)."""

from functools import lru_cache

from cryptography.fernet import Fernet

from app.config import get_settings, secret_from_file


@lru_cache
def _fernet() -> Fernet:
    # TOKEN_ENCRYPTION_KEY from .env, or a key created once in data_dir/token.key (git-ignored).
    key = get_settings().token_encryption_key.encode() or secret_from_file("token.key")
    return Fernet(key)


def encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
