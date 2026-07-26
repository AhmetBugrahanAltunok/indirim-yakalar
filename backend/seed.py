"""Takip listesi başlangıç verisi.

Çalıştırma (backend/ içinden, venv aktifken):
    python seed.py

Idempotent: zaten var olan kalem tekrar açılmaz, tekrar çalıştırmak güvenlidir.

Ürün ID'leri platformun kendi kalıcı kodlarıdır (26.07.2026'da günler arası
kalıcı olduğu doğrulandı). Buradaki değerler `.env`'deki konumun depolarıyla
`/search` üzerinden bulundu — başka bir bölgede bazıları bulunmayabilir.

Her satır = bir takip kalemi = bir fiziksel ürün. Platform aynı ürünü birden
çok katalog kaydında tutabildiği için, kurulumdan sonra
`GET /watchlist/{id}/duplicate-candidates` ile mükerrer kayıtlar taranıp
kullanıcı onayıyla aynı kaleme bağlanır (bkz. SPEC §3.2b).
"""

from __future__ import annotations

import sys

from sqlalchemy import select

from app.database.session import SessionLocal
from app.models import Product, WatchlistItem, WatchlistSourceId
from app.services import watchlist_service as ws

# (kategori, [(platform_id, etiket), ...])
BASLANGIC_LISTESI: list[tuple[str, list[tuple[str, str]]]] = [
    ("Süt 1 L", [
        ("1QKO", "Pınar Süt 1 L"),
        ("0XRT", "Sütaş Tam Yağlı Süt 1 L"),
        ("1T9S", "İçim Süt 1 L"),
    ]),
    ("Ayçiçek yağı 5 L", [
        ("0SAV", "Orkide Ayçiçek Yağı 5 L"),
        ("0R82", "Komili Ayçiçek Yağı 5 L"),
        ("13WJ", "Safya Ayçiçek Yağı 5 L"),
        ("0848", "Sole Ayçiçek Yağı 5 L"),
        ("091M", "Tarım Kredi Anadolu Ayçiçek Yağı 5 L"),
    ]),
    ("Toz şeker 5 kg", [
        ("21HD", "Balküpü Toz Şeker 5 kg"),
        ("1PK8", "Türkşeker Toz Şeker 5 kg"),
        ("0WFK", "Kayseri Şeker Toz Şeker 5 kg"),
        ("0P2B", "Altınküp Toz Şeker 5 kg"),
    ]),
    ("Baldo pirinç 1 kg", [
        ("1Z47", "Reis Gönen Baldo Pirinç 1 kg"),
        ("0YGM", "Duru Baldo Pirinç 1 kg"),
        ("0YS5", "Ovadan Gönen Baldo Pirinç 1 kg"),
        ("0K8J", "Tarım Kredi Anadolu Baldo Pirinç 1 kg"),
    ]),
    ("Makarna 500 g", [
        ("1P8W", "Arbella Burgu Makarna 500 g"),
        ("1Q4D", "Arbella Spagetti Makarna 500 g"),
        ("1ZNR", "Arrighi Linguinette Makarna 500 g"),
        ("10AB", "Bendo Arpa Şehriye 500 g"),
        ("0Z49", "Bendo Tel Şehriye 500 g"),
        ("083Q", "Cardella Fiyonk Makarna 500 g"),
        ("02QY", "Cardella İnce Uzun Makarna 500 g"),
        ("0DYK", "Carrefour Burgu Makarna 500 g"),
        ("05SY", "Carrefour Spagetti Makarna 500 g"),
        ("207R", "Filiz Boncuk Makarna 500 g"),
        ("1YQJ", "Filiz Fiyonk Makarna 500 g"),
        ("1TBA", "Filiz Fırın Makarna 500 g"),
        ("1S7V", "Filiz Kalem Makarna 500 g"),
        ("3WJI", "Granoro Lazanya 500 g"),
        ("1ON5", "Makaroma Caserecce 500 g"),
        ("0M0B", "Migros Spagetti Makarna 500 g"),
        ("20FP", "Mutlu Penne Makarna 500 g"),
        ("0NRW", "Oba Spagetti Makarna 500 g"),
        ("22N4", "Oba Çarliston Makarna 500 g"),
        ("2166", "Pastavilla Dirsek Makarna 500 g"),
        ("1ZOT", "Pastavilla Kelebek Makarna 500 g"),
        ("1RYR", "Pastavilla Midye Makarna 500 g"),
        ("0B11", "Piyale Burgu Makarna 500 g"),
        ("22L5", "Rummo Penne Makarna 500 g"),
    ]),
    ("Çay 1 kg", [
        ("1WHF", "Çaykur Rize Turist Çay 1 kg"),
        ("1YYC", "Çaykur Tiryaki Çay 1 kg"),
        ("1ZZX", "Doğuş Karadeniz Çay 1 kg"),
        ("210G", "Doğuş Tiryaki Çay 1 kg"),
        ("0TQG", "Migros Rize Siyah Çay 1 kg"),
    ]),
    ("Toz çamaşır deterjanı", [
        # 9 kg piyasada yok; en yakın 10 kg + 5 kg alındı.
        ("0W4M", "Bingo Beyaz & Renkli Toz Deterjan 10 kg"),
        ("0Q21", "Tursil Toz Deterjan 10 kg"),
        ("1PH7", "Rinso Limon ve Karbonat Toz Deterjan 10 kg"),
        ("1KCV", "Peros Matik Toz Deterjan 10 kg"),
        ("0HUQ", "Elit Matik Beyazlar Toz Deterjan 5 kg"),
    ]),
    ("Tuvalet kâğıdı 32'li", [
        ("1DQ6", "Selpak Pamuk Katkılı Tuvalet Kâğıdı 32'li"),
        ("0O5P", "Selpak Deluxe Tuvalet Kâğıdı 32'li"),
        ("1WE3", "Carrefour Çift Katlı Tuvalet Kâğıdı 32'li"),
        ("1UOH", "Carrefour Eco Planet Tuvalet Kâğıdı 32'li"),
        ("0U9E", "Logi 3 Katlı Tuvalet Kâğıdı 32'li"),
    ]),
    ("Kâğıt havlu 12'li", [
        # Adet fark etmiyor ama kıyas anlamlı olsun diye tek adette sabitlendi
        # (farklı adet = farklı ürün, fiyatları doğrudan kıyaslanamaz).
        # Proje sahibi 12'li seçti (26.07.2026).
        ("1UPA", "Carrefour Çift Katlı Kâğıt Havlu 12'li"),
        ("1XK8", "Carrefour Eco Planet Kâğıt Havlu 12'li"),
        ("11AW", "Logi 3 Katlı Kâğıt Havlu 12'li"),
        ("119I", "Bambu Aqua 3 Katlı Kâğıt Havlu 12'li"),
        ("19CV", "Bambu Softy 3 Katlı Kâğıt Havlu 12'li"),
    ]),
    ("Un 5 kg", [
        ("0QZ6", "Söke Un 5 kg"),
        ("1NDD", "Sinangil Un 5 kg"),
        ("0XQN", "Piyale Un 5 kg"),
        ("0GDD", "Tarım Kredi Anadolu Un 5 kg"),
    ]),
    ("Beyaz peynir 500 g", [
        ("08HS", "Pınar Süzme Beyaz Peynir 500 g"),
        ("1IS2", "İçim Tam Yağlı Beyaz Peynir 500 g"),
        ("0Z27", "Mis Tam Yağlı Beyaz Peynir 500 g"),
        ("087J", "Torku Beyaz Peynir 500 g"),
        ("1UAA", "Ekici Beyaz Peynir 500 g"),
        ("1OE0", "Bahçıvan Süzme Beyaz Peynir 500 g"),
        ("0H4J", "Tarım Kredi Tam Yağlı Beyaz Peynir 500 g"),
    ]),
    ("Kaşar peyniri 500 g", [
        ("1N24", "Sütaş Kaşar Peyniri 500 g"),
        ("1JMK", "Muratbey Tam Yağlı Taze Kaşar 500 g"),
        ("0YZ6", "Mis Tam Yağlı Kaşar Peyniri 500 g"),
        ("11BZ", "Tarabya Kaşar Peyniri 500 g"),
        ("0GD5", "Carrefour Kaşar Peyniri 500 g"),
    ]),
]


