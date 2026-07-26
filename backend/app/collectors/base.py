"""Collector arayüzü.

Her veri kaynağı bir adaptördür. Sorumluluğu tek: kaynaktan ham veriyi alıp
`raw_records`'a DEĞİŞTİRMEDEN yazmak (anayasa md. 3). Normalize/analiz sonraki
katmanların işi — böylece bir ayrıştırma hatası bulunduğunda kaynağı tekrar
yormadan geçmiş veriden yeniden üretilebilir.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from sqlalchemy.orm import Session


@dataclass
class ToplamaSonucu:
    """Bir toplama koşusunun özeti."""

    kaynak: str
    istenen: int = 0
    basarili: int = 0
    bos_donen: int = 0
    hatali: int = 0
    durduruldu: bool = False
    durma_nedeni: str | None = None
    hatalar: list[str] = field(default_factory=list)

    def ozet(self) -> str:
        satir = (
            f"{self.kaynak}: {self.basarili}/{self.istenen} kayıt alındı "
            f"({self.bos_donen} boş, {self.hatali} hata)"
        )
        if self.durduruldu:
            satir += f" — DURDURULDU: {self.durma_nedeni}"
        return satir


class BaseCollector(ABC):
    """Tüm collector'ların ortak arayüzü."""

    kaynak: str

    @abstractmethod
    def topla(self, db: Session) -> ToplamaSonucu:
        """Kaynaktan ham veriyi çeker ve `raw_records`'a yazar."""
        raise NotImplementedError
