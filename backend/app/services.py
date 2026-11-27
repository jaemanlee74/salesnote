"""타임라인 기록, 알림(서비스 내·메일·구글 챗), 감사 기록, 텍스트 처리."""
import html
import logging
import smtplib
import threading
from email.message import EmailMessage

import httpx
import nh3
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .core import can_view
from .models import (
    Activity,
    AuditLog,
    Code,
    Notification,
    Opportunity,
    Setting,
    User,
    today_kst,
    utcnow,
    watchers,
)

log = logging.getLogger("salesnote")

ALLOWED_TAGS = {
    "p", "br", "b", "strong", "i", "em", "u", "s", "ul", "ol", "li",
    "a", "blockquote", "h3", "h4", "div", "span", "code", "pre",
}


def clean_html(value: str | None) -> str:
    """서식 텍스트에서 허용한 태그만 남긴다."""
    if not value:
        return ""
    return nh3.clean(
        value,
        tags=ALLOWED_TAGS,
        attributes={"a": {"href"}},
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer",
    )


def plain_text(value: str | None) -> str:
    if not value:
        return ""
    spaced = value.replace("<", " <")
    return " ".join(html.unescape(nh3.clean(spaced, tags=set())).split())


def like_pattern(term: str) -> str:
    escaped = term.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    return f"%{escaped}%"


def code_name(db: Session, kind: str, code: str | None) -> str:
    if not code:
        return ""
    name = db.scalar(select(Code.name).where(Code.kind == kind, Code.code == code))
    return name or code


def touch(opp: Opportunity) -> None:
    opp.updated_at = utcnow()


def add_system(db: Session, opp: Opportunity, user: User, event: str, meta: dict | None = None) -> Activity:
    """시스템이 남기는 타임라인 기록."""
    row = Activity(
        opportunity_id=opp.id,
        kind="system",
        event=event,
        activity_date=today_kst(),
        meta=meta or {},
        author_id=user.id,
    )
    db.add(row)
    return row


def audit(db: Session, request: Request | None, user: User | None, action: str,
          target: str = "", detail: str = "", email: str = "") -> None:
    ip = ""
    if request is not None:
        forwarded = request.headers.get("x-forwarded-for", "")
        ip = forwarded.split(",")[0].strip() or (request.client.host if request.client else "")
    db.add(AuditLog(
        user_id=user.id if user else None,
        user_email=user.email if user else email,
        action=action,
        target=target[:100],
        detail=detail[:500],
        ip=ip[:64],
    ))


# ---------- 알림 ----------

def find_mentions(db: Session, text: str) -> list[User]:
    """본문의 @이름을 사용자로 바꾼다."""
    if "@" not in text:
        return []
    users = db.scalars(select(User).where(User.is_active.is_(True))).all()
    return [u for u in users if u.name and f"@{u.name}" in text]


def opp_audience(db: Session, opp: Opportunity) -> set[int]:
    """담당자, 참여자, 관심 등록자."""
    ids = {opp.owner_id} | {p.id for p in opp.participants}
    ids |= set(db.scalars(select(watchers.c.user_id).where(watchers.c.opportunity_id == opp.id)))
    return ids


def notify(db: Session, recipients, actor: User | None, kind: str, opp: Opportunity,
           message: str, activity_id: int | None = None, comment_id: int | None = None,
           email: bool = False) -> None:
    """서비스 내 알림을 만든다. 본인이 일으킨 이벤트와 열람 권한이 없는 사용자는 제외한다."""
    ids = {i for i in recipients if i and (actor is None or i != actor.id)}
    if not ids:
        return
    users = db.scalars(select(User).where(User.id.in_(ids), User.is_active.is_(True))).all()
    for user in users:
        if not can_view(opp, user):
            continue
        db.add(Notification(
            user_id=user.id, kind=kind, message=message[:500], opportunity_id=opp.id,
            activity_id=activity_id, comment_id=comment_id, actor_id=actor.id if actor else None,
        ))
        if email and user.notify_email:
            send_mail(user.email, f"[SalesNote] {message}",
                      f"{message}\n\n{settings.base_url}/#/opp/{opp.id}")


def _background(fn, *args) -> None:
    threading.Thread(target=fn, args=args, daemon=True).start()


def send_mail(to: str, subject: str, body: str) -> None:
    if not settings.smtp_host or not settings.mail_from:
        return

    def _send():
        try:
            msg = EmailMessage()
            msg["From"], msg["To"], msg["Subject"] = settings.mail_from, to, subject[:200]
            msg.set_content(body)
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
                smtp.starttls()
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(msg)
        except Exception:
            log.exception("메일 발송 실패")

    _background(_send)


def chat_webhook(db: Session) -> str:
    row = db.get(Setting, "google_chat_webhook")
    return row.value if row else ""


def post_chat(url: str, text: str) -> None:
    httpx.post(url, json={"text": text}, timeout=10).raise_for_status()


def send_chat(db: Session, opp: Opportunity, text: str) -> None:
    """구글 챗 스페이스로 주요 알림을 보낸다. 비공개 기회는 보내지 않는다."""
    url = chat_webhook(db)
    if not url or opp.visibility != "public":
        return
    message = f"{text}\n{settings.base_url}/#/opp/{opp.id}"

    def _send():
        try:
            post_chat(url, message)
        except Exception:
            log.exception("구글 챗 발송 실패")

    _background(_send)
