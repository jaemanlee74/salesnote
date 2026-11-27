"""영업기회 등록·조회·수정·삭제, 단계 변경, 목록·검색·내보내기 (OPP, STG, LST)."""
import io
import re
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, insert, or_, select
from sqlalchemy.orm import Session

from ..core import (
    FIELD_LABELS,
    OPP_LOAD,
    SENSITIVE_FIELDS,
    STAGE_REQUIRED,
    can_delete,
    can_edit,
    can_see_amount,
    current_user,
    d,
    get_opp,
    is_admin,
    iso,
    opp_brief,
    opp_detail,
    require,
    user_brief,
    visible_opps,
)
from ..database import get_db
from ..models import (
    TERMINAL_STAGES,
    Activity,
    Attachment,
    Code,
    Comment,
    Contact,
    Opportunity,
    Tag,
    Todo,
    User,
    participants,
    today_kst,
    utcnow,
    watchers,
)
from ..services import (
    add_system,
    audit,
    clean_html,
    code_name,
    like_pattern,
    notify,
    opp_audience,
    plain_text,
    send_chat,
    touch,
)

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])

PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])(-\d{2})?$")
NULLABLE = (
    "biz_type", "win_probability", "expected_period", "proposal_deadline", "submitted_at",
    "project_start", "project_end", "amount_expected", "contract_amount", "contract_date",
    "close_reason_code", "review_date", "owner_id",
)
TRACKED = (
    "amount_expected", "contract_amount", "expected_period", "proposal_deadline",
    "project_start", "project_end",
)


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    position: str = Field("", max_length=100)
    phone: str = Field("", max_length=50)
    email: str = Field("", max_length=255)


