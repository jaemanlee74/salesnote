"""하루 한 번 도는 작업: 기한·정체 알림(NTF-03), 휴지통·감사 기록 정리."""
import asyncio
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal
from .models import (
    KST,
    TERMINAL_STAGES,
    Activity,
    Attachment,
    AuditLog,
    Comment,
    Contact,
    Notification,
    Opportunity,
    Setting,
    Tag,
    Todo,
    participants,
    today_kst,
    utcnow,
    watchers,
)
from .services import notify

log = logging.getLogger("salesnote.jobs")
RUN_HOUR = 8  # 한국 시간 오전 8시 이후 첫 점검 때 실행


def purge_opportunity(db: Session, opp: Opportunity) -> None:
    """영업기회와 딸린 데이터(고객 담당자 연락처, 첨부파일 포함)를 영구 삭제한다."""
    opp_id = opp.id
    for model in (Comment, Attachment, Todo, Activity, Contact, Tag, Notification):
        db.execute(delete(model).where(model.opportunity_id == opp_id))
    for table in (participants, watchers):
        db.execute(delete(table).where(table.c.opportunity_id == opp_id))
    db.execute(delete(Opportunity).where(Opportunity.id == opp_id))
    db.expunge(opp)
    shutil.rmtree(Path(settings.upload_dir) / str(opp_id), ignore_errors=True)


def run_daily(db: Session) -> dict:
    today = today_kst()
    result = {"due": 0, "stale": 0, "purged": 0}

    # 다음 할 일 기한 하루 전
    todos = db.scalars(select(Todo).where(
        Todo.done.is_(False), Todo.due_date == today + timedelta(days=1))).all()
    for todo in todos:
        opp = db.get(Opportunity, todo.opportunity_id)
        if not opp or opp.deleted_at is not None or opp.stage_code in TERMINAL_STAGES:
            continue
        notify(db, {todo.assignee_id or opp.owner_id}, None, "due", opp,
               f"'{opp.title}'의 할 일 기한이 내일입니다: {todo.content}")
        result["due"] += 1

    # 30일 이상 기록이 없는 기회. 30일째와 그 뒤 7일마다 담당자에게 알린다.
    cutoff = utcnow() - timedelta(days=settings.stale_days)
    stale = db.scalars(select(Opportunity).where(
        Opportunity.deleted_at.is_(None), Opportunity.stage_code.notin_(TERMINAL_STAGES),
        Opportunity.updated_at <= cutoff)).all()
    for opp in stale:
        days = (utcnow() - opp.updated_at).days
        if (days - settings.stale_days) % 7 == 0:
            notify(db, {opp.owner_id}, None, "stale", opp,
                   f"'{opp.title}'에 {days}일 동안 기록이 없습니다.")
            result["stale"] += 1

    # 휴지통 30일 경과분 영구 삭제
    old = db.scalars(select(Opportunity).where(
        Opportunity.deleted_at <= utcnow() - timedelta(days=settings.trash_days))).all()
    for opp in old:
        purge_opportunity(db, opp)
        result["purged"] += 1

    db.execute(delete(AuditLog).where(
        AuditLog.created_at < utcnow() - timedelta(days=settings.audit_keep_days)))
    db.commit()
    return result


def run_if_due() -> None:
    now = datetime.now(KST)
    if now.hour < RUN_HOUR:
        return
    today = now.date().isoformat()
    with SessionLocal() as db:
        # 여러 프로세스가 떠 있어도 하루에 한 번만 돌도록 갱신에 성공한 쪽만 실행한다
        claimed = db.execute(update(Setting).where(
            Setting.name == "job_last_run", Setting.value != today).values(value=today))
        db.commit()
        if claimed.rowcount != 1:
            return
        log.info("일일 작업 결과: %s", run_daily(db))


async def scheduler() -> None:
    while True:
        try:
            await asyncio.to_thread(run_if_due)
        except Exception:  # noqa: BLE001
            log.exception("일일 작업 실패")
        await asyncio.sleep(600)
