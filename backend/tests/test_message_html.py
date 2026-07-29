"""Tıklanabilir HTML sayfası.

Sayfanın tek işi var: mesajı tek tıkla WhatsApp'a taşımak, taşıyamazsa
kopyalatmak. Bu yüzden testler iki şeyi kovalıyor — bağlantının doğru
kurulduğu, ve **kopyala yolunun her zaman durduğu** (bağlantı uzun mesajda
kesilebilir, o zaman tek çıkış kopyalamaktır).
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database.session import engine
from app.models import (
    Depot,
    Market,
    PriceHistory,
    Product,
    WatchlistItem,
    WatchlistSourceId,
)
from app.services.message_html import html_yaz

ONEK = "HT"
GUN = date.today() + timedelta(days=700)


@pytest.fixture
def db():
    baglanti = engine.connect()
    dis_islem = baglanti.begin()
    oturum = Session(bind=baglanti, join_transaction_mode="create_savepoint")
    try:
        oturum.query(WatchlistItem).update({WatchlistItem.active: False})
        oturum.flush()
        yield oturum
    finally:
        oturum.close()
        dis_islem.rollback()
        baglanti.close()


def _ayar(tmp_path: Path, **degisiklik) -> Settings:
    temel = {"message_dir": str(tmp_path), "whatsapp_recipient": "905550000000"}
    temel.update(degisiklik)
    return get_settings().model_copy(update=temel)


def _kalem_kur(db, etiket: str, spid: str, fiyatlar: dict[str, str]) -> None:
    kalem = WatchlistItem(label=etiket, active=True)
    db.add(kalem)
    db.flush()
    db.add(Product(source_product_id=spid, title=etiket))
    db.flush()
    db.add(WatchlistSourceId(
        watchlist_item_id=kalem.id, source_product_id=spid, link_confirmed_by="test"
    ))
    urun = db.scalar(select(Product).where(Product.source_product_id == spid))

    for slug, fiyat in fiyatlar.items():
        market = db.scalar(select(Market).where(Market.slug == slug))
        if market is None:
            market = Market(slug=slug, name=slug.upper())
            db.add(market)
            db.flush()
        depo_id = f"{ONEK}-{slug}-{spid}"
        if db.get(Depot, depo_id) is None:
            db.add(Depot(id=depo_id, market_id=market.id, name=depo_id, active=True))
            db.flush()
        db.add(PriceHistory(
            product_id=urun.id, depot_id=depo_id, market_id=market.id,
            price=fiyat, collected_date=GUN,
        ))
    db.flush()


@pytest.fixture
def sayfa(db, tmp_path) -> str:
    _kalem_kur(db, "Süt 1 L", f"{ONEK}01", {"a101": "30.00", "bim": "35.00"})
    yol = html_yaz(db, gun=GUN, settings=_ayar(tmp_path))
    assert yol is not None
    return yol.read_text(encoding="utf-8")


# --- temel ---------------------------------------------------------------


def test_dosya_yaziliyor(db, tmp_path) -> None:
    _kalem_kur(db, "Süt 1 L", f"{ONEK}02", {"a101": "30.00", "bim": "35.00"})
    yol = html_yaz(db, gun=GUN, settings=_ayar(tmp_path))
    assert yol.name == f"mesaj-{GUN.isoformat()}.html"


def test_soylenecek_sey_yoksa_yazilmiyor(db, tmp_path) -> None:
    _kalem_kur(db, "Tek market", f"{ONEK}03", {"sok": "42.00"})
    assert html_yaz(db, gun=GUN, settings=_ayar(tmp_path)) is None


def test_disa_baglanti_yok(sayfa) -> None:
    """Yerel dosya: internet olmadan da açılmalı, izleme betiği taşımamalı."""
    assert "http://" not in sayfa
    assert not re.search(r'src=["\']https?://', sayfa)


# --- WhatsApp bağlantısı -------------------------------------------------


def test_whatsapp_protokolu_kullaniliyor(sayfa) -> None:
    """Kurulu masaüstü uygulaması bu protokolü karşılıyor (Store manifest'i)."""
    assert "whatsapp://send?phone=" in sayfa


def test_alici_numarasi_gomulu(sayfa) -> None:
    assert '"905550000000"' in sayfa


def test_alici_yoksa_kisi_secme_ekrani(db, tmp_path) -> None:
    """Numara yoksa bağlantı yine çalışmalı — kişiyi kullanıcı seçer."""
    _kalem_kur(db, "Süt", f"{ONEK}04", {"a101": "30.00", "bim": "35.00"})
    yol = html_yaz(db, gun=GUN, settings=_ayar(tmp_path, whatsapp_recipient=""))
    icerik = yol.read_text(encoding="utf-8")
    assert "whatsapp://send?text=" in icerik


def test_numara_temizleniyor(db, tmp_path) -> None:
    """'+90 555 000 00 00' biçimi de kabul edilmeli."""
    _kalem_kur(db, "Süt", f"{ONEK}05", {"a101": "30.00", "bim": "35.00"})
    yol = html_yaz(
        db, gun=GUN, settings=_ayar(tmp_path, whatsapp_recipient="+90 555 000 00 00")
    )
    assert '"905550000000"' in yol.read_text(encoding="utf-8")


def test_metin_encodeuricomponent_ile_kaciriliyor(sayfa) -> None:
    """Ham metin URL'ye elle gömülseydi emoji ve satır başı bağlantıyı bozardı."""
    assert "encodeURIComponent(metin)" in sayfa


# --- kopyala yolu her zaman durmalı --------------------------------------


def test_kopyala_dugmesi_var(sayfa) -> None:
    """Bağlantı uzun mesajda kesilebilir; kopyala tek güvenilir yol."""
    assert "Panoya Kopyala" in sayfa
    assert "navigator.clipboard.writeText" in sayfa


def test_kesilme_uyarisi_var(sayfa) -> None:
    assert "kesik" in sayfa


def test_tam_metin_sayfada_gomulu(sayfa) -> None:
    """Kopyalama, bağlantıdan bağımsız olarak tam metni vermeli."""
    gomulu = re.search(r"const MESAJLAR = (\[.*?\]);", sayfa, re.S)
    assert gomulu is not None
    mesajlar = json.loads(gomulu.group(1))
    assert mesajlar[0].startswith("🛒")
    assert "Süt 1 L" in mesajlar[0]


def test_emoji_ve_turkce_bozulmamis(sayfa) -> None:
    assert "🛒" in sayfa
    assert "Süt 1 L" in sayfa


def test_json_gomme_bozuk_html_uretmiyor(db, tmp_path) -> None:
    """Etikette tırnak varsa elle string birleştirme sayfayı bozardı."""
    _kalem_kur(db, 'Süt "Tam Yağlı" 1 L', f"{ONEK}06", {"a101": "30.00", "bim": "35.00"})
    yol = html_yaz(db, gun=GUN, settings=_ayar(tmp_path))
    icerik = yol.read_text(encoding="utf-8")

    gomulu = re.search(r"const MESAJLAR = (\[.*?\]);", icerik, re.S)
    assert gomulu is not None
    assert 'Süt "Tam Yağlı" 1 L' in json.loads(gomulu.group(1))[0]


# --- çok sayfa -----------------------------------------------------------


def test_cok_mesajda_ayri_kartlar(db, tmp_path) -> None:
    for i in range(12):
        _kalem_kur(db, f"Ürün {i}", f"{ONEK}1{i:02d}",
                   {"a101": "10.00", "bim": str(20 + i)})

    ayar = _ayar(tmp_path).model_copy(update={"message_item_limit": 10})
    icerik = html_yaz(db, gun=GUN, settings=ayar).read_text(encoding="utf-8")

    gomulu = re.search(r"const MESAJLAR = (\[.*?\]);", icerik, re.S)
    assert len(json.loads(gomulu.group(1))) == 2
    assert "ayrı ayrı gönder" in icerik
