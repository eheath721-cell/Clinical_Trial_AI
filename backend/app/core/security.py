"""Password hashing (Argon2id) and server-side session tokens.

Session token: random 256-bit value in an httpOnly, SameSite=Lax cookie; only its SHA-256
is persisted, so a database leak does not yield usable sessions.
CSRF: double-submit token. A second, JS-readable cookie holds a CSRF token whose hash is
bound to the session; state-changing requests must echo it in the X-CSRF-Token header.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import utcnow
from app.models import AuthSession, User

SESSION_COOKIE = "tc_session"
CSRF_COOKIE = "tc_csrf"
CSRF_HEADER = "x-csrf-token"

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def create_session(db: Session, user: User) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=_sha(token),
            csrf_token_hash=_sha(csrf),
            expires_at=utcnow() + timedelta(hours=get_settings().session_ttl_hours),
        )
    )
    return token, csrf


def resolve_session(db: Session, token: str | None) -> AuthSession | None:
    if not token:
        return None
    sess = db.scalar(select(AuthSession).where(AuthSession.token_hash == _sha(token)))
    if sess is None or sess.revoked_at is not None:
        return None
    expires = sess.expires_at if sess.expires_at.tzinfo else sess.expires_at.replace(tzinfo=utcnow().tzinfo)
    if expires < utcnow():
        return None
    return sess


def csrf_matches(sess: AuthSession, header_value: str | None) -> bool:
    if not header_value:
        return False
    return secrets.compare_digest(sess.csrf_token_hash, _sha(header_value))


def revoke_session(db: Session, sess: AuthSession) -> None:
    sess.revoked_at = utcnow()
