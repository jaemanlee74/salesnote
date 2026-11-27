"""관리자: 허용 사용자, 코드, 구글 챗 연동, 휴지통, 감사 기록 (ADM, NTF-04, OPP-04)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core import admin_user, iso, user_brief
from ..database import get_db
from ..models import AuditLog, Code, Opportunity, Setting, User
from ..services import audit, post_chat
from ..jobs import purge_opportunity

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(admin_user)])

CODE_KINDS = ("stage", "biz_type", "activity_type", "loss_reason")
CHAT_PREFIX = "https://chat.googleapis.com/"


# ---------- 허용 사용자 ----------

def _user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "title": u.title, "role": u.role,
            "is_active": u.is_active, "last_login_at": iso(u.last_login_at)}


class UserIn(BaseModel):
    email: str | None = Field(None, max_length=255)
    name: str | None = Field(None, max_length=100)
    title: str | None = Field(None, max_length=50)
    role: str | None = None
    is_active: bool | None = None


@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    return [_user_out(u) for u in db.scalars(select(User).order_by(User.is_active.desc(), User.name))]


@router.post("/users", status_code=201)
def add_user(body: UserIn, db: Session = Depends(get_db)):
    email = (body.email or "").strip().lower()
    if "@" not in email:
        raise HTTPException(422, "구글 계정 메일을 입력하세요.")
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "이미 등록된 계정입니다.")
    if body.role not in (None, "admin", "member"):
        raise HTTPException(422, "역할이 올바르지 않습니다.")
    user = User(email=email, name=(body.name or "").strip() or email.split("@")[0],
                title=(body.title or "").strip(), role=body.role or "member")
    db.add(user)
    db.commit()
    return _user_out(user)


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserIn, admin: User = Depends(admin_user),
                db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "사용자를 찾을 수 없습니다.")
    data = body.model_dump(exclude_unset=True)
    if user.id == admin.id and (data.get("role") == "member" or data.get("is_active") is False):
        raise HTTPException(422, "본인의 관리자 권한이나 사용 상태는 바꿀 수 없습니다.")
    if data.get("role") in ("admin", "member"):
        user.role = data["role"]
    if data.get("is_active") is not None:
        user.is_active = data["is_active"]
    if data.get("name"):
        user.name = data["name"].strip()
    if "title" in data:
        user.title = (data["title"] or "").strip()
    db.commit()
    return _user_out(user)


# ---------- 코드 ----------

def _code_out(c: Code) -> dict:
    return {"id": c.id, "kind": c.kind, "code": c.code, "name": c.name,
            "sort_order": c.sort_order, "is_active": c.is_active, "is_system": c.is_system}


class CodeIn(BaseModel):
    kind: str | None = None
    name: str | None = Field(None, max_length=100)
    is_active: bool | None = None


class Reorder(BaseModel):
    kind: str
    ids: list[int]


@router.get("/codes")
def list_codes(db: Session = Depends(get_db)):
    return [_code_out(c) for c in db.scalars(select(Code).order_by(Code.kind, Code.sort_order, Code.id))]


@router.post("/codes", status_code=201)
def add_code(body: CodeIn, db: Session = Depends(get_db)):
    name = (body.name or "").strip()
    if body.kind not in CODE_KINDS or not name:
        raise HTTPException(422, "분류와 이름을 입력하세요.")
    last = db.scalar(select(func.max(Code.sort_order)).where(Code.kind == body.kind)) or 0
    code = Code(kind=body.kind, code=f"c_{uuid.uuid4().hex[:8]}", name=name, sort_order=last + 1)
    db.add(code)
    db.commit()
    return _code_out(code)


@router.patch("/codes/{code_id}")
def update_code(code_id: int, body: CodeIn, db: Session = Depends(get_db)):
    code = db.get(Code, code_id)
    if not code:
        raise HTTPException(404, "코드를 찾을 수 없습니다.")
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(422, "이름을 입력하세요.")
        code.name = body.name.strip()
    if body.is_active is not None:
        if code.is_system and not body.is_active:
            raise HTTPException(422, "기본 코드는 이름과 순서만 바꿀 수 있습니다.")
        if code.kind == "stage" and not body.is_active and db.scalar(
                select(func.count()).select_from(Opportunity).where(
                    Opportunity.stage_code == code.code, Opportunity.deleted_at.is_(None))):
            raise HTTPException(422, "이 단계에 있는 영업기회가 있어 중지할 수 없습니다.")
        code.is_active = body.is_active
    db.commit()
    return _code_out(code)


@router.post("/codes/reorder")
def reorder_codes(body: Reorder, db: Session = Depends(get_db)):
    codes = {c.id: c for c in db.scalars(select(Code).where(Code.kind == body.kind))}
    for order, code_id in enumerate(body.ids, start=1):
        if code_id in codes:
            codes[code_id].sort_order = order
    db.commit()
    return {"ok": True}


# ---------- 구글 챗 연동 ----------

class ChatIn(BaseModel):
    webhook: str = Field("", max_length=1000)


@router.get("/chat")
def get_chat(db: Session = Depends(get_db)):
    row = db.get(Setting, "google_chat_webhook")
    return {"webhook": row.value if row else ""}


@router.put("/chat")
def set_chat(body: ChatIn, db: Session = Depends(get_db)):
    webhook = body.webhook.strip()
    if webhook and not webhook.startswith(CHAT_PREFIX):
        raise HTTPException(422, f"{CHAT_PREFIX} 로 시작하는 웹훅 주소만 등록할 수 있습니다.")
    row = db.get(Setting, "google_chat_webhook")
    if row:
        row.value = webhook
    else:
        db.add(Setting(name="google_chat_webhook", value=webhook))
    db.commit()
    return {"webhook": webhook}


@router.post("/chat/test")
def test_chat(db: Session = Depends(get_db)):
    row = db.get(Setting, "google_chat_webhook")
    if not row or not row.value:
        raise HTTPException(422, "웹훅 주소를 먼저 저장하세요.")
    try:
        post_chat(row.value, "SalesNote 구글 챗 연동 테스트입니다.")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, "구글 챗으로 보내지 못했습니다. 웹훅 주소를 확인하세요.") from exc
    return {"ok": True}


# ---------- 휴지통 ----------

def _trashed(db: Session, opp_id: int) -> Opportunity:
    opp = db.get(Opportunity, opp_id)
    if not opp or opp.deleted_at is None:
        raise HTTPException(404, "휴지통에 없는 영업기회입니다.")
    return opp


@router.get("/trash")
def trash(db: Session = Depends(get_db)):
    opps = db.scalars(select(Opportunity).where(Opportunity.deleted_at.is_not(None))
                      .order_by(Opportunity.deleted_at.desc())).all()
    return [{"id": o.id, "title": o.title, "customer": o.customer, "owner": user_brief(o.owner),
             "deleted_at": iso(o.deleted_at)} for o in opps]


@router.post("/trash/{opp_id}/restore")
def restore(opp_id: int, db: Session = Depends(get_db)):
    opp = _trashed(db, opp_id)
    opp.deleted_at = opp.deleted_by = None
    db.commit()
    return {"ok": True}


@router.delete("/trash/{opp_id}")
def purge(opp_id: int, request: Request, admin: User = Depends(admin_user),
          db: Session = Depends(get_db)):
    opp = _trashed(db, opp_id)
    audit(db, request, admin, "purge", f"opportunity:{opp.id}", opp.title)
    purge_opportunity(db, opp)
    db.commit()
    return {"ok": True}


# ---------- 감사 기록 ----------

@router.get("/audit")
def audit_logs(page: int = 1, db: Session = Depends(get_db)):
    size = 50
    total = db.scalar(select(func.count()).select_from(AuditLog))
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc())
                      .offset((max(page, 1) - 1) * size).limit(size)).all()
    return {"total": total, "page": page, "size": size, "items": [
        {"id": r.id, "user_email": r.user_email, "action": r.action, "target": r.target,
         "detail": r.detail, "ip": r.ip, "created_at": iso(r.created_at)} for r in rows]}
