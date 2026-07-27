"""Felaket kurtarma: veritabanını yeniden ayağa kaldırır.

27.07.2026'da Docker Desktop'ın `pgdata` volume'ü ikinci kez yok oldu. O gün
kurtarma adımları elle bulunmuştu; bir daha aranmasın diye buraya alındı
(bkz. [[Gotchas]]).

İki yol var ve **yedekten yükleme her zaman tercih edilir** — sıfırdan kurulum
şemayı ve takip listesini geri getirir ama FİYAT GEÇMİŞİNİ GETİREMEZ. Platform
yalnız güncel fiyatı döndürüyor, kaçan gün kalıcı olarak kayıptır.

    python restore.py --yedekten            # en yeni dump'tan (önerilen)
    python restore.py --yedekten --dosya X  # belirli bir dump'tan
    python restore.py --sifirdan            # yedek yoksa son çare

Öncesinde şema kurulmuş olmalı:  python -m alembic upgrade head
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from app.config import get_settings
from app.database.session import SessionLocal
from app.models import Product, WatchlistItem
from app.services.backup import YedekHatasi, en_yeni_yedek, geri_yukle
from app.services.depot_resolver import depolari_coz

from seed import BASLANGIC_LISTESI, MUKERRER_BAGLAR


def _taslak_hedefleri() -> list[tuple[str, str]]:
    """(source_product_id, etiket) — takip listesi + onaylı mükerrer kayıtlar."""
    ciftler: list[tuple[str, str]] = []
    for _kategori, urunler in BASLANGIC_LISTESI:
        ciftler.extend(urunler)
    for _ana, ek, aciklama in MUKERRER_BAGLAR:
        ciftler.append((ek, aciklama))
    return ciftler


def urun_taslaklarini_yaz() -> tuple[int, int]:
    """Katalogda olmayan takip ID'leri için iskelet `products` satırı açar.

    `seed.py` API'ye çıkmaz: takip kalemi açmak için ürünün `products`'ta
    olmasını bekler (FK). Boş katalogda seed hiçbir kalem açamazdı.

    Yalnız ID + etiket yazılır. Marka, gramaj, görsel gibi alanlar ilk pipeline
    koşusunda `price_ingest._urun_guncelle` tarafından platform yanıtından
    doldurulur — fazladan API çağrısı yapılmaz, uydurma veri kalmaz
    (anayasa md. 11).
    """
    db = SessionLocal()
    eklendi = vardi = 0
    try:
        for spid, etiket in _taslak_hedefleri():
            mevcut = db.scalar(
                select(Product).where(Product.source_product_id == spid)
            )
            if mevcut is not None:
                vardi += 1
                continue
            db.add(Product(source_product_id=spid, title=etiket))
            eklendi += 1
        db.commit()
    finally:
        db.close()
    return eklendi, vardi


def _sifirdan(atla_depo: bool) -> int:
    print("Sıfırdan kurulum — fiyat geçmişi GERİ GELMEYECEK.\n")

    if atla_depo:
        print("1/3 Depo çözümlemesi atlandı (--depolarsiz).")
    else:
        print("1/3 Depolar çözümleniyor (konum ayarı — anayasa md. 13)...")
        db = SessionLocal()
        try:
            sonuc = depolari_coz(db)
        finally:
            db.close()
        print(f"    {sonuc}")

    print("2/3 Ürün taslakları yazılıyor...")
    eklendi, vardi = urun_taslaklarini_yaz()
    print(f"    eklendi: {eklendi} · zaten vardı: {vardi}")

    print("3/3 Takip listesi kuruluyor (seed.py)...")
    import seed

    seed.main()

    print("\nSonraki adım — ilk toplama:")
    print("    python gunluk_kosu.py")
    return 0


def _yedekten(dosya: str | None) -> int:
    settings = get_settings()
    kaynak = None

    if dosya:
        from pathlib import Path

        kaynak = Path(dosya).expanduser()
    else:
        kaynak = en_yeni_yedek(settings)

    if kaynak is None:
        print(f"Yedek bulunamadı: {settings.backup_dir}")
        print("Yedek yoksa sıfırdan kurulabilir:  python restore.py --sifirdan")
        return 1

    print(f"Geri yüklenecek: {kaynak}")
    print("UYARI: mevcut tablolar düşürülüp yedekteki hâlleriyle değiştirilecek.\n")

    try:
        geri_yukle(kaynak, settings)
    except YedekHatasi as hata:
        print(f"BAŞARISIZ: {hata}")
        return 1

    db = SessionLocal()
    try:
        kalem = len(list(db.scalars(select(WatchlistItem.id))))
        urun = len(list(db.scalars(select(Product.id))))
    finally:
        db.close()

    print(f"Geri yüklendi — {kalem} takip kalemi, {urun} ürün.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ayristirici = argparse.ArgumentParser(description="Veritabanı kurtarma")
    grup = ayristirici.add_mutually_exclusive_group(required=True)
    grup.add_argument(
        "--yedekten", action="store_true", help="Dump dosyasından geri yükle (önerilen)"
    )
    grup.add_argument(
        "--sifirdan",
        action="store_true",
        help="Yedek yokken şema + takip listesini yeniden kur (fiyat geçmişi gelmez)",
    )
    ayristirici.add_argument("--dosya", help="Belirli bir dump dosyası")
    ayristirici.add_argument(
        "--depolarsiz",
        action="store_true",
        help="Sıfırdan kurulumda depo çözümlemesini atla (API'ye çıkmaz)",
    )
    args = ayristirici.parse_args(argv)

    if args.yedekten:
        return _yedekten(args.dosya)
    return _sifirdan(args.depolarsiz)


if __name__ == "__main__":
    sys.exit(main())
