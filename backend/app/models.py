"""데이터 모델. 기능명세서 6장 기준."""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

KST = ZoneInfo("Asia/Seoul")
LongText = Text().with_variant(LONGTEXT(), "mysql")

TERMINAL_STAGES = ("won", "lost", "hold")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def today_kst() -> date:
    return datetime.now(KST).date()


class Base(DeclarativeBase):
    pass


participants = Table(
    "opportunity_participants",
    Base.metadata,
    Column("opportunity_id", ForeignKey("opportunities.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)

watchers = Table(
    "opportunity_watchers",
    Base.metadata,
    Column("opportunity_id", ForeignKey("opportunities.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(100), default="")
    title: Mapped[str] = mapped_column(String(50), default="")  # 직급
    role: Mapped[str] = mapped_column(String(20), default="member")  # admin | member
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    picture: Mapped[str] = mapped_column(String(500), default="")
    notify_email: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Code(Base):
    """관리자가 관리하는 코드: stage, biz_type, activity_type, loss_reason."""

    __tablename__ = "codes"
    __table_args__ = (UniqueConstraint("kind", "code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))
    code: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)  # 동작 규칙이 걸린 코드. 삭제 불가


class Setting(Base):
    __tablename__ = "settings"

    name: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class Opportunity(Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        Index("ix_opp_list", "deleted_at", "stage_code", "updated_at"),
        Index("ix_opp_customer", "customer"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(100))
    customer: Mapped[str] = mapped_column(String(100))
    stage_code: Mapped[str] = mapped_column(String(50), default="explore")
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    biz_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    overview: Mapped[str] = mapped_column(LongText, default="")
    overview_text: Mapped[str] = mapped_column(LongText, default="")  # 검색용 일반 텍스트
    source: Mapped[str] = mapped_column(String(100), default="")
    amount_expected: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    win_probability: Mapped[str | None] = mapped_column(String(10), nullable=True)  # high|mid|low
    expected_period: Mapped[str | None] = mapped_column(String(10), nullable=True)  # YYYY-MM 또는 YYYY-MM-DD
    proposal_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    submitted_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    project_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    project_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    competitors: Mapped[list] = mapped_column(JSON, default=list)
    partners: Mapped[list] = mapped_column(JSON, default=list)
    links: Mapped[list] = mapped_column(JSON, default=list)
    visibility: Mapped[str] = mapped_column(String(10), default="public")  # public | private
    contract_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    contract_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    close_reason_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    close_reason_text: Mapped[str] = mapped_column(Text, default="")
    review_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    owner: Mapped[User] = relationship(foreign_keys=[owner_id])
    participants: Mapped[list[User]] = relationship(secondary=participants)
    contacts: Mapped[list["Contact"]] = relationship(
        cascade="all, delete-orphan", order_by="Contact.id"
    )
    tags: Mapped[list["Tag"]] = relationship(cascade="all, delete-orphan", order_by="Tag.id")


class Contact(Base):
    """고객 담당자."""

    __tablename__ = "opportunity_contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(50))
    position: Mapped[str] = mapped_column(String(100), default="")  # 부서·직책
    phone: Mapped[str] = mapped_column(String(50), default="")
    email: Mapped[str] = mapped_column(String(255), default="")


class Tag(Base):
    __tablename__ = "opportunity_tags"
    __table_args__ = (Index("ix_tag_name", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(30))


class Activity(Base):
    """타임라인 한 줄. kind=activity는 사용자가 쓴 기록, kind=system은 시스템 기록."""

    __tablename__ = "activities"
    __table_args__ = (Index("ix_activity_opp", "opportunity_id", "activity_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(10), default="activity")
    type_code: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 활동 유형
    event: Mapped[str | None] = mapped_column(String(30), nullable=True)  # 시스템 기록 종류
    activity_date: Mapped[date] = mapped_column(Date, default=today_kst)
    content: Mapped[str] = mapped_column(LongText, default="")
    content_text: Mapped[str] = mapped_column(LongText, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    author: Mapped[User] = relationship()


class Todo(Base):
    __tablename__ = "todos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    content: Mapped[str] = mapped_column(String(300))
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    done_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id])


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    activity_id: Mapped[int | None] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE"), nullable=True
    )
    content: Mapped[str] = mapped_column(Text)
    mentions: Mapped[list] = mapped_column(JSON, default=list)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    author: Mapped[User] = relationship()


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    activity_id: Mapped[int | None] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    content_type: Mapped[str] = mapped_column(String(150), default="")
    uploader_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    uploader: Mapped[User] = relationship()


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notification_user", "user_id", "is_read", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(String(500))
    opportunity_id: Mapped[int | None] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=True
    )
    activity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    """감사 기록: 로그인, 열람 제한 항목 조회, 삭제, 엑셀 내보내기."""

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_email: Mapped[str] = mapped_column(String(255), default="")
    action: Mapped[str] = mapped_column(String(40))
    target: Mapped[str] = mapped_column(String(100), default="")
    detail: Mapped[str] = mapped_column(String(500), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
