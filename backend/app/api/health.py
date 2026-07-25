"""Sağlık kontrolü — DB bağlantısını gerçekten dener."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.schemas.health import HealthResponse

router = APIRouter(tags=["sistem"])


@router.get("/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)) -> HealthResponse:
    """`db` alanı gerçek bir sorguyla doğrulanır, varsayılmaz."""
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except SQLAlchemyError:
        db_ok = False
    return HealthResponse(status="ok" if db_ok else "degraded", db=db_ok)
