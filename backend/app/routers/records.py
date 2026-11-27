"""활동 기록, 다음 할 일, 댓글·멘션, 첨부파일 (ACT, CMT)."""
import os
import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..core import can_edit, can_record, current_user, get_opp, is_admin, require, user_brief
from ..database import get_db
from ..models import Activity, Attachment, Code, Comment, Opportunity, Todo, User, today_kst, utcnow
from ..services import (
    add_system,
    clean_html,
    code_name,
    find_mentions,
    notify,
    opp_audience,
    plain_text,
    touch,
)
from .opps import todo_out

router = APIRouter(prefix="/api", tags=["records"])

BLOCKED_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".com", ".scr", ".msi", ".dll", ".sh", ".ps1", ".vbs", ".js",
    ".jar", ".app", ".apk", ".dmg", ".pif", ".cpl", ".hta", ".wsf", ".lnk",
}


def _name(user: User) -> str:
    return user_brief(user)["name"]


# ---------- 활동 기록 ----------

class ActivityIn(BaseModel):
    type: str
    activity_date: date | None = None
    content: str

    @field_validator("activity_date", mode="before")
    @classmethod
    def blank_to_none(cls, value):
        return None if value == "" else value


def _check_activity(db: Session, body: ActivityIn) -> tuple[str, str]:
    known = db.scalar(select(Code.id).where(Code.kind == "activity_type", Code.code == body.type))
    if not known:
        raise HTTPException(422, "활동 유형이 올바르지 않습니다.")
    content = clean_html(body.content)
    text = plain_text(content)
    if not text:
        raise HTTPException(422, "내용을 입력하세요.")
    return content, text