# Aynı fiziksel ürünün ikinci katalog kaydı — proje sahibi onayladı (26.07.2026).
# (ana_id, ek_id, açıklama). Bunlar tek kaleme bağlanır; en ucuz ikisi
# birleştirilerek hesaplanır (bkz. SPEC §3.2b, anayasa md. 7).
MUKERRER_BAGLAR: list[tuple[str, str, str]] = [
    ("1WHF", "1NFN", "Çaykur Rize Turist Çay ≡ ... Siyah Çay"),
    ("1ZZX", "1W39", "Doğuş Karadeniz Çay ≡ ... Siyah Çay"),
    ("210G", "1WZN", "Doğuş Tiryaki Çay ≡ ... Siyah Çay"),
    ("1JMK", "0ZWO", "Muratbey Tam Yağlı Taze Kaşar ≡ Muratbey Kaşar"),
    ("1IS2", "0D0Q", "İçim Tam Yağlı Beyaz Peynir ≡ İçim Beyaz Peynir"),
]


def _mukerrerleri_bagla(db) -> tuple[int, int]:
    baglandi = atlandi = 0
    for ana_id, ek_id, aciklama in MUKERRER_BAGLAR:
        bag = db.scalar(
            select(WatchlistSourceId).where(
                WatchlistSourceId.source_product_id == ana_id
            )
        )
        if bag is None:
            print(f"  ! {ana_id} listede değil, atlandı ({aciklama})")
            atlandi += 1
            continue
        mevcut = db.scalar(
            select(WatchlistSourceId).where(
                WatchlistSourceId.source_product_id == ek_id
            )
        )
        if mevcut is not None:
            print(f"  = {ek_id} zaten bağlı ({aciklama})")
            atlandi += 1
            continue
        if db.scalar(select(Product).where(Product.source_product_id == ek_id)) is None:
            print(f"  ! {ek_id} katalogda yok, önce GET /search ({aciklama})")
            atlandi += 1
            continue
        ws.kaynak_bagla(db, bag.watchlist_item_id, ek_id, onaylayan="user")
        print(f"  + {ana_id} <- {ek_id}  ({aciklama})")
        baglandi += 1
    return baglandi, atlandi


