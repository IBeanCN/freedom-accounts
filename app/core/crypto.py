"""Symmetric encryption for sensitive DB fields (passwords, TOTP, proxy auth).

Encrypted values are stored with an ``enc:`` prefix so legacy plaintext rows
can be detected and migrated on startup without a flag column.
"""
from cryptography.fernet import Fernet, InvalidToken

_PREFIX = "enc:"
_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        from . import config
        _fernet = Fernet(config.ENCRYPTION_KEY.encode())
    return _fernet


def encrypt(plain: str) -> str:
    """Encrypt a plaintext value; empty string passes through."""
    if not plain:
        return plain
    token = _get_fernet().encrypt(plain.encode()).decode()
    return _PREFIX + token


def decrypt(stored: str) -> str:
    """Decrypt a stored value; legacy plaintext (no prefix) passes through."""
    if not stored or not stored.startswith(_PREFIX):
        return stored
    try:
        return _get_fernet().decrypt(stored[len(_PREFIX):].encode()).decode()
    except (InvalidToken, Exception):
        # If decryption fails (wrong key, corrupted data), return raw value
        # so callers see the issue instead of getting an empty string.
        return stored


def is_encrypted(value: str) -> bool:
    return bool(value and value.startswith(_PREFIX))


def ensure_encrypted(value: str) -> str:
    """Encrypt only when not already encrypted (idempotent for migration)."""
    if not value or is_encrypted(value):
        return value
    return encrypt(value)
