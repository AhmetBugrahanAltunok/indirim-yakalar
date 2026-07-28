"""Mesajın dosyaya yazılması.

Amaç tek cümle: dosyayı aç → tümünü seç → kopyala → WhatsApp'a yapıştır.
Bu yüzden testlerin çoğu "dosyada FAZLADAN ne var" sorusunu kovalıyor —
eklenen her satır kullanıcının elle sileceği bir satırdır.
"""

from __future__ import annotations

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
from app.services.message_export import (
    eski_mesajlari_temizle,
    mesaj_dizini,
    mesajlari_yaz,
)

ONEK = "MX"
GUN = date.today() + timedelta(days=600)


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


def _ayar(tmp_path: Path) -> Settings:
    return get_settings().model_copy(update={"message_dir": str(tmp_path)})


def _kalem_kur(db, etiket: str, spid: str, fiyatlar: dict[str, str]) -> None:
    """fiyatlar: {market_slug: fiyat}"""
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


# --- yazım ---------------------------------------------------------------


def test_mesaj_dosyaya_yaziliyor(db, tmp_path) -> None:
    _kalem_kur(db, "Süt 1 L", f"{ONEK}01", {"a101": "30.00", "bim": "35.00"})
    yollar = mesajlari_yaz(db, gun=GUN, settings=_ayar(tmp_path))

    assert len(yollar) == 1
    assert yollar[0].name == f"mesaj-{GUN.isoformat()}.txt"
    assert "Süt 1 L" in yollar[0].read_text(encoding="utf-8")


def test_dosyada_fazladan_satir_yok(db, tmp_path) -> None:
    """"Tümünü seç"in doğrudan çalışması gerekiyor — başlık/açıklama eklenmez."""
    _kalem_kur(db, "Süt 1 L", f"{ONEK}02", {"a101": "30.00", "bim": "35.00"})
    yol = mesajlari_yaz(db, gun=GUN, settings=_ayar(tmp_path))[0]

    icerik = yol.read_text(encoding="utf-8")
    assert icerik.startswith("🛒")
    assert icerik == icerik.strip(), "başta/sonda boşluk kalmamalı"
    assert "Dosya" not in icerik
    assert "kopyala" not in icerik.lower()


def test_utf8_yaziliyor(db, tmp_path) -> None:
    """Emoji ve Türkçe karakter bozulmadan gitmeli."""
    _kalem_kur(db, "Çaykur Rize Turist Çay", f"{ONEK}03",
               {"a101": "365.00", "bim": "399.95"})
    yol = mesajlari_yaz(db, gun=GUN, settings=_ayar(tmp_path))[0]

    ham = yol.read_bytes()
    assert "🛒".encode() in ham
    assert "Çaykur Rize Turist Çay".encode() in ham


def test_dizin_yoksa_olusturuluyor(db, tmp_path) -> None:
    _kalem_kur(db, "Süt", f"{ONEK}04", {"a101": "30.00", "bim": "35.00"})
    dizin = tmp_path / "henuz" / "yok"
    mesajlari_yaz(db, gun=GUN, settings=get_settings().model_copy(
        update={"message_dir": str(dizin)}))
    assert dizin.exists()


# --- sayfalama -----------------------------------------------------------


def test_cok_sayfada_ayri_dosyalar(db, tmp_path) -> None:
    """Tek dosyada birleştirmek 10 ürün sınırını anlamsız kılardı (SPEC §7)."""
    for i in range(12):
        _kalem_kur(db, f"Ürün {i}", f"{ONEK}1{i:02d}",
                   {"a101": "10.00", "bim": str(20 + i)})

    yollar = mesajlari_yaz(db, gun=GUN, settings=_ayar(tmp_path))
    assert len(yollar) == 2
    assert [y.name for y in yollar] == [
        f"mesaj-{GUN.isoformat()}-1.txt",
        f"mesaj-{GUN.isoformat()}-2.txt",
    ]


def test_tek_sayfada_numara_eki_yok(db, tmp_path) -> None:
    _kalem_kur(db, "Süt", f"{ONEK}05", {"a101": "30.00", "bim": "35.00"})
    yol = mesajlari_yaz(db, gun=GUN, settings=_ayar(tmp_path))[0]
    assert "-1.txt" not in yol.name


def test_onceki_kosunun_fazla_sayfalari_siliniyor(db, tmp_path) -> None:
    """Dünkü 3. sayfa, bugün 1 sayfa üretilince ortada kalmamalı."""
    ayar = _ayar(tmp_path)
    artik = tmp_path / f"mesaj-{GUN.isoformat()}-3.txt"
    artik.write_text("eski sayfa", encoding="utf-8")

    _kalem_kur(db, "Süt", f"{ONEK}06", {"a101": "30.00", "bim": "35.00"})
    mesajlari_yaz(db, gun=GUN, settings=ayar)

    assert not artik.exists()
    assert len(list(tmp_path.glob("mesaj-*.txt"))) == 1


# --- söylenecek bir şey yoksa -------------------------------------------


def test_paylasilacak_sey_yoksa_dosya_yazilmiyor(db, tmp_path) -> None:
    """Boş dosya bırakmak, kullanıcıyı boşuna açmaya iterdi."""
    _kalem_kur(db, "Tek market", f"{ONEK}07", {"sok": "42.00"})
    assert mesajlari_yaz(db, gun=GUN, settings=_ayar(tmp_path)) == []
    assert list(tmp_path.glob("*.txt")) == []


def test_hic_veri_yoksa_patlamiyor(db, tmp_path) -> None:
    assert mesajlari_yaz(db, gun=GUN, settings=_ayar(tmp_path)) == []


# --- klasör seçimi -------------------------------------------------------


def test_message_dir_bossa_yedek_klasorune_yazilir() -> None:
    ayar = get_settings().model_copy(update={
        "message_dir": "", "backup_dir": r"C:\ornek\yedek",
    })
    assert mesaj_dizini(ayar) == Path(r"C:\ornek\yedek")


def test_message_dir_verilmisse_o_kullanilir(tmp_path) -> None:
    ayar = get_settings().model_copy(update={"message_dir": str(tmp_path)})
    assert mesaj_dizini(ayar) == tmp_path


# --- saklama süresi ------------------------------------------------------


def test_eski_mesajlar_siliniyor(tmp_path) -> None:
    ayar = get_settings().model_copy(update={
        "message_dir": str(tmp_path), "backup_retention_days": 30,
    })
    bugun = date(2026, 7, 29)
    eski = tmp_path / "mesaj-2026-01-01.txt"
    yeni = tmp_path / "mesaj-2026-07-28.txt"
    sayfali = tmp_path / "mesaj-2026-01-02-2.txt"
    for d in (eski, yeni, sayfali):
        d.write_text("x", encoding="utf-8")

    silinen = eski_mesajlari_temizle(ayar, gun=bugun)

    assert set(silinen) == {eski, sayfali}, "sayfa ekli dosya da temizlenmeli"
    assert yeni.exists()


def test_tanimadigimiz_dosyaya_dokunulmuyor(tmp_path) -> None:
    ayar = get_settings().model_copy(update={
        "message_dir": str(tmp_path), "backup_retention_days": 1,
    })
    yabanci = tmp_path / "mesaj-notlarim.txt"
    yabanci.write_text("dokunma", encoding="utf-8")

    eski_mesajlari_temizle(ayar, gun=date(2026, 7, 29))
    assert yabanci.exists()
