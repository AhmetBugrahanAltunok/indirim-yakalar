"""Çalışma zamanı ayarları (anahtar-değer).

`.env` kurulum sabitlerini tutar (DB adresi, konum, WAF bekleme süresi);
bu tablo ise uygulama içinden değiştirilebilen şeyleri tutar:
WhatsApp alıcı numarası, düşüş eşiği, depo listesi tazeleme tarihi.

⚠️ Kişisel veri (telefon numarası) buraya girer, repo'ya girmez.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<Setting {self.key}>"
