"""공통 정보, 내 설정, 알림 목록, 대시보드 (NTF-01, DSH, SC-09)."""
from datetime import timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..core import (
    FIELD_LABELS,
    OPP_LOAD,
    STAGE_REQUIRED,
    can_see_amount,
    current_user,
    current_user_passive,
    d,
    iso,
    opp_brief,
    user_brief,
    visible_opps,
)
from ..database import get_db
from ..models import TERMINAL_STAGES, Code, Notification, Opportunity, Tag, Todo, User, today_kst
from ..services import like_pattern

router = APIRouter(prefix="/api", tags=["misc"])


def me_out(user: User) -> dict:
    return {"id": user.id, "email": user.email, "name": user.name, "title": user.title,
            "role": user.role, "picture": user.picture, "notify_email": user.notify_email}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return me_out(user)


class MeIn(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    title: str | None = Field(None, max_length=50)
    notify_email: bool | None = None


@router.patch("/me")
def update_me(body: MeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(user, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    return me_out(user)


@router.get("/meta")
def meta(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """화면이 쓰는 코드와 사용자 목록."""
    codes: dict[str, list] = {}
    for c in db.scalars(select(Code).order_by(Code.kind, Code.sort_order, Code.id)):
        codes.setdefault(c.kind, []).append({
            "code": c.code, "name": c.name, "is_active": c.is_active,
            "terminal": c.kind == "stage" and c.code in TERMINAL_STAGES,
        })
    users = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.name)).all()
    return {
        "me": me_out(user),
        "codes": codes,
        "users": [user_brief(u) for u in users],
        "stage_required": STAGE_REQUIRED,
        "field_labels": FIELD_LABELS,
    }


@router.get("/customers")
def customers(q: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)):
    """고객사 자동완성. 열람할 수 있는 기회의 고객사만 보여준다."""
    visible = visible_opps(user).subquery()
    query = select(visible.c.customer).distinct().order_by(visible.c.customer).limit(20)
    if q.strip():
        query = query.where(visible.c.customer.like(like_pattern(q.strip()), escape="!"))
    return list(db.scalars(query))


@router.get("/tags")
def tags(user: User = Depends(current_user), db: Session = Depends(get_db)):
    visible = visible_opps(user).subquery()
    query = (select(Tag.name, func.count()).join(visible, visible.c.id == Tag.opportunity_id)
             .group_by(Tag.name).order_by(func.count().desc()).limit(50))
    return [name for name, _ in db.execute(query)]


# ---------- 알림 ----------

@router.get("/notifications/count")
def notification_count(user: User = Depends(current_user_passive), db: Session = Depends(get_db)):
    count = db.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == user.id, Notification.is_read.is_(False)))
    return {"unread": count}


@router.get("/notifications")
def notifications(unread: bool = False, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    query = select(Notification).where(Notification.user_id == user.id)
    if unread:
        query = query.where(Notification.is_read.is_(False))
    rows = db.scalars(query.order_by(Notification.id.desc()).limit(200)).all()
    return [{"id": n.id, "kind": n.kind, "message": n.message, "opportunity_id": n.opportunity_id,
             "activity_id": n.activity_id, "comment_id": n.comment_id, "is_read": n.is_read,
             "created_at": iso(n.created_at)} for n in rows]


@router.post("/notifications/{notification_id}/read")
def read_notification(notification_id: int, user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    db.execute(update(Notification).where(
        Notification.id == notification_id, Notification.user_id == user.id).values(is_read=True))
    db.commit()
    return {"ok": True}


@router.post("/notifications/read-all")
def read_all(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(update(Notification).where(
        Notification.user_id == user.id, Notification.is_read.is_(False)).values(is_read=True))
    db.commit()
    return {"ok": True}


# ---------- 대시보드 ----------

@router.get("/dashboard")
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    opps = db.scalars(visible_opps(user).options(*OPP_LOAD)).all()
    by_id = {o.id: o for o in opps}
    today = today_kst()

    # 단계별 건수와 예상 금액. 금액은 열람할 수 있는 건만 더한다.
    stages: dict[str, dict] = {}
    for o in opps:
        row = stages.setdefault(o.stage_code, {"count": 0, "amount": 0, "hidden": 0})
        row["count"] += 1
        if can_see_amount(o, user):
            # 수주 건은 계약 금액으로 집계한다
            value = o.contract_amount if o.stage_code == "won" else o.amount_expected
            row["amount"] += value or 0
        else:
            row["hidden"] += 1

    open_opps = [o for o in opps if o.stage_code not in TERMINAL_STAGES]
    recent = sorted(open_opps, key=lambda o: o.updated_at, reverse=True)[:8]

    open_ids = [o.id for o in open_opps]
    todos = []
    if open_ids:
        rows = db.scalars(select(Todo).where(
            Todo.opportunity_id.in_(open_ids), Todo.done.is_(False),
            Todo.due_date.is_not(None), Todo.due_date <= today + timedelta(days=7))
            .order_by(Todo.due_date).limit(30)).all()
        todos = [{"id": t.id, "content": t.content, "due_date": d(t.due_date),
                  "assignee": user_brief(t.assignee), "opportunity_id": t.opportunity_id,
                  "opportunity_title": by_id[t.opportunity_id].title} for t in rows]

    # 올해 수주·실주 통계
    year_start = today.replace(month=1, day=1)
    closed = [o for o in opps if o.stage_code in ("won", "lost")
              and (o.updated_at + timedelta(hours=9)).date() >= year_start]
    won = [o for o in closed if o.stage_code == "won"]
    lost = [o for o in closed if o.stage_code == "lost"]
    closed_ids = {o.id for o in closed}
    reasons: dict[str, int] = {}
    for o in lost:
        key = o.close_reason_code or "etc"
        reasons[key] = reasons.get(key, 0) + 1
    owners: dict[int, dict] = {}
    for o in opps:
        row = owners.setdefault(o.owner_id, {"owner": user_brief(o.owner), "open": 0, "won": 0, "lost": 0})
        if o.id in closed_ids:
            row[o.stage_code] += 1
        elif o.stage_code not in TERMINAL_STAGES:
            row["open"] += 1

    return {
        "stages": stages,
        "recent": [opp_brief(o, user) for o in recent],
        "todos": todos,
        "stats": {
            "year": today.year,
            "won": len(won), "lost": len(lost),
            "win_rate": round(len(won) / len(closed) * 100) if closed else None,
            "loss_reasons": reasons,
            "owners": sorted(owners.values(), key=lambda r: -(r["open"] + r["won"] + r["lost"])),
        },
    }
