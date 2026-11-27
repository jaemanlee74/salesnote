"""환경 변수로 받는 설정."""
import os
from urllib.parse import quote_plus


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    user = os.getenv("MYSQL_USER", "salesnote")
    password = quote_plus(os.getenv("MYSQL_PASSWORD", "salesnote"))
    host = os.getenv("MYSQL_HOST", "db")
    port = os.getenv("MYSQL_PORT", "3306")
    name = os.getenv("MYSQL_DATABASE", "salesnote")
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}?charset=utf8mb4"


class Settings:
    database_url: str = _database_url()
    secret_key: str = os.getenv("SECRET_KEY", "change-me")
    base_url: str = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")

    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    # 최초 관리자. 쉼표로 구분한 구글 계정 메일. 시작할 때 허용 사용자로 등록한다.
    admin_emails: list[str] = [
        e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()
    ]
    # 개발용 로그인(메일만 입력). 운영에서는 반드시 끈다.
    dev_login: bool = _bool("DEV_LOGIN", False)

    cookie_secure: bool = _bool("COOKIE_SECURE", False)
    session_idle_minutes: int = int(os.getenv("SESSION_IDLE_MINUTES", "60"))

    upload_dir: str = os.getenv("UPLOAD_DIR", "/data/uploads")
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_MB", "50")) * 1024 * 1024

    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    mail_from: str = os.getenv("MAIL_FROM", "")

    trash_days: int = 30
    stale_days: int = 30
    audit_keep_days: int = 365

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)


settings = Settings()
