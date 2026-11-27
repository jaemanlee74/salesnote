"""구글 계정 로그인 (ADM-01). 허용 목록에 있는 계정만 세션을 받는다."""
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import User, utcnow
from ..services import audit

router = APIRouter(prefix="/auth", tags=["auth"])

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"


def _redirect_uri() -> str:
    return f"{settings.base_url}/auth/callback"


def _sign_in(request: Request, db: Session, user: User, name: str = "", picture: str = "") -> None:
    if name and (not user.name or user.name == user.email.split("@")[0]):
        user.name = name[:100]
    if picture:
        user.picture = picture[:500]
    user.last_login_at = utcnow()
    request.session.clear()
    request.session.update(uid=user.id, ts=int(time.time()))
    audit(db, request, user, "login")
    db.commit()


def _allowed_user(db: Session, email: str) -> User | None:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    return user if user and user.is_active else None


@router.get("/config")
def config():
    return {"google": settings.google_enabled, "dev_login": settings.dev_login}


@router.get("/login")
def login(request: Request):
    if not settings.google_enabled:
        raise HTTPException(503, "구글 로그인이 설정되지 않았습니다.")
    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    query = urlencode({
        "client_id": settings.google_client_id,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    })
    return RedirectResponse(f"{GOOGLE_AUTH}?{query}")


@router.get("/callback")
def callback(request: Request, code: str = "", state: str = "", db: Session = Depends(get_db)):
    expected = request.session.pop("oauth_state", None)
    if not code or not expected or not secrets.compare_digest(state, expected):
        return RedirectResponse("/#/login?error=failed")
    try:
        token = httpx.post(GOOGLE_TOKEN, timeout=10, data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": _redirect_uri(),
            "grant_type": "authorization_code",
        })
        token.raise_for_status()
        info = httpx.get(GOOGLE_USERINFO, timeout=10, headers={
            "Authorization": f"Bearer {token.json()['access_token']}"
        })
        info.raise_for_status()
        profile = info.json()
    except Exception:  # noqa: BLE001
        return RedirectResponse("/#/login?error=failed")

    email = (profile.get("email") or "").lower()
    user = _allowed_user(db, email) if profile.get("email_verified") else None
    if not user:
        audit(db, request, None, "login_denied", email=email)
        db.commit()
        return RedirectResponse("/#/login?error=not_allowed")
    _sign_in(request, db, user, profile.get("name", ""), profile.get("picture", ""))
    return RedirectResponse("/")


class DevLogin(BaseModel):
    email: str


@router.post("/dev-login")
def dev_login(body: DevLogin, request: Request, db: Session = Depends(get_db)):
    """개발 환경 전용. DEV_LOGIN=true일 때만 열린다."""
    if not settings.dev_login:
        raise HTTPException(404)
    user = _allowed_user(db, body.email)
    if not user:
        audit(db, request, None, "login_denied", email=body.email[:255])
        db.commit()
        raise HTTPException(403, "접근이 허용되지 않은 계정입니다. 관리자에게 등록을 요청하세요.")
    _sign_in(request, db, user)
    return {"ok": True}


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}
