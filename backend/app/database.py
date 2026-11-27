from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import settings

_kwargs: dict = {"pool_pre_ping": True}
if settings.database_url.startswith("sqlite"):
    _kwargs["connect_args"] = {"check_same_thread": False}
else:
    _kwargs.update(pool_recycle=3600, pool_size=10, max_overflow=20)

engine = create_engine(settings.database_url, **_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
