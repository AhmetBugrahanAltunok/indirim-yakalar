"""Sağlık kontrolü şeması."""

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(description="ok | degraded")
    db: bool = Field(description="Veritabanı bağlantısı gerçekten kuruldu mu")