@router.post("/opportunities/{opp_id}/activities", status_code=201)
def create_activity(opp_id: int, body: ActivityIn, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    opp = get_opp(db, opp_id, user)
    require(can_record(opp, user), "담당자와 참여자만 진행 기록을 쓸 수 있습니다.")
    content, text = _check_activity(db, body)
    row = Activity(opportunity_id=opp.id, kind="activity", type_code=body.type,
                   activity_date=body.activity_date or today_kst(), content=content,
                   content_text=text, author_id=user.id)
    db.add(row)
    touch(opp)
    db.flush()
    type_name = code_name(db, "activity_type", body.type)
    mentioned = {u.id for u in find_mentions(db, text)}
    notify(db, mentioned, user, "mention", opp,
           f"{_name(user)}님이 '{opp.title}' 기록에서 회원님을 언급했습니다.",
           activity_id=row.id, email=True)
    notify(db, opp_audience(db, opp) - mentioned, user, "activity", opp,
           f"{_name(user)}님이 '{opp.title}'에 {type_name} 기록을 남겼습니다.", activity_id=row.id)
    db.commit()
    return {"id": row.id}


def _own_activity(db: Session, activity_id: int, user: User, allow_admin: bool) -> tuple[Activity, Opportunity]:
    row = db.get(Activity, activity_id)
    if not row or row.deleted_at is not None or row.kind != "activity":
        raise HTTPException(404, "기록을 찾을 수 없습니다.")
    opp = get_opp(db, row.opportunity_id, user)
    require(row.author_id == user.id or (allow_admin and is_admin(user)),
            "본인이 쓴 기록만 바꿀 수 있습니다.")
    return row, opp


@router.patch("/activities/{activity_id}")
def update_activity(activity_id: int, body: ActivityIn, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    row, _ = _own_activity(db, activity_id, user, allow_admin=False)
    row.content, row.content_text = _check_activity(db, body)
    row.type_code = body.type
    if body.activity_date:
        row.activity_date = body.activity_date
    row.updated_at = utcnow()
    db.commit()
    return {"id": row.id}


@router.delete("/activities/{activity_id}")
def delete_activity(activity_id: int, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    row, _ = _own_activity(db, activity_id, user, allow_admin=True)
    row.deleted_at = utcnow()
    db.commit()
    return {"ok": True}


# ---------- 다음 할 일 ----------

class TodoIn(BaseModel):
    content: str | None = Field(None, max_length=300)
    due_date: date | None = None
    assignee_id: int | None = None
    done: bool | None = None

    @field_validator("due_date", "assignee_id", mode="before")
    @classmethod
    def blank_to_none(cls, value):
        return None if value == "" else value


@router.post("/opportunities/{opp_id}/todos", status_code=201)
def create_todo(opp_id: int, body: TodoIn, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    opp = get_opp(db, opp_id, user)
    require(can_record(opp, user), "담당자와 참여자만 할 일을 등록할 수 있습니다.")
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(422, "할 일 내용을 입력하세요.")
    assignee_id = body.assignee_id or user.id
    if not db.get(User, assignee_id):
        raise HTTPException(422, "지정할 수 없는 사용자입니다.")
    todo = Todo(opportunity_id=opp.id, content=content, due_date=body.due_date,
                assignee_id=assignee_id, created_by=user.id)
    db.add(todo)
    touch(opp)
    notify(db, {assignee_id}, user, "todo", opp,
           f"{_name(user)}님이 '{opp.title}'의 할 일을 맡겼습니다: {content}")
    db.commit()
    return todo_out(todo)


def _todo(db: Session, todo_id: int, user: User) -> tuple[Todo, Opportunity]:
    todo = db.get(Todo, todo_id)
    if not todo:
        raise HTTPException(404, "할 일을 찾을 수 없습니다.")
    opp = get_opp(db, todo.opportunity_id, user)
    require(can_record(opp, user))
    return todo, opp


@router.patch("/todos/{todo_id}")
def update_todo(todo_id: int, body: TodoIn, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    todo, opp = _todo(db, todo_id, user)
    data = body.model_dump(exclude_unset=True)
    if data.get("content"):
        todo.content = data["content"].strip()
    if "due_date" in data:
        todo.due_date = data["due_date"]
    if data.get("assignee_id"):
        todo.assignee_id = data["assignee_id"]
    if "done" in data and data["done"] is not None and data["done"] != todo.done:
        todo.done = data["done"]
        todo.done_at = utcnow() if todo.done else None
        if todo.done:
            add_system(db, opp, user, "todo_done", {"content": todo.content})
    touch(opp)
    db.commit()
    return todo_out(todo)


@router.delete("/todos/{todo_id}")
def delete_todo(todo_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    todo, _ = _todo(db, todo_id, user)
    db.delete(todo)
    db.commit()
    return {"ok": True}


# ---------- 댓글·멘션 ----------

class CommentIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    activity_id: int | None = None


@router.post("/opportunities/{opp_id}/comments", status_code=201)
def create_comment(opp_id: int, body: CommentIn, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    opp = get_opp(db, opp_id, user)  # 열람할 수 있으면 누구나 댓글을 달 수 있다
    content = body.content.strip()
    if not content:
        raise HTTPException(422, "댓글 내용을 입력하세요.")
    activity = None
    if body.activity_id:
        activity = db.get(Activity, body.activity_id)
        if not activity or activity.opportunity_id != opp.id or activity.deleted_at is not None:
            raise HTTPException(404, "기록을 찾을 수 없습니다.")
    mentioned = {u.id for u in find_mentions(db, content)}
    row = Comment(opportunity_id=opp.id, activity_id=body.activity_id, content=content,
                  mentions=sorted(mentioned), author_id=user.id)
    db.add(row)
    db.flush()

    # 담당자, 해당 기록 작성자, 같은 글에 댓글을 단 사용자
    recipients = {opp.owner_id}
    if activity:
        recipients.add(activity.author_id)
    recipients |= set(db.scalars(select(Comment.author_id).where(
        Comment.opportunity_id == opp.id, Comment.activity_id == body.activity_id,
        Comment.deleted_at.is_(None))))
    notify(db, mentioned, user, "mention", opp,
           f"{_name(user)}님이 '{opp.title}' 댓글에서 회원님을 언급했습니다.",
           activity_id=body.activity_id, comment_id=row.id, email=True)
    notify(db, recipients - mentioned, user, "comment", opp,
           f"{_name(user)}님이 '{opp.title}'에 댓글을 남겼습니다.",
           activity_id=body.activity_id, comment_id=row.id)
    db.commit()
    return {"id": row.id}


@router.delete("/comments/{comment_id}")
def delete_comment(comment_id: int, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    row = db.get(Comment, comment_id)
    if not row or row.deleted_at is not None:
        raise HTTPException(404, "댓글을 찾을 수 없습니다.")
    get_opp(db, row.opportunity_id, user)
    require(row.author_id == user.id or is_admin(user), "본인이 쓴 댓글만 지울 수 있습니다.")
    row.deleted_at = utcnow()
    db.commit()
    return {"ok": True}


# ---------- 첨부파일 ----------

def attachment_path(row: Attachment) -> str:
    return os.path.join(settings.upload_dir, str(row.opportunity_id), row.stored_name)


@router.post("/opportunities/{opp_id}/attachments", status_code=201)
def upload(opp_id: int, file: UploadFile = File(...), activity_id: int | None = Form(None),
           user: User = Depends(current_user), db: Session = Depends(get_db)):
    opp = get_opp(db, opp_id, user)
    require(can_record(opp, user), "담당자와 참여자만 파일을 첨부할 수 있습니다.")
    filename = os.path.basename((file.filename or "").replace("\\", "/")).strip()[:255]
    if not filename:
        raise HTTPException(422, "파일 이름이 없습니다.")
    if os.path.splitext(filename)[1].lower() in BLOCKED_EXTENSIONS:
        raise HTTPException(422, "실행 파일은 첨부할 수 없습니다.")
    if activity_id:
        activity = db.get(Activity, activity_id)
        if not activity or activity.opportunity_id != opp.id:
            raise HTTPException(404, "기록을 찾을 수 없습니다.")

    folder = os.path.join(settings.upload_dir, str(opp.id))
    os.makedirs(folder, exist_ok=True)
    stored = uuid.uuid4().hex
    path = os.path.join(folder, stored)
    size = 0
    try:
        with open(path, "wb") as out:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(413, "파일당 50MB까지 첨부할 수 있습니다.")
                out.write(chunk)
    except HTTPException:
        os.remove(path)
        raise
    row = Attachment(opportunity_id=opp.id, activity_id=activity_id, filename=filename,
                     stored_name=stored, size=size, content_type=(file.content_type or "")[:150],
                     uploader_id=user.id)
    db.add(row)
    touch(opp)
    db.commit()
    return {"id": row.id, "filename": row.filename, "size": row.size}


@router.get("/attachments/{attachment_id}")
def download(attachment_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.get(Attachment, attachment_id)
    if not row:
        raise HTTPException(404, "파일을 찾을 수 없습니다.")
    get_opp(db, row.opportunity_id, user)
    path = attachment_path(row)
    if not os.path.exists(path):
        raise HTTPException(404, "파일을 찾을 수 없습니다.")
    # 브라우저가 내용을 해석하지 않도록 항상 내려받게 한다
    return FileResponse(path, filename=row.filename, media_type="application/octet-stream")


@router.delete("/attachments/{attachment_id}")
def delete_attachment(attachment_id: int, user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    row = db.get(Attachment, attachment_id)
    if not row:
        raise HTTPException(404, "파일을 찾을 수 없습니다.")
    opp = get_opp(db, row.opportunity_id, user)
    require(row.uploader_id == user.id or can_edit(opp, user), "올린 사람만 지울 수 있습니다.")
    path = attachment_path(row)
    db.delete(row)
    db.commit()
    if os.path.exists(path):
        os.remove(path)
    return {"ok": True}
