"""WhatsApp mesajı testleri (SPEC §7).

Veritabanına çıkmıyor: `KalemAnalizi` donmuş bir veri yapısı, doğrudan kurulur.
Böylece burada yalnız METİN kuralları sınanır — en ucuz hesabının kendisi
`test_analyzer.py`'nin işi.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.config import get_settings
from app.services.analyzer import DususBilgisi, KalemAnalizi, MarketFiyati
from app.services.message_builder import whatsapp_mesajlari

BUGUN = date(2026, 7, 28)
DUN = BUGUN - timedelta(days=1)
AYAR = get_settings().model_copy(update={"price_drop_threshold_pct": Decimal("5.0")})


def _market(ad: str, fiyat: str, market_id: int = 0) -> MarketFiyati:
    return MarketFiyati(
        market_id=market_id or abs(hash(ad)) % 10_000,
        slug=ad.lower(),
        ad=ad,
        fiyat=Decimal(fiyat),
        depo_sayisi=1,
    )


def _kalem(
    etiket: str,
    marketler: list[MarketFiyati],
    *,
    dusus: DususBilgisi | None = None,
    son_gun: date = BUGUN,
    kalem_id: int = 1,
) -> KalemAnalizi:
    return KalemAnalizi(
        kalem_id=kalem_id,
        etiket=etiket,
        son_gun=son_gun,
        market_fiyatlari=sorted(marketler, key=lambda m: (m.fiyat, m.slug)),
        dusus=dusus,
    )


def _tek_metin(analizler, **kw) -> str:
    mesajlar = whatsapp_mesajlari(analizler, gun=BUGUN, settings=AYAR, **kw)
    assert len(mesajlar) == 1
    return mesajlar[0].metin


# --- temel biçim ---------------------------------------------------------


def test_baslik_ve_tarih_var() -> None:
    metin = _tek_metin([_kalem("Süt 1 L", [_market("A101", "30"), _market("BİM", "35")])])
    assert "🛒" in metin
    assert "📅 28.07.2026" in metin


def test_en_ucuz_kalin_yazilir() -> None:
    metin = _tek_metin([_kalem("Süt 1 L", [_market("A101", "30"), _market("BİM", "35")])])
    assert "✅ En uygun: *A101 — 30,00 TL*" in metin


def test_fiyatlar_ucuzdan_pahaliya_siralanir() -> None:
    metin = _tek_metin([_kalem("Süt 1 L", [
        _market("Migros", "40"), _market("A101", "30"), _market("BİM", "35"),
    ])])
    satirlar = [s for s in metin.splitlines() if "TL" in s]
    assert satirlar[0].startswith("✅")
    assert "BİM: 35,00 TL" == satirlar[1]
    assert "Migros: 40,00 TL" == satirlar[2]


def test_para_virgullu_yazilir() -> None:
    metin = _tek_metin([_kalem("Süt", [_market("A101", "59.5"), _market("BİM", "70")])])
    assert "59,50 TL" in metin
    assert "59.50" not in metin


# --- anayasa md. 7: kıyas yoksa "en ucuz" denmez -------------------------


def test_beraberlikte_tum_marketler_yazilir() -> None:
    """27.07.2026: Çaykur Rize Turist A101/BİM/ŞOK'ta aynı anda 365,00."""
    metin = _tek_metin([_kalem("Çay 1 kg", [
        _market("A101", "365"), _market("BİM", "365"),
        _market("ŞOK", "365"), _market("Migros", "399.95"),
    ])])
    assert "✅ En uygun: *A101 / BİM / ŞOK — 365,00 TL*" in metin


def test_hepsi_ayni_fiyatsa_en_ucuz_denmiyor() -> None:
    metin = _tek_metin([_kalem("Çay 1 kg", [
        _market("A101", "365"), _market("BİM", "365"),
    ], dusus=DususBilgisi(
        onceki_gun=DUN, onceki_fiyat=Decimal("400"),
        son_gun=BUGUN, son_fiyat=Decimal("365"),
        onceki_market="A101", son_market="A101",
    ))])
    assert "En uygun" not in metin
    assert "ℹ️ Tüm marketlerde aynı: *365,00 TL*" in metin


