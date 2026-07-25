"""Veritabanı motoru ve oturum üretimi."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_settings = get_settings()

engine = create_engine(
    _settings.database_url,
    pool_pre_ping=True,  # kopan bağlantıyı sessizce yenile
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI bağımlılığı: istek başına bir oturum."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
