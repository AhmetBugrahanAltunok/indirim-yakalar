"""Karşılaştırma, fiyat geçmişi ve mesaj şemaları (Faz 2).

Para alanları `Decimal` — JSON'a metin olarak değil sayı olarak çıkar ama
Python tarafında hiçbir noktada float'a düşmez (anayasa md. 1).
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class MarketFiyatiOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    ad: str
    fiyat: Decimal = Field(description="Zincirin en ucuz şubesinin fiyatı")
    depo_sayisi: int = Field(
        description="O gün fiyatı bilinen depo sayısı — hepsi bu fiyatta demek değil"
    )


class DususOut(BaseModel):
    onceki_gun: date
    onceki_fiyat: Decimal
    son_gun: date
    son_fiyat: Decimal
    onceki_market: str
    son_market: str
    fark: Decimal = Field(description="Pozitif = ucuzladı")
    yuzde: Decimal
    dustu_mu: bool
    market_degisti_mi: bool = Field(
        description=(
            "En ucuz zincir değiştiyse düşüş 'aynı markette indirim' değildir; "
            "daha ucuz bir market listeye girmiş olabilir."
        )
    )


class KarsilastirmaOut(BaseModel):
    kalem_id: int
    etiket: str
    son_gun: date = Field(description="Fiyatların ait olduğu gözlem günü")
    marketler: list[MarketFiyatiOut]
    market_sayisi: int
    en_ucuz_denebilir_mi: bool = Field(
        description=(
            "False ise 'en ucuz' iddiası edilmez: ya tek market biliniyor ya da "
            "tüm marketler aynı fiyatta (anayasa md. 7)."
        )
    )
    beraberlik_var_mi: bool
    en_pahali_fark: Decimal | None = Field(
        description="En ucuz ile en pahalı arası fark; kıyas yoksa null"
    )
    dusus: DususOut | None


class FiyatGecmisiNoktasi(BaseModel):
    gun: date
    slug: str
    market: str
    fiyat: Decimal


class FiyatGecmisiOut(BaseModel):
    kalem_id: int
    etiket: str
    gozlem_gunu_sayisi: int
    noktalar: list[FiyatGecmisiNoktasi]


class BayatKalemOut(BaseModel):
    kalem_id: int
    etiket: str
    son_veri: date | None = Field(description="Son fiyat gözlemi; hiç yoksa null")
    gun_farki: int | None = Field(
        description="Son gözlem gününe göre kaç gün geride; hiç verisi yoksa null"
    )
    bagli_id_sayisi: int = Field(
        description=(
            "Kaleme bağlı platform ID sayısı. Birden fazlaysa biri düşse de "
            "fiyat akmaya devam edebilir."
        )
    )
    hic_veri_yok: bool


class MesajOut(BaseModel):
    metin: str
    sayfa: int
    toplam_sayfa: int
    kalem_sayisi: int


class MesajYanit(BaseModel):
    mesajlar: list[MesajOut]
    aciklama: str = Field(
        description="Mesaj üretilmediyse nedenini açıklar — boş liste sessiz kalmaz"
    )