def test_tek_market_dususle_birlikte_yalnizca_diye_yazilir() -> None:
    metin = _tek_metin([_kalem("Tuz", [_market("ŞOK", "42")], dusus=DususBilgisi(
        onceki_gun=DUN, onceki_fiyat=Decimal("50"),
        son_gun=BUGUN, son_fiyat=Decimal("42"),
        onceki_market="ŞOK", son_market="ŞOK",
    ))])
    assert "ℹ️ Yalnızca ŞOK: *42,00 TL*" in metin
    assert "En uygun" not in metin


def test_tek_market_ve_dusus_yoksa_mesaja_girmez() -> None:
    """Ortada söylenecek bir şey yok — mesajı şişirmez."""
    assert whatsapp_mesajlari(
        [_kalem("Tuz", [_market("ŞOK", "42")])], gun=BUGUN, settings=AYAR
    ) == []


def test_fark_yoksa_ve_dusus_yoksa_mesaja_girmez() -> None:
    assert whatsapp_mesajlari(
        [_kalem("Çay", [_market("A101", "365"), _market("BİM", "365")])],
        gun=BUGUN, settings=AYAR,
    ) == []


# --- düşüş satırı --------------------------------------------------------


def _dusen(**kw) -> KalemAnalizi:
    varsayilan = dict(
        onceki_gun=DUN, onceki_fiyat=Decimal("70"),
        son_gun=BUGUN, son_fiyat=Decimal("59.50"),
        onceki_market="ŞOK", son_market="ŞOK",
    )
    varsayilan.update(kw)
    return _kalem(
        "Red Bull 250 ml",
        [_market("ŞOK", "59.50"), _market("Migros", "60.90")],
        dusus=DususBilgisi(**varsayilan),  # type: ignore[arg-type]
    )


def test_dun_bugun_gercekten_oyleyse_yazilir() -> None:
    metin = _tek_metin([_dusen()])
    assert "🔻 Düştü (%15): dün 70,00 TL → bugün 59,50 TL" in metin


def test_gun_boslugunda_gercek_tarihler_yazilir() -> None:
    """Makine kapalıyken gün atlandıysa "dün" yazmak yalan olur (SPEC §6.3)."""
    eski = BUGUN - timedelta(days=13)
    metin = _tek_metin([_dusen(onceki_gun=eski)])
    assert "dün" not in metin
    assert "15.07.2026 70,00 TL → 28.07.2026 59,50 TL" in metin


def test_iki_gun_ayni_bicimde_yazilir() -> None:
    """29.07'de 27.07→28.07 düşüşü "27.07.2026 ... → dün ..." diye çıkıyordu.

    Doğruydu ama bir ucu tarih bir ucu göreli olunca okuyan kıyaslayamıyordu.
    """
    onceki = BUGUN - timedelta(days=2)
    son = BUGUN - timedelta(days=1)
    metin = _tek_metin([_dusen(onceki_gun=onceki, son_gun=son)])
    assert "dün" not in metin
    assert "26.07.2026 70,00 TL → 27.07.2026 59,50 TL" in metin


def test_ikisi_de_goreliyse_goreli_kalir() -> None:
    metin = _tek_metin([_dusen()])
    assert "dün 70,00 TL → bugün 59,50 TL" in metin


def test_market_degistiyse_isimler_yaziliyor() -> None:
    """Fiyat, A101 indirim yaptığı için değil ŞOK listeye girdiği için düşmüş
    olabilir; okuyan bunu görebilmeli."""
    metin = _tek_metin([_dusen(onceki_market="A101")])
    assert "dün A101 70,00 TL → bugün ŞOK 59,50 TL" in metin


def test_zam_dusus_olarak_yazilmaz() -> None:
    metin = _tek_metin([_kalem("Süt", [_market("A101", "30"), _market("BİM", "40")],
        dusus=DususBilgisi(
            onceki_gun=DUN, onceki_fiyat=Decimal("25"),
            son_gun=BUGUN, son_fiyat=Decimal("30"),
            onceki_market="A101", son_market="A101",
        ))])
    assert "🔻" not in metin


# --- bölme ---------------------------------------------------------------


def _cok_kalem(adet: int) -> list[KalemAnalizi]:
    return [
        _kalem(f"Ürün {i}", [_market("A101", "10"), _market("BİM", str(20 + i))],
               kalem_id=i)
        for i in range(1, adet + 1)
    ]


