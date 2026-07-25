"""SQLAlchemy 2.x taban sınıfı. Modeller (Faz 1) bundan türer."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Tüm ORM modellerinin ortak tabanı."""