class OppFields(BaseModel):
    """등록·수정 공용. 수정은 보낸 항목만 바꾼다."""

    title: str | None = Field(None, max_length=100)
    customer: str | None = Field(None, max_length=100)
    biz_type: str | None = Field(None, max_length=50)
    overview: str | None = None
    source: str | None = Field(None, max_length=100)
    contacts: list[ContactIn] | None = None
    amount_expected: int | None = Field(None, ge=0)
    win_probability: str | None = None
    expected_period: str | None = None
    proposal_deadline: date | None = None
    submitted_at: date | None = None
    project_start: date | None = None
    project_end: date | None = None
    competitors: list[str] | None = None
    partners: list[str] | None = None
    links: list[str] | None = None
    tags: list[str] | None = None
    visibility: str | None = None
    owner_id: int | None = None
    participant_ids: list[int] | None = None
    contract_amount: int | None = Field(None, ge=0)
    contract_date: date | None = None
    close_reason_code: str | None = Field(None, max_length=50)
    close_reason_text: str | None = Field(None, max_length=2000)
    review_date: date | None = None

    @field_validator(*NULLABLE, mode="before")
    @classmethod
    def blank_to_none(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("expected_period")
    @classmethod
    def check_period(cls, value):
        if value and not PERIOD_RE.match(value):
            raise ValueError("YYYY-MM 또는 YYYY-MM-DD 형식으로 입력하세요.")
        return value

    @field_validator("win_probability")
    @classmethod
    def check_probability(cls, value):
        if value and value not in ("high", "mid", "low"):
            raise ValueError("상, 중, 하 중에서 고르세요.")
        return value

    @field_validator("visibility")
    @classmethod
    def check_visibility(cls, value):
        if value is not None and value not in ("public", "private"):
            raise ValueError("공개 범위가 올바르지 않습니다.")
        return value


def _clean_list(values: list[str] | None, limit: int, max_len: int) -> list[str]:
    seen: list[str] = []
    for value in values or []:
        value = value.strip()[:max_len]
        if value and value not in seen:
            seen.append(value)
    return seen[:limit]


def _active_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(422, "지정할 수 없는 사용자입니다.")
    return user


def _fmt(value):
    return value.isoformat() if isinstance(value, date) else value


def apply_fields(db: Session, opp: Opportunity, body: OppFields, actor: User, creating: bool) -> None:
    data = body.model_dump(exclude_unset=True)
    before = {f: getattr(opp, f) for f in TRACKED} if not creating else {}
    old_owner = opp.owner if not creating else None
    old_participants = {p.id for p in opp.participants} if not creating else set()

    for field in ("title", "customer"):
        if field in data:
            value = (data[field] or "").strip()
            if not value:
                raise HTTPException(422, "제목과 고객사는 필수입니다.")
            setattr(opp, field, value)
    for field in ("biz_type", "win_probability", "expected_period", "proposal_deadline",
                  "submitted_at", "project_start", "project_end", "amount_expected",
                  "contract_amount", "contract_date", "close_reason_code", "review_date"):
        if field in data:
            setattr(opp, field, data[field])
    for field in ("source", "close_reason_text"):
        if field in data:
            setattr(opp, field, (data[field] or "").strip())
    if "overview" in data:
        opp.overview = clean_html(data["overview"])
        opp.overview_text = plain_text(opp.overview)
    if data.get("visibility"):
        opp.visibility = data["visibility"]
    if "competitors" in data:
        opp.competitors = _clean_list(data["competitors"], 20, 100)
    if "partners" in data:
        opp.partners = _clean_list(data["partners"], 20, 100)
    if "links" in data:
        opp.links = [u for u in _clean_list(data["links"], 20, 500)
                     if u.startswith(("http://", "https://"))]
    if "tags" in data:
        opp.tags = [Tag(name=name) for name in _clean_list(data["tags"], 20, 30)]
    if "contacts" in data:
        opp.contacts = [Contact(**c) for c in (data["contacts"] or [])]
    if data.get("owner_id"):
        opp.owner = _active_user(db, data["owner_id"])
        opp.owner_id = opp.owner.id
    if "participant_ids" in data:
        ids = [i for i in dict.fromkeys(data["participant_ids"] or [])]
        opp.participants = [_active_user(db, i) for i in ids]
    opp.participants = [p for p in opp.participants if p.id != opp.owner_id]

    db.flush()
    if not creating:
        for field in TRACKED:
            after = getattr(opp, field)
            if before[field] != after:
                add_system(db, opp, actor, "field_change", {
                    "field": field, "label": FIELD_LABELS[field],
                    "before": _fmt(before[field]), "after": _fmt(after),
                    "sensitive": field in SENSITIVE_FIELDS,
                })
        if old_owner and old_owner.id != opp.owner_id:
            add_system(db, opp, actor, "owner_change", {
                "before": user_brief(old_owner)["name"], "after": user_brief(opp.owner)["name"],
            })
    if creating or (old_owner and old_owner.id != opp.owner_id):
        notify(db, {opp.owner_id}, actor, "assigned", opp,
               f"'{opp.title}'의 담당자로 지정되었습니다.", email=True)
    added = {p.id for p in opp.participants} - old_participants
    notify(db, added, actor, "assigned", opp, f"'{opp.title}'의 참여자로 지정되었습니다.", email=True)


# ---------- 목록·검색 ----------

class ListParams:
    def __init__(self, quick: str = "", stage: str = "", owner: int | None = None,
                 biz_type: str = "", customer: str = "", tag: str = "",
                 date_from: date | None = None, date_to: date | None = None,
                 q: str = "", sort: str = "updated", order: str = "desc"):
        self.quick, self.stage, self.owner, self.biz_type = quick, stage, owner, biz_type
        self.customer, self.tag, self.date_from, self.date_to = customer, tag, date_from, date_to
        self.q, self.sort, self.order = q.strip(), sort, order


def _to_utc(day: date) -> datetime:
    return datetime.combine(day, time.min) - timedelta(hours=9)


def build_query(user: User, p: ListParams):
    O = Opportunity
    query = visible_opps(user)
    if p.stage:
        query = query.where(O.stage_code.in_(p.stage.split(",")))
    elif p.quick == "closed":
        query = query.where(O.stage_code.in_(TERMINAL_STAGES))
    elif not p.q:  # 검색은 종료 건도 함께 찾는다
        query = query.where(O.stage_code.notin_(TERMINAL_STAGES))
    if p.quick == "mine":
        query = query.where(O.owner_id == user.id)
    elif p.quick == "joined":
        query = query.where(O.id.in_(
            select(participants.c.opportunity_id).where(participants.c.user_id == user.id)))
    elif p.quick == "watching":
        query = query.where(O.id.in_(
            select(watchers.c.opportunity_id).where(watchers.c.user_id == user.id)))
    if p.owner:
        query = query.where(O.owner_id == p.owner)
    if p.biz_type:
        query = query.where(O.biz_type == p.biz_type)
    if p.customer:
        query = query.where(O.customer.like(like_pattern(p.customer), escape="!"))
    if p.tag:
        query = query.where(O.id.in_(select(Tag.opportunity_id).where(Tag.name == p.tag)))
    if p.date_from:
        query = query.where(O.updated_at >= _to_utc(p.date_from))
    if p.date_to:
        query = query.where(O.updated_at < _to_utc(p.date_to + timedelta(days=1)))
    if p.q:
        like = like_pattern(p.q)
        query = query.where(or_(
            O.title.like(like, escape="!"),
            O.customer.like(like, escape="!"),
            O.overview_text.like(like, escape="!"),
            O.source.like(like, escape="!"),
            O.id.in_(_activity_match(like)),
            O.id.in_(_comment_match(like)),
        ))
    columns = {
        "updated": O.updated_at, "created": O.created_at, "title": O.title,
        "customer": O.customer, "deadline": O.proposal_deadline,
    }
    if is_admin(user):  # 금액순 정렬은 금액을 볼 수 있는 관리자에게만 허용한다
        columns["amount"] = O.amount_expected
    column = columns.get(p.sort, O.updated_at)
    return query.order_by(column.asc() if p.order == "asc" else column.desc(), O.id.desc())


def _activity_match(like: str):
    return select(Activity.opportunity_id).where(
        Activity.kind == "activity", Activity.deleted_at.is_(None),
        Activity.content_text.like(like, escape="!"))


def _comment_match(like: str):
    return select(Comment.opportunity_id).where(
        Comment.deleted_at.is_(None), Comment.content.like(like, escape="!"))


def _list_extras(db: Session, opps: list[Opportunity], q: str) -> dict[int, dict]:
    """목록에 붙는 다음 할 일, 댓글 수, 검색 일치 위치."""
    ids = [o.id for o in opps]
    extras: dict[int, dict] = {i: {"next_todo": None, "comment_count": 0, "match": []} for i in ids}
    if not ids:
        return extras
    todos = db.scalars(
        select(Todo).where(Todo.opportunity_id.in_(ids), Todo.done.is_(False))
        .order_by(Todo.due_date.is_(None), Todo.due_date, Todo.id)).all()
    for todo in todos:
        if extras[todo.opportunity_id]["next_todo"] is None:
            extras[todo.opportunity_id]["next_todo"] = {
                "content": todo.content, "due_date": d(todo.due_date)}
    for opp_id, count in db.execute(
            select(Comment.opportunity_id, func.count()).where(
                Comment.opportunity_id.in_(ids), Comment.deleted_at.is_(None))
            .group_by(Comment.opportunity_id)):
        extras[opp_id]["comment_count"] = count
    if q:
        like, needle = like_pattern(q), q.lower()
        in_activity = set(db.scalars(_activity_match(like).where(Activity.opportunity_id.in_(ids))))
        in_comment = set(db.scalars(_comment_match(like).where(Comment.opportunity_id.in_(ids))))
        for opp in opps:
            match = extras[opp.id]["match"]
            if needle in opp.title.lower():
                match.append("제목")
            if needle in opp.customer.lower():
                match.append("고객사")
            if needle in (opp.overview_text or "").lower() or needle in (opp.source or "").lower():
                match.append("개요")
            if opp.id in in_activity:
                match.append("기록")
            if opp.id in in_comment:
                match.append("댓글")
    return extras


@router.get("")
def list_opportunities(p: ListParams = Depends(), page: int = 1, size: int = 20,
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    size = max(1, min(size, 500))
    page = max(1, page)
    query = build_query(user, p)
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    opps = db.scalars(query.options(*OPP_LOAD).offset((page - 1) * size).limit(size)).all()
    extras = _list_extras(db, opps, p.q)
    return {
        "items": [{**opp_brief(o, user), **extras[o.id]} for o in opps],
        "total": total, "page": page, "size": size,
    }


@router.get("/export")
def export_excel(request: Request, p: ListParams = Depends(),
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    """현재 필터 결과를 엑셀로 내려받는다 (LST-05). 열람 권한이 없는 금액은 비운다."""
    from openpyxl import Workbook

    opps = db.scalars(build_query(user, p).options(*OPP_LOAD).limit(5000)).all()
    names = {(c.kind, c.code): c.name for c in db.scalars(select(Code))}
    extras = _list_extras(db, opps, "")
    probability = {"high": "상", "mid": "중", "low": "하"}

    book = Workbook()
    sheet = book.active
    sheet.title = "영업기회"
    sheet.append(["번호", "단계", "제목", "고객사", "사업 유형", "예상 금액", "계약 금액", "수주 가능성",
                  "담당자", "참여자", "예상 공고·제안 시기", "제안 마감일", "다음 할 일", "태그",
                  "등록일", "최종 갱신일"])
    for o in opps:
        amount = can_see_amount(o, user)
        todo = extras[o.id]["next_todo"]
        sheet.append([
            o.id, names.get(("stage", o.stage_code), o.stage_code), o.title, o.customer,
            names.get(("biz_type", o.biz_type), o.biz_type or ""),
            o.amount_expected if amount else None, o.contract_amount if amount else None,
            probability.get(o.win_probability or "", ""),
            user_brief(o.owner)["name"], ", ".join(user_brief(u)["name"] for u in o.participants),
            o.expected_period or "", d(o.proposal_deadline) or "",
            f"{todo['content']} ({todo['due_date'] or '기한 없음'})" if todo else "",
            ", ".join(t.name for t in o.tags),
            (o.created_at + timedelta(hours=9)).strftime("%Y-%m-%d"),
            (o.updated_at + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M"),
        ])
    for column, width in zip("ABCDEFGHIJKLMNOP", (8, 12, 40, 24, 16, 16, 16, 12, 12, 24, 18, 14, 36, 24, 12, 18)):
        sheet.column_dimensions[column].width = width
    buffer = io.BytesIO()
    book.save(buffer)
    audit(db, request, user, "export", "opportunities", f"{len(opps)}건")
    db.commit()
    return Response(
        buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="salesnote-{today_kst()}.xlsx"'},
    )


@router.get("/similar")
def similar(customer: str, exclude: int | None = None,
            user: User = Depends(current_user), db: Session = Depends(get_db)):
    """같은 고객사의 진행 중인 기회 (등록 시 중복 안내)."""
    query = visible_opps(user).where(
        Opportunity.customer == customer.strip(),
        Opportunity.stage_code.notin_(TERMINAL_STAGES))
    if exclude:
        query = query.where(Opportunity.id != exclude)
    opps = db.scalars(query.options(*OPP_LOAD).order_by(Opportunity.updated_at.desc()).limit(10)).all()
    return [{"id": o.id, "title": o.title, "stage": o.stage_code, "owner": user_brief(o.owner)}
            for o in opps]


# ---------- 등록·상세·수정·삭제 ----------

@router.post("", status_code=201)
def create(body: OppFields, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not (body.title or "").strip() or not (body.customer or "").strip():
        raise HTTPException(422, "제목과 고객사는 필수입니다.")
    opp = Opportunity(stage_code="explore", owner_id=body.owner_id or user.id,
                      visibility="public", created_by=user.id,
                      competitors=[], partners=[], links=[])
    opp.owner = _active_user(db, opp.owner_id)
    db.add(opp)
    apply_fields(db, opp, body, user, creating=True)
    add_system(db, opp, user, "created")
    db.commit()
    send_chat(db, opp, f"새 영업기회: {opp.title} ({opp.customer}) · 담당 {user_brief(opp.owner)['name']}")
    return {"id": opp.id}


def _attachment_out(a: Attachment, user: User, editor: bool = False) -> dict:
    return {
        "id": a.id, "filename": a.filename, "size": a.size, "activity_id": a.activity_id,
        "uploader": user_brief(a.uploader), "created_at": iso(a.created_at),
        "url": f"/api/attachments/{a.id}",
        "can_delete": editor or a.uploader_id == user.id,
    }


def _comment_out(c: Comment, user: User) -> dict:
    return {
        "id": c.id, "activity_id": c.activity_id, "content": c.content,
        "author": user_brief(c.author), "created_at": iso(c.created_at),
        "can_delete": is_admin(user) or c.author_id == user.id,
    }


def todo_out(t: Todo) -> dict:
    return {"id": t.id, "content": t.content, "due_date": d(t.due_date),
            "assignee": user_brief(t.assignee), "done": t.done, "done_at": iso(t.done_at)}


@router.get("/{opp_id}")
def detail(opp_id: int, request: Request, user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    opp = get_opp(db, opp_id, user)
    amount = can_see_amount(opp, user)
    editor = can_edit(opp, user)

    attachments = db.scalars(select(Attachment).where(Attachment.opportunity_id == opp.id)
                             .order_by(Attachment.id.desc())).all()
    comments = db.scalars(select(Comment).where(
        Comment.opportunity_id == opp.id, Comment.deleted_at.is_(None)).order_by(Comment.id)).all()
    activities = db.scalars(select(Activity).where(
        Activity.opportunity_id == opp.id, Activity.deleted_at.is_(None))
        .order_by(Activity.activity_date.desc(), Activity.id.desc())).all()

    timeline = []
    for a in activities:
        meta = dict(a.meta or {})
        if meta.get("sensitive") and not amount:
            meta.update(before=None, after=None, masked=True)
        timeline.append({
            "id": a.id, "kind": a.kind, "type": a.type_code, "event": a.event,
            "activity_date": d(a.activity_date), "content": a.content, "meta": meta,
            "author": user_brief(a.author), "created_at": iso(a.created_at),
            "edited": a.updated_at is not None,
            "can_edit": a.kind == "activity" and a.author_id == user.id,
            "can_delete": a.kind == "activity" and (a.author_id == user.id or is_admin(user)),
            "attachments": [_attachment_out(x, user, editor) for x in attachments if x.activity_id == a.id],
            "comments": [_comment_out(c, user) for c in comments if c.activity_id == a.id],
        })

    todos = db.scalars(select(Todo).where(Todo.opportunity_id == opp.id)
                       .order_by(Todo.done, Todo.due_date.is_(None), Todo.due_date, Todo.id)).all()
    watching = db.scalar(select(func.count()).select_from(watchers).where(
        watchers.c.opportunity_id == opp.id, watchers.c.user_id == user.id))

    if amount and (opp.amount_expected is not None or opp.contract_amount is not None):
        audit(db, request, user, "view_restricted", f"opportunity:{opp.id}", "금액")
    elif opp.visibility == "private":
        audit(db, request, user, "view_restricted", f"opportunity:{opp.id}", "비공개 기회")
    db.commit()

    return {
        "opp": {**opp_detail(opp, user), "watching": bool(watching)},
        "timeline": timeline,
        "comments": [_comment_out(c, user) for c in comments if c.activity_id is None],
        "todos": [todo_out(t) for t in todos],
        "attachments": [_attachment_out(a, user, editor) for a in attachments],
    }


@router.patch("/{opp_id}")
def update(opp_id: int, body: OppFields, user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    opp = get_opp(db, opp_id, user)
    require(can_edit(opp, user), "담당자 또는 관리자만 수정할 수 있습니다.")
    apply_fields(db, opp, body, user, creating=False)
    touch(opp)
    db.commit()
    return {"id": opp.id}


@router.delete("/{opp_id}")
def remove(opp_id: int, request: Request, user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    """휴지통으로 옮긴다. 30일 뒤 영구 삭제된다 (OPP-04)."""
    opp = get_opp(db, opp_id, user)
    require(can_delete(opp, user), "본인이 등록한 담당 건 또는 관리자만 삭제할 수 있습니다.")
    opp.deleted_at, opp.deleted_by = utcnow(), user.id
    audit(db, request, user, "delete", f"opportunity:{opp.id}", opp.title)
    db.commit()
    return {"ok": True}


# ---------- 단계 변경 (STG-01~04) ----------

class StageFields(BaseModel):
    contacts: list[ContactIn] | None = None
    amount_expected: int | None = Field(None, ge=0)
    expected_period: str | None = None
    submitted_at: date | None = None
    contract_amount: int | None = Field(None, ge=0)
    contract_date: date | None = None
    close_reason_code: str | None = None
    close_reason_text: str | None = Field(None, max_length=2000)
    review_date: date | None = None

    @field_validator("amount_expected", "expected_period", "submitted_at", "contract_amount",
                     "contract_date", "close_reason_code", "review_date", mode="before")
    @classmethod
    def blank_to_none(cls, value):
        return None if isinstance(value, str) and not value.strip() else value


class StageChange(BaseModel):
    stage: str
    reason: str = Field("", max_length=200)
    fields: StageFields | None = None
    direct: bool = False  # 바로 계약(민간)


def missing_fields(opp: Opportunity, stage: str) -> list[str]:
    missing = []
    for field in STAGE_REQUIRED.get(stage, []):
        value = opp.contacts if field == "contacts" else getattr(opp, field)
        if value in (None, "", []):
            missing.append(field)
    return missing


@router.post("/{opp_id}/stage")
def change_stage(opp_id: int, body: StageChange, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    opp = get_opp(db, opp_id, user)
    require(can_edit(opp, user), "담당자 또는 관리자만 단계를 바꿀 수 있습니다.")
    target = db.scalar(select(Code).where(
        Code.kind == "stage", Code.code == body.stage, Code.is_active.is_(True)))
    if not target:
        raise HTTPException(422, "존재하지 않는 단계입니다.")
    if body.stage == opp.stage_code:
        raise HTTPException(422, "이미 해당 단계입니다.")
    if body.direct and (opp.biz_type != "private" or body.stage != "won"):
        raise HTTPException(422, "바로 계약은 사업 유형이 민간인 기회에만 쓸 수 있습니다.")

    if body.fields:
        apply_fields(db, opp, OppFields(**body.fields.model_dump(exclude_unset=True)), user,
                     creating=False)
    missing = missing_fields(opp, body.stage)
    if missing:
        db.rollback()
        raise HTTPException(422, {
            "message": "필수 입력: " + ", ".join(FIELD_LABELS[f] for f in missing),
            "missing": missing,
        })

    before = opp.stage_code
    before_name, after_name = code_name(db, "stage", before), target.name
    opp.stage_code = body.stage
    touch(opp)
    row = add_system(db, opp, user, "stage_change", {
        "from": before, "to": body.stage, "from_name": before_name, "to_name": after_name,
        "reason": body.reason.strip(), "direct": body.direct,
        "reopened": before in TERMINAL_STAGES and body.stage not in TERMINAL_STAGES,
    })
    db.flush()
    label = "바로 계약으로 수주 처리" if body.direct else f"{before_name} → {after_name} 단계 변경"
    notify(db, opp_audience(db, opp), user, "stage", opp,
           f"{user_brief(user)['name']}님이 '{opp.title}'을(를) {label}했습니다.", activity_id=row.id)
    db.commit()
    send_chat(db, opp, f"단계 변경: {opp.title} ({opp.customer}) · {before_name} → {after_name}"
              + (f" · {body.reason.strip()}" if body.reason.strip() else ""))
    return {"id": opp.id, "stage": opp.stage_code}


# ---------- 관심 등록 (CMT-03) ----------

@router.post("/{opp_id}/watch")
def watch(opp_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    opp = get_opp(db, opp_id, user)
    exists = db.scalar(select(func.count()).select_from(watchers).where(
        watchers.c.opportunity_id == opp.id, watchers.c.user_id == user.id))
    if not exists:
        db.execute(insert(watchers).values(opportunity_id=opp.id, user_id=user.id))
        db.commit()
    return {"watching": True}


@router.delete("/{opp_id}/watch")
def unwatch(opp_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    opp = get_opp(db, opp_id, user)
    db.execute(delete(watchers).where(
        watchers.c.opportunity_id == opp.id, watchers.c.user_id == user.id))
    db.commit()
    return {"watching": False}
