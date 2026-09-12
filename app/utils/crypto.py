"""
Field-level encryption for sensitive data (phone numbers, email addresses,
OTP codes) stored in the database. Uses Fernet (AES-128-CBC + HMAC) from the
`cryptography` library, keyed by config.FIELD_ENCRYPTION_KEY.

This is what makes the "connect a separate database, encrypted" requirement
concrete without needing a full disk-encrypted DB engine like SQLCipher:
even if the .db file itself leaked, phone numbers/emails inside it are
unreadable without the key (which lives only in the server's environment,
never in the database or in source control).
"""

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


def _fernet() -> Fernet:
    key = current_app.config["FIELD_ENCRYPTION_KEY"]
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_value(plaintext: str) -> str:
    if plaintext is None:
        return None
    return _fernet().encrypt(str(plaintext).encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    if ciphertext is None:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        # Corrupt data or key mismatch - fail safe rather than crash the page
        return "***decryption-error***"


class EncryptedString:
    """
    Mixin-style descriptor pattern used inside SQLAlchemy models:
    store `<field>_enc` in the DB column, expose `<field>` as a plain
    python property that transparently encrypts/decrypts.
    See models.py `phone` / `email` properties for usage.
    """
    pass
