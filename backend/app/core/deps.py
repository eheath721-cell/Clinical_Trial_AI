"""Request dependencies: authentication, CSRF enforcement and profile-level RBAC."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CSRF_HEADER, SESSION_COOKIE, csrf_matches, resolve_session
from app.models import AuthSession, PatientProfile, ProfileAccess, User
from app.models.enums import ProfileAccessRole

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass
class AuthContext:
    user: User
    session: AuthSession


def get_auth(request: Request, db: Session = Depends(get_db)) -> AuthContext:
    sess = resolve_session(db, request.cookies.get(SESSION_COOKIE))
    if sess is None or not sess.user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    if request.method not in _SAFE_METHODS and not csrf_matches(sess, request.headers.get(CSRF_HEADER)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing or invalid CSRF token")
    return AuthContext(user=sess.user, session=sess)


_RANK = {ProfileAccessRole.viewer: 1, ProfileAccessRole.editor: 2, ProfileAccessRole.owner: 3}


def load_profile(db: Session, auth: AuthContext, profile_id: uuid.UUID, need: ProfileAccessRole) -> PatientProfile:
    profile = db.get(PatientProfile, profile_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not found")
    if profile.owner_user_id == auth.user.id:
        return profile
    grant = db.scalar(
        select(ProfileAccess).where(ProfileAccess.profile_id == profile_id, ProfileAccess.user_id == auth.user.id)
    )
    # 404 rather than 403 so profile IDs cannot be probed.
    if grant is None or _RANK[grant.role] < _RANK[need]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not found")
    return profile


def profile_reader(profile_id: uuid.UUID, auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    return load_profile(db, auth, profile_id, ProfileAccessRole.viewer)


def profile_editor(profile_id: uuid.UUID, auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    return load_profile(db, auth, profile_id, ProfileAccessRole.editor)


def profile_owner(profile_id: uuid.UUID, auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    return load_profile(db, auth, profile_id, ProfileAccessRole.owner)
