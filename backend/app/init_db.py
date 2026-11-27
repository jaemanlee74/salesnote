"""DB 연결 대기, 테이블 생성, 기본 코드·최초 관리자 등록.

컨테이너가 뜰 때 한 번 실행한다:  python -m app.init_db
"""
import logging
import time

from sqlalchemy import select, text

from .config import settings
from .database import SessionLocal, engine
from .models import Base, Code, Setting, User

log = logging.getLogger("salesnote.init")

DEFAULT_CODES = {
    "stage": [
        ("explore", "탐색"), ("contact", "접촉"), ("prepare", "제안 준비"),
        ("proposal", "제안·입찰"), ("negotiate", "협상·평가"),
        ("won", "수주"), ("lost", "실주"), ("hold", "보류"),
    ],
    "biz_type": [
        ("public_bid", "공공 입찰"), ("public_private", "공공 수의계약"), ("private", "민간"),
        ("renewal", "재계약·유지보수"), ("etc", "기타"),
    ],
    "activity_type": [
        ("meeting", "미팅"), ("call", "통화"), ("mail", "메일"),
        ("proposal", "제안·견적"), ("internal", "내부 회의"), ("memo", "메모"),
    ],
    "loss_reason": [
        ("price", "가격"), ("tech", "기술 평가"), ("competitor", "경쟁사 선정"),
        ("cancelled", "사업 취소"), ("withdrawn", "참여 포기"), ("etc", "기타"),
    ],
}
# 동작 규칙이 걸려 있어 삭제할 수 없는 코드
SYSTEM_CODES = {
    "stage": {"explore", "contact", "prepare", "proposal", "negotiate", "won", "lost", "hold"},
    "biz_type": {"private"},
}


def wait_for_db(retries: int = 60, delay: float = 2.0) -> None:
    for attempt in range(1, retries + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("DB 연결 대기 중 (%s/%s): %s", attempt, retries, exc.__class__.__name__)
            time.sleep(delay)
    raise RuntimeError("DB에 연결할 수 없습니다.")


def seed() -> None:
    with SessionLocal() as db:
        for kind, rows in DEFAULT_CODES.items():
            if db.scalar(select(Code.id).where(Code.kind == kind).limit(1)):
                continue
            for order, (code, name) in enumerate(rows, start=1):
                db.add(Code(kind=kind, code=code, name=name, sort_order=order,
                            is_system=code in SYSTEM_CODES.get(kind, set())))
        for email in settings.admin_emails:
            user = db.scalar(select(User).where(User.email == email))
            if not user:
                db.add(User(email=email, name=email.split("@")[0], role="admin"))
        if not db.get(Setting, "job_last_run"):
            db.add(Setting(name="job_last_run", value=""))
        db.commit()


def init() -> None:
    wait_for_db()
    Base.metadata.create_all(engine)
    seed()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init()
    log.info("DB 초기화 완료")