def main() -> int:
    db = SessionLocal()
    eklendi = atlandi = katalogda_yok = 0
    eksik_idler: list[str] = []

    try:
        for kategori, urunler in BASLANGIC_LISTESI:
            print(f"\n{kategori}")
            for spid, etiket in urunler:
                # Zaten bağlıysa dokunma (idempotency).
                mevcut = db.scalar(
                    select(WatchlistSourceId).where(
                        WatchlistSourceId.source_product_id == spid
                    )
                )
                if mevcut is not None:
                    print(f"  = {spid}  {etiket}  (zaten listede)")
                    atlandi += 1
                    continue

                # Katalogda yoksa önce aratılmalı — seed API'ye çıkmaz.
                urun = db.scalar(
                    select(Product).where(Product.source_product_id == spid)
                )
                if urun is None:
                    print(f"  ! {spid}  {etiket}  (KATALOGDA YOK — önce GET /search)")
                    katalogda_yok += 1
                    eksik_idler.append(spid)
                    continue

                ws.kalem_ekle(
                    db,
                    label=etiket,
                    source_product_ids=[spid],
                    note=kategori,
                    onaylayan="seed",
                )
                print(f"  + {spid}  {etiket}")
                eklendi += 1

        print("\nMükerrer katalog kayıtları (onaylı birleştirmeler)")
        baglandi, bag_atlandi = _mukerrerleri_bagla(db)
    finally:
        db.close()

    toplam = db_kalem_sayisi()
    print("\n" + "=" * 60)
    print(f"Eklendi: {eklendi} · Zaten vardı: {atlandi} · Katalogda yok: {katalogda_yok}")
    print(f"Birleştirilen mükerrer kayıt: {baglandi} · atlandı: {bag_atlandi}")
    print(f"Toplam takip kalemi: {toplam}")
    if eksik_idler:
        print("\nKatalogda olmayanlar için önce arama yapın:")
        print("  " + ", ".join(eksik_idler))
    print("\nSonraki adım: mükerrer katalog kayıtlarını tara ->")
    print("  GET /watchlist/{id}/duplicate-candidates")
    return 0


def db_kalem_sayisi() -> int:
    db = SessionLocal()
    try:
        return len(list(db.scalars(select(WatchlistItem.id))))
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
