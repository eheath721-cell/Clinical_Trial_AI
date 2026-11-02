"""Encrypted blob storage for uploaded documents (local disk for the MVP; the interface is
small so it can be swapped for S3/GCS with server-side KMS encryption)."""

from __future__ import annotations

import secrets
from pathlib import Path

from app.core.config import get_settings
from app.core.crypto import decrypt_bytes, encrypt_bytes


def _root() -> Path:
    root = Path(get_settings().document_storage_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def put_blob(data: bytes) -> str:
    key = secrets.token_hex(24)
    (_root() / key).write_bytes(encrypt_bytes(data))
    return key


def get_blob(key: str) -> bytes:
    return decrypt_bytes((_root() / key).read_bytes())


def delete_blob(key: str) -> None:
    path = _root() / key
    if path.exists():
        path.unlink()
