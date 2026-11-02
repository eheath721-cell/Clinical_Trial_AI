"""Encryption at rest for uploaded documents and their extracted text."""

from __future__ import annotations

import hashlib
import hmac

from cryptography.fernet import Fernet

from app.core.config import get_settings

_dev_key: bytes | None = None


def _fernet() -> Fernet:
    global _dev_key
    settings = get_settings()
    if settings.document_encryption_key is not None:
        return Fernet(settings.document_encryption_key.get_secret_value().encode())
    if settings.environment in ("staging", "production"):
        raise RuntimeError("DOCUMENT_ENCRYPTION_KEY must be set outside development")
    # Development/test only: ephemeral key (documents are unreadable after restart, by design).
    if _dev_key is None:
        _dev_key = Fernet.generate_key()
    return Fernet(_dev_key)


def encrypt_bytes(data: bytes) -> bytes:
    return _fernet().encrypt(data)


def decrypt_bytes(token: bytes) -> bytes:
    return _fernet().decrypt(token)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_ip(ip: str | None) -> str | None:
    if not ip:
        return None
    salt = get_settings().audit_ip_salt.get_secret_value().encode()
    return hmac.new(salt, ip.encode(), hashlib.sha256).hexdigest()[:32]
