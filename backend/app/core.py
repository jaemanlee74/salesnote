"""인증 의존성, 권한 규칙, 공통 직렬화."""
import time
from datetime import datetime

from fastapi import Depends, HTTPException, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from .config import settings
from .database import get_db
from .models import Opportunity, User, participants

# 단계 진입 시 필수 입력 (기능명세서 3장)
STAGE_REQUIRED: dict[str, list[str]] = {
    "contact": ["contacts"],
    "prepare": ["amount_expected", "expected_period"],
    "proposal": ["submitted_at"],
    "won": ["contract_amount", "contract_date"],
    "lost": ["close_reason_code"],
    "hold": ["close_reason_text", "review_date"],
}

FIELD_LABELS = {
    "contacts": "고객 담당자",
    "amount_expected": "예상 금액",
    "expected_period": "예상 공고·제안 시기",
    "proposal_deadline": "제안 마감일",
    "submitted_at": "제출일",
    "project_start": "사업 시작일",
    "project_end": "사업 종료일",
    "contract_amount": "계약 금액",
    "contract_date": "계약일",
    "close_reason_code": "실주 사유",
    "close_reason_text": "사유 상세",
    "review_date": "재검토 예정일",
    "owner": "담당자",
}

SENSITIVE_FIELDS = {"amount_expected", "contract_amount"}


# ---------- 인증 ----------

def _load_user(request: Request, db: Session, touch: bool) -> User:
    session = request.session
    uid, ts = session.get("uid"), session.get("ts")
    if not uid or not ts or time.time() - ts > settings.session_idle_minutes * 60:
        session.clear()
        raise HTTPException(401, "로그인이 필요합니다.")
    user = db.get(User, uid)
    if not user or not user.is_active:
        session.clear()
        raise HTTPException(401, "접근이 허용되지 않은 계정입니다.")
    if touch:
        session["ts"] = int(time.time())
    return user


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    return _load_user(request, db, touch=True)


def current_user_passive(request: Request, db: Session = Depends(get_db)) -> User:
    """자동 폴링용. 미사용 시간을 갱신하지 않는다."""
    return _load_user(request, db, touch=False)


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "관리자만 사용할 수 있습니다.")
    return user


# ---------- 권한 (기능명세서 2장) ----------

def is_admin(user: User) -> bool:
    return user.role == "admin"


def is_assigned(opp: Opportunity, user: User) -> bool:
    """담당자 또는 참여자."""
    return opp.owner_id == user.id or any(p.id == user.id for p in opp.participants)


def can_view(opp: Opportunity, user: User) -> bool:
    return is_admin(user) or opp.visibility == "public" or is_assigned(opp, user)


def can_edit(opp: Opportunity, user: User) -> bool:
    return is_admin(user) or opp.owner_id == user.id


def can_record(opp: Opportunity, user: User) -> bool:
    return is_admin(user) or is_assigned(opp, user)


def can_see_amount(opp: Opportunity, user: User) -> bool:
    return is_admin(user) or is_assigned(opp, user)


def can_delete(opp: Opportunity, user: User) -> bool:
    return is_admin(user) or (opp.owner_id == user.id and opp.created_by == user.id)


def visible_condition(user: User):
    """목록·검색에서 비공개 기회를 걸러내는 조건."""
    return or_(
        Opportunity.visibility == "public",
        Opportunity.owner_id == user.id,
        Opportunity.id.in_(
            select(participants.c.opportunity_id).where(participants.c.user_id == user.id)
        ),
    )


def visible_opps(user: User):
    q = select(Opportunity).where(Opportunity.deleted_at.is_(None))
    if not is_admin(user):
        q = q.where(visible_condition(user))
    return q


OPP_LOAD = (
    selectinload(Opportunity.owner),
    selectinload(Opportunity.participants),
    selectinload(Opportunity.tags),
)


def get_opp(db: Session, opp_id: int, user: User) -> Opportunity:
    """열람 권한이 없으면 존재 여부를 드러내지 않도록 404로 응답한다."""
    opp = db.get(Opportunity, opp_id)
    if not opp or opp.deleted_at is not None or not can_view(opp, user):
        raise HTTPException(404, "영업기회를 찾을 수 없습니다.")
    return opp


def require(ok: bool, message: str = "권한이 없습니다.") -> None:
    if not ok:
        raise HTTPException(403, message)


# ---------- 직렬화 ----------

def iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") + "Z" if dt else None


def d(value) -> str | None:
    return value.isoformat() if value else None


def user_brief(user: User | None) -> dict | None:
    if not user:
        return None
    return {"id": user.id, "name": user.name or user.email, "title": user.title}


def opp_brief(opp: Opportunity, user: User) -> dict:
    amount = can_see_amount(opp, user)
    return {
        "id": opp.id,
        "title": opp.title,
        "customer": opp.customer,
        "stage": opp.stage_code,
        "biz_type": opp.biz_type,
        "owner": user_brief(opp.owner),
        "participants": [user_brief(p) for p in opp.participants],
        "tags": [t.name for t in opp.tags],
        "visibility": opp.visibility,
        "amount_expected": opp.amount_expected if amount else None,
        "contract_amount": opp.contract_amount if amount else None,
        "amount_hidden": not amount,
        "win_probability": opp.win_probability,
        "expected_period": opp.expected_period,
        "proposal_deadline": d(opp.proposal_deadline),
        "created_at": iso(opp.created_at),
        "updated_at": iso(opp.updated_at),
        "perms": {
            "edit": can_edit(opp, user),
            "record": can_record(opp, user),
            "delete": can_delete(opp, user),
            "amount": amount,
        },
    }


def opp_detail(opp: Opportunity, user: User) -> dict:
    out = opp_brief(opp, user)
    out.update(
        overview=opp.overview,
        source=opp.source,
        contacts=[
            {"id": c.id, "name": c.name, "position": c.position, "phone": c.phone, "email": c.email}
            for c in opp.contacts
        ],
        submitted_at=d(opp.submitted_at),
        project_start=d(opp.project_start),
        project_end=d(opp.project_end),
        competitors=opp.competitors or [],
        partners=opp.partners or [],
        links=opp.links or [],
        contract_date=d(opp.contract_date),
        close_reason_code=opp.close_reason_code,
        close_reason_text=opp.close_reason_text,
        review_date=d(opp.review_date),
        created_by=opp.created_by,
    )
    return out
