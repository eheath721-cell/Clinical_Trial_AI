from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import AuthContext, get_auth
from app.core.security import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    create_session,
    hash_password,
    revoke_session,
    verify_password,
)
from app.core.storage import delete_blob
from app.models import AuditEvent, Consent, Document, PatientProfile, User

router = APIRouter(prefix="/api", tags=["accounts"])

CONSENT_VERSION = "2026-11-01"
REQUIRED_CONSENTS = ("terms", "privacy", "health_data")

_attempts: dict[str, deque] = defaultdict(deque)


def _throttle(key: str, limit: int = 8, window: int = 300) -> None:
    now = time.monotonic()
    q = _attempts[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Please wait a few minutes.")
    q.append(now)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    display_name: str | None = Field(None, max_length=120)
    accept_terms: bool
    accept_privacy: bool
    accept_health_data: bool
    accept_ai_processing: bool = False


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class ConsentIn(BaseModel):
    consent_type: str = Field(pattern="^(ai_processing)$")
    granted: bool


def _set_cookies(resp: Response, token: str, csrf: str) -> None:
    s = get_settings()
    max_age = s.session_ttl_hours * 3600
    resp.set_cookie(SESSION_COOKIE, token, httponly=True, secure=s.cookie_secure, samesite="lax", max_age=max_age, path="/")
    resp.set_cookie(CSRF_COOKIE, csrf, httponly=False, secure=s.cookie_secure, samesite="lax", max_age=max_age, path="/")


def _consents(db: Session, user: User) -> dict[str, bool]:
    latest: dict[str, bool] = {}
    for c in sorted(user.consents, key=lambda c: c.created_at):
        latest[c.consent_type] = c.granted
    return latest


def user_out(db: Session, user: User) -> dict:
    return {"id": str(user.id), "email": user.email, "display_name": user.display_name, "role": user.role.value,
            "consents": _consents(db, user)}


@router.post("/auth/register", status_code=201)
def register(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)):
    _throttle(f"reg:{request.client.host if request.client else 'x'}", limit=10, window=3600)
    if not (body.accept_terms and body.accept_privacy and body.accept_health_data):
        raise HTTPException(400, "Terms, privacy notice and health-data consent are required to create an account.")
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists.")
    user = User(email=email, password_hash=hash_password(body.password), display_name=body.display_name)
    db.add(user)
    db.flush()
    for ct, granted in (("terms", True), ("privacy", True), ("health_data", True),
                        ("ai_processing", body.accept_ai_processing)):
        db.add(Consent(user_id=user.id, consent_type=ct, version=CONSENT_VERSION, granted=granted))
    token, csrf = create_session(db, user)
    audit.record(db, "account.register", actor_id=user.id, request=request, resource_type="user", resource_id=user.id)
    db.commit()
    db.refresh(user)
    _set_cookies(response, token, csrf)
    return user_out(db, user)


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.lower()
    _throttle(f"login:{email}")
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active or not verify_password(user.password_hash, body.password):
        audit.record(db, "auth.login", actor_id=user.id if user else None, request=request, outcome="failure")
        db.commit()
        raise HTTPException(401, "Incorrect email or password.")
    token, csrf = create_session(db, user)
    audit.record(db, "auth.login", actor_id=user.id, request=request)
    db.commit()
    _set_cookies(response, token, csrf)
    return user_out(db, user)


@router.post("/auth/logout")
def logout(request: Request, response: Response, auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    revoke_session(db, auth.session)
    audit.record(db, "auth.logout", actor_id=auth.user.id, request=request)
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/session")
def session_state(request: Request, db: Session = Depends(get_db)):
    """Like /auth/me but returns {"user": null} instead of 401, for public pages."""
    from app.core.security import resolve_session

    sess = resolve_session(db, request.cookies.get(SESSION_COOKIE))
    if sess is None or not sess.user.is_active:
        return {"user": None}
    return {"user": user_out(db, sess.user)}


@router.get("/auth/me")
def me(auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    return user_out(db, auth.user)


@router.post("/account/consents")
def update_consent(body: ConsentIn, request: Request, auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    db.add(Consent(user_id=auth.user.id, consent_type=body.consent_type, version=CONSENT_VERSION, granted=body.granted))
    audit.record(db, "consent.update", actor_id=auth.user.id, request=request, meta={"status": str(body.granted)})
    db.commit()
    db.refresh(auth.user)
    return user_out(db, auth.user)


@router.get("/account/audit")
def my_audit(auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditEvent).where(AuditEvent.actor_user_id == auth.user.id)
                      .order_by(AuditEvent.occurred_at.desc()).limit(200)).all()
    return [{"at": r.occurred_at.isoformat(), "action": r.action, "resource_type": r.resource_type,
             "outcome": r.outcome} for r in rows]


@router.get("/account/export")
def export_data(request: Request, auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    """Machine-readable export of everything stored about the account (data portability)."""
    from app.modules.eligibility.service import load_profile_full
    from app.modules.profiles.router import profile_out

    profiles = db.scalars(select(PatientProfile).where(PatientProfile.owner_user_id == auth.user.id)).all()
    audit.record(db, "account.export", actor_id=auth.user.id, request=request)
    db.commit()
    return {"account": user_out(db, auth.user),
            "profiles": [profile_out(load_profile_full(db, p.id)) for p in profiles],
            "note": "Uploaded files can be downloaded individually from the Documents page."}


@router.delete("/account")
def delete_account(request: Request, response: Response, auth: AuthContext = Depends(get_auth),
                   db: Session = Depends(get_db)):
    """Permanently deletes the account, all profiles, health information, documents (including
    encrypted files) and enrollment records. Audit events are retained without identifiers."""
    user = auth.user
    docs = db.scalars(select(Document).join(PatientProfile).where(PatientProfile.owner_user_id == user.id)).all()
    for d in docs:
        delete_blob(d.storage_key)
    audit.record(db, "account.delete", actor_id=None, request=request, resource_type="user", meta={"count": len(docs)})
    db.delete(user)
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"deleted": True}