def test_sinir_asilinca_bolunuyor() -> None:
    mesajlar = whatsapp_mesajlari(
        _cok_kalem(25), gun=BUGUN, settings=AYAR, kalem_siniri=10
    )
    assert [m.kalem_sayisi for m in mesajlar] == [10, 10, 5]
    assert mesajlar[0].toplam_sayfa == 3
    assert "(1/3)" in mesajlar[0].metin
    assert "(3/3)" in mesajlar[2].metin


def test_sinir_ayardan_okunuyor() -> None:
    """`.env`'deki MESSAGE_ITEM_LIMIT, çağrıda sınır verilmediğinde geçerli."""
    ayar = AYAR.model_copy(update={"message_item_limit": 5})
    mesajlar = whatsapp_mesajlari(_cok_kalem(12), gun=BUGUN, settings=ayar)
    assert [m.kalem_sayisi for m in mesajlar] == [5, 5, 2]


def test_cagridaki_sinir_ayari_eziyor() -> None:
    ayar = AYAR.model_copy(update={"message_item_limit": 5})
    mesajlar = whatsapp_mesajlari(
        _cok_kalem(12), gun=BUGUN, settings=ayar, kalem_siniri=100
    )
    assert len(mesajlar) == 1


def test_varsayilan_sinir_yuz() -> None:
    """29.07.2026: proje sahibi dosya sayısı artmasın diye yükseltilmesini istedi."""
    mesajlar = whatsapp_mesajlari(_cok_kalem(40), gun=BUGUN, settings=AYAR)
    assert len(mesajlar) == 1, "40 kalem tek mesajda kalmalı"


def test_tek_sayfada_sayfa_numarasi_yazilmaz() -> None:
    metin = _tek_metin([_kalem("Süt", [_market("A101", "30"), _market("BİM", "35")])])
    assert "(1/1)" not in metin


def test_kalem_siniri_degistirilebilir() -> None:
    mesajlar = whatsapp_mesajlari(
        _cok_kalem(5), gun=BUGUN, settings=AYAR, kalem_siniri=2
    )
    assert [m.kalem_sayisi for m in mesajlar] == [2, 2, 1]


# --- sıralama ------------------------------------------------------------


def test_dusenler_farklilardan_once_gelir() -> None:
    farkli = _kalem("Farkli", [_market("A101", "10"), _market("BİM", "500")], kalem_id=1)
    dusen = _kalem("Dusen", [_market("ŞOK", "90"), _market("Migros", "95")],
        kalem_id=2, dusus=DususBilgisi(
            onceki_gun=DUN, onceki_fiyat=Decimal("100"),
            son_gun=BUGUN, son_fiyat=Decimal("90"),
            onceki_market="ŞOK", son_market="ŞOK",
        ))
    metin = _tek_metin([farkli, dusen])
    assert metin.index("*Dusen*") < metin.index("*Farkli*")


def test_kalem_hem_dusen_hem_farkli_ise_bir_kez_yazilir() -> None:
    dusen = _kalem("Tek", [_market("ŞOK", "90"), _market("Migros", "500")],
        kalem_id=7, dusus=DususBilgisi(
            onceki_gun=DUN, onceki_fiyat=Decimal("100"),
            son_gun=BUGUN, son_fiyat=Decimal("90"),
            onceki_market="ŞOK", son_market="ŞOK",
        ))
    metin = _tek_metin([dusen])
    assert metin.count("*Tek*") == 1


# --- tarih dürüstlüğü ----------------------------------------------------


def test_baslik_gozlem_gununu_gosterir_cekim_gununu_degil() -> None:
    """Toplama kaçtıysa eldeki veri dünündür; bugünün tarihini yazmak
    eski fiyatı bugünün fiyatı gibi gösterirdi."""
    metin = _tek_metin([_kalem(
        "Süt", [_market("A101", "30"), _market("BİM", "35")], son_gun=DUN
    )])
    assert "📅 27.07.2026" in metin
    assert "1 gün önce toplandı" in metin
    assert "Bugünün" not in metin


def test_gozlem_bugunse_bugun_denir() -> None:
    metin = _tek_metin([_kalem("Süt", [_market("A101", "30"), _market("BİM", "35")])])
    assert "Bugünün" in metin
    assert "önce toplandı" not in metin


def test_soylenecek_sey_yoksa_mesaj_uretilmez() -> None:
    assert whatsapp_mesajlari([], gun=BUGUN, settings=AYAR) == []
