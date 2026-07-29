"""Analyzer testleri — en ucuz hesabı ve fiyat düşüşü tespiti.

Buradaki senaryolar uydurma değil: her biri 26-27.07.2026'da gerçek veride
görülen bir durumun sadeleştirilmiş hali. Özellikle üçü tekrar ısırabilir —
mükerrer katalog kaydı, aynı zincirin farklı şube fiyatı, ve gözlem günleri
arasındaki boşluk.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.session import engine
from app.models import (
    Depot,
    Market,
    PriceHistory,
    Product,
    WatchlistItem,
    WatchlistSourceId,
)
from app.services.analyzer import (
    dusenler,
    kalem_analiz_et,
    tum_kalemleri_analiz_et,
)

# Gerçek platform ID'leriyle çakışmasın diye ayrılmış önek (bkz. test_models).
ONEK = "AN"
# Gerçek gözlem günlerinden uzak: canlı veriyle karışmasın.
GUN1 = date.today() + timedelta(days=500)
GUN2 = GUN1 + timedelta(days=1)


@pytest.fixture
def db():
    baglanti = engine.connect()
    dis_islem = baglanti.begin()
    oturum = Session(bind=baglanti, join_transaction_mode="create_savepoint")
    try:
        # Gerçek takip listesi (76 kalem) analiz sonuçlarına karışmasın.
        oturum.query(WatchlistItem).update({WatchlistItem.active: False})
        oturum.flush()
        yield oturum
    finally:
        oturum.close()
        dis_islem.rollback()
        baglanti.close()


# --- kurulum yardımcıları ------------------------------------------------


def _market(db, slug: str, ad: str) -> Market:
    m = db.scalar(select(Market).where(Market.slug == slug))
    if m is None:
        m = Market(slug=slug, name=ad)
        db.add(m)
        db.flush()
    return m


def _depo(db, depo_id: str, market: Market) -> Depot:
    d = db.get(Depot, depo_id)
    if d is None:
        d = Depot(id=depo_id, market_id=market.id, name=depo_id, active=True)
        db.add(d)
        db.flush()
    return d


def _kalem(db, etiket: str, spidler: list[str]) -> WatchlistItem:
    kalem = WatchlistItem(label=etiket, active=True)
    db.add(kalem)
    db.flush()
    for spid in spidler:
        db.add(Product(source_product_id=spid, title=f"{etiket} [{spid}]"))
        db.flush()
        db.add(WatchlistSourceId(
            watchlist_item_id=kalem.id,
            source_product_id=spid,
            link_confirmed_by="test",
        ))
    db.flush()
    return kalem


def _fiyat(db, spid: str, depo: Depot, gun: date, fiyat: str) -> None:
    urun = db.scalar(select(Product).where(Product.source_product_id == spid))
    assert urun is not None
    db.add(PriceHistory(
        product_id=urun.id,
        depot_id=depo.id,
        market_id=depo.market_id,
        price=Decimal(fiyat),
        collected_date=gun,
    ))
    db.flush()


# --- en ucuz -------------------------------------------------------------


def test_en_ucuz_bagli_tum_idler_birlestirilerek_bulunur(db) -> None:
    """Mükerrer katalog kaydı senaryosu — projenin kurucu bulgusu.

    26.07.2026: `1TOK` tek başına bakınca en ucuz carrefour 60,00 diyordu;
    aynı ürünün ikinci kaydı `21D5` a101'de 55,00'ti ve ortak depo yoktu.
    Tek kayda bakan kullanıcı %8,3 pahalıya yönlendiriliyordu.
    """
    a101 = _market(db, "a101", "A101")
    carrefour = _market(db, "carrefour", "CarrefourSA")
    d_a101 = _depo(db, f"{ONEK}-a101-1", a101)
    d_car = _depo(db, f"{ONEK}-car-1", carrefour)

    kalem = _kalem(db, "Red Bull 250 ml", [f"{ONEK}01", f"{ONEK}02"])
    _fiyat(db, f"{ONEK}01", d_car, GUN1, "60.00")
    _fiyat(db, f"{ONEK}02", d_a101, GUN1, "55.00")

    analiz = kalem_analiz_et(db, kalem)
    assert analiz is not None
    assert analiz.en_ucuz.fiyat == Decimal("55.00")
    assert analiz.en_ucuz.ad == "A101"
    assert analiz.market_sayisi == 2
    assert analiz.en_pahali_fark == Decimal("5.00")


def test_ayni_zincirin_en_ucuz_subesi_alinir(db) -> None:
    """Aynı zincirin iki şubesi 70,00 ⟷ 55,00 — zincir tek satırda görünmeli.

    26.07.2026'da gerçek veride görüldü; şube kimlikleri kasada, burada değil
    (anayasa md. 5: test verisinde gerçek mağaza ID'si kullanılmaz).
    """
    a101 = _market(db, "a101", "A101")
    pahali = _depo(db, f"{ONEK}-a101-pahali", a101)
    ucuz = _depo(db, f"{ONEK}-a101-ucuz", a101)

    kalem = _kalem(db, "Sube farki", [f"{ONEK}03"])
    _fiyat(db, f"{ONEK}03", pahali, GUN1, "70.00")
    _fiyat(db, f"{ONEK}03", ucuz, GUN1, "55.00")

    analiz = kalem_analiz_et(db, kalem)
    assert analiz.market_sayisi == 1, "aynı zincir iki satır olmamalı"
    assert analiz.en_ucuz.fiyat == Decimal("55.00")
    assert analiz.en_ucuz.depo_sayisi == 2


def test_tek_market_biliniyorsa_en_ucuz_denmez(db) -> None:
    """Anayasa md. 7: kıyas yoksa "en ucuz" iddiası uydurmadır."""
    sok = _market(db, "sok", "ŞOK")
    depo = _depo(db, f"{ONEK}-sok-1", sok)

    kalem = _kalem(db, "Tek market", [f"{ONEK}04"])
    _fiyat(db, f"{ONEK}04", depo, GUN1, "42.00")

    analiz = kalem_analiz_et(db, kalem)
    assert analiz.market_sayisi == 1
    assert analiz.en_ucuz_denebilir_mi is False
    assert analiz.en_pahali_fark is None


def test_hepsi_ayni_fiyatsa_en_ucuz_denmez(db) -> None:
    """27.07.2026: Çaykur Rize Turist 1 kg A101/BİM/ŞOK'ta aynı anda 365,00.

    Ortada en ucuz yok; birini seçip yazmak kullanıcıyı boşuna yönlendirir.
    """
    for slug, ad in [("a101", "A101"), ("bim", "BİM"), ("sok", "ŞOK")]:
        m = _market(db, slug, ad)
        d = _depo(db, f"{ONEK}-{slug}-berabere", m)
        if slug == "a101":
            kalem = _kalem(db, "Berabere cay", [f"{ONEK}05"])
        _fiyat(db, f"{ONEK}05", d, GUN1, "365.00")

    analiz = kalem_analiz_et(db, kalem)
    assert analiz.market_sayisi == 3
    assert analiz.en_ucuz_denebilir_mi is False
    assert analiz.beraberlik_var_mi is True
    assert len(analiz.en_ucuz_marketler) == 3


def test_kismi_beraberlikte_en_ucuz_denir(db) -> None:
    """İki market 365,00'te berabere ama üçüncüsü 400,00 → kıyas gerçek."""
    fiyatlar = {"a101": "365.00", "bim": "365.00", "migros": "400.00"}
    kalem = _kalem(db, "Kismi berabere", [f"{ONEK}06"])
    for slug, fiyat in fiyatlar.items():
        m = _market(db, slug, slug.upper())
        d = _depo(db, f"{ONEK}-{slug}-kismi", m)
        _fiyat(db, f"{ONEK}06", d, GUN1, fiyat)

    analiz = kalem_analiz_et(db, kalem)
    assert analiz.en_ucuz_denebilir_mi is True
    assert analiz.beraberlik_var_mi is True
    assert len(analiz.en_ucuz_marketler) == 2


def test_gozlemi_olmayan_kalem_none_doner(db) -> None:
    kalem = _kalem(db, "Fiyati yok", [f"{ONEK}07"])
    assert kalem_analiz_et(db, kalem) is None


# --- fiyat düşüşü --------------------------------------------------------


def test_tek_gun_gozlemle_dusus_denmez(db) -> None:
    """SPEC §6.3: tek gözlemle "düştü" denmez."""
    m = _market(db, "sok", "ŞOK")
    d = _depo(db, f"{ONEK}-sok-tek", m)
    kalem = _kalem(db, "Tek gun", [f"{ONEK}08"])
    _fiyat(db, f"{ONEK}08", d, GUN1, "50.00")

    analiz = kalem_analiz_et(db, kalem)
    assert analiz.dusus is None


def test_dusus_hesaplaniyor(db) -> None:
    m = _market(db, "sok", "ŞOK")
    d = _depo(db, f"{ONEK}-sok-dusus", m)
    kalem = _kalem(db, "Dusen urun", [f"{ONEK}09"])
    _fiyat(db, f"{ONEK}09", d, GUN1, "70.00")
    _fiyat(db, f"{ONEK}09", d, GUN2, "59.50")

    dusus = kalem_analiz_et(db, kalem).dusus
    assert dusus.dustu_mu is True
    assert dusus.fark == Decimal("10.50")
    assert dusus.yuzde == Decimal("15")
    assert dusus.market_degisti_mi is False


def test_zam_dusus_sayilmaz(db) -> None:
    m = _market(db, "sok", "ŞOK")
    d = _depo(db, f"{ONEK}-sok-zam", m)
    kalem = _kalem(db, "Zamlanan", [f"{ONEK}10"])
    _fiyat(db, f"{ONEK}10", d, GUN1, "50.00")
    _fiyat(db, f"{ONEK}10", d, GUN2, "60.00")

    dusus = kalem_analiz_et(db, kalem).dusus
    assert dusus.dustu_mu is False
    assert dusus.fark == Decimal("-10.00")


def test_gunler_arasi_bosluk_gercek_tarihleri_tasiyor(db) -> None:
    """Makine kapalıyken gün atlanır — "dün" yazmak yalan olurdu (SPEC §6.3)."""
    uzak_gun = GUN1 + timedelta(days=13)
    m = _market(db, "sok", "ŞOK")
    d = _depo(db, f"{ONEK}-sok-bosluk", m)
    kalem = _kalem(db, "Bosluklu", [f"{ONEK}11"])
    _fiyat(db, f"{ONEK}11", d, GUN1, "80.00")
    _fiyat(db, f"{ONEK}11", d, uzak_gun, "70.00")

    dusus = kalem_analiz_et(db, kalem).dusus
    assert dusus.onceki_gun == GUN1
    assert dusus.son_gun == uzak_gun
    assert (dusus.son_gun - dusus.onceki_gun).days == 13


def test_en_son_iki_gozlem_gunu_kiyaslanir(db) -> None:
    """Üç gözlem varsa ilk gün değil, son iki gün karşılaştırılır."""
    m = _market(db, "sok", "ŞOK")
    d = _depo(db, f"{ONEK}-sok-uc", m)
    gun3 = GUN2 + timedelta(days=1)
    kalem = _kalem(db, "Uc gun", [f"{ONEK}12"])
    _fiyat(db, f"{ONEK}12", d, GUN1, "100.00")
    _fiyat(db, f"{ONEK}12", d, GUN2, "90.00")
    _fiyat(db, f"{ONEK}12", d, gun3, "85.00")

    dusus = kalem_analiz_et(db, kalem).dusus
    assert dusus.onceki_gun == GUN2
    assert dusus.onceki_fiyat == Decimal("90.00")
    assert dusus.son_fiyat == Decimal("85.00")


def test_taban_gun_verilince_o_gune_gore_kiyaslaniyor(db) -> None:
    """Mesaj 3 günde bir gidiyorsa kıyas da son mesajdan bu yana olmalı.

    Yalnız son iki günü kıyaslamak, arada olmuş bir indirimi mesaja hiç
    sokmazdı: aşağıda 100 → 90 → 88 var; son iki güne bakan %2 görür,
    üç güne bakan %12.
    """
    m = _market(db, "sok", "ŞOK")
    d = _depo(db, f"{ONEK}-sok-taban", m)
    gun3 = GUN2 + timedelta(days=1)
    kalem = _kalem(db, "Taban", [f"{ONEK}40"])
    _fiyat(db, f"{ONEK}40", d, GUN1, "100.00")
    _fiyat(db, f"{ONEK}40", d, GUN2, "90.00")
    _fiyat(db, f"{ONEK}40", d, gun3, "88.00")

    varsayilan = kalem_analiz_et(db, kalem).dusus
    assert varsayilan.onceki_fiyat == Decimal("90.00")

    tabanli = kalem_analiz_et(db, kalem, taban_gun=GUN1).dusus
    assert tabanli.onceki_gun == GUN1
    assert tabanli.onceki_fiyat == Decimal("100.00")
    assert tabanli.fark == Decimal("12.00")


def test_taban_gununde_gozlem_yoksa_oncekine_dusuluyor(db) -> None:
    """İstenen tarihte toplama yapılmamış olabilir (makine kapalıydı).

    O gün yok diye kıyastan vazgeçmek, gerçekten olmuş bir indirimi gizlerdi.
    """
    m = _market(db, "sok", "ŞOK")
    d = _depo(db, f"{ONEK}-sok-bosluk2", m)
    gun5 = GUN1 + timedelta(days=5)
    kalem = _kalem(db, "Bosluklu taban", [f"{ONEK}41"])
    _fiyat(db, f"{ONEK}41", d, GUN1, "100.00")
    _fiyat(db, f"{ONEK}41", d, gun5, "80.00")

    # GUN1+2'de gözlem yok; en yakın ÖNCEKİ gözlem GUN1.
    dusus = kalem_analiz_et(db, kalem, taban_gun=GUN1 + timedelta(days=2)).dusus
    assert dusus.onceki_gun == GUN1


def test_taban_gun_tum_gozlemlerden_eskiyse_en_eskiye_dusuluyor(db) -> None:
    m = _market(db, "sok", "ŞOK")
    d = _depo(db, f"{ONEK}-sok-eski", m)
    kalem = _kalem(db, "Eski taban", [f"{ONEK}42"])
    _fiyat(db, f"{ONEK}42", d, GUN1, "100.00")
    _fiyat(db, f"{ONEK}42", d, GUN2, "80.00")

    dusus = kalem_analiz_et(db, kalem, taban_gun=GUN1 - timedelta(days=30)).dusus
    assert dusus.onceki_gun == GUN1


def test_tek_gozlemde_taban_gun_de_dusus_uretmiyor(db) -> None:
    """Bir günü kendisiyle kıyaslamak "değişim yok" der; bu bilgi değil gürültü."""
    m = _market(db, "sok", "ŞOK")
    d = _depo(db, f"{ONEK}-sok-tekgun", m)
    kalem = _kalem(db, "Tek gozlem", [f"{ONEK}43"])
    _fiyat(db, f"{ONEK}43", d, GUN1, "100.00")

    assert kalem_analiz_et(db, kalem, taban_gun=GUN1).dusus is None


def test_en_ucuz_market_degisince_isaretleniyor(db) -> None:
    """Fiyat, A101 indirim yaptığı için değil ŞOK listeye girdiği için düşmüş
    olabilir. Mesajın dürüstlüğü bu ayrımı bilmeye bağlı."""
    a101 = _market(db, "a101", "A101")
    sok = _market(db, "sok", "ŞOK")
    d_a101 = _depo(db, f"{ONEK}-a101-degis", a101)
    d_sok = _depo(db, f"{ONEK}-sok-degis", sok)

    kalem = _kalem(db, "Market degisti", [f"{ONEK}13"])
    _fiyat(db, f"{ONEK}13", d_a101, GUN1, "70.00")
    _fiyat(db, f"{ONEK}13", d_a101, GUN2, "70.00")
    _fiyat(db, f"{ONEK}13", d_sok, GUN2, "59.50")

    dusus = kalem_analiz_et(db, kalem).dusus
    assert dusus.dustu_mu is True
    assert dusus.market_degisti_mi is True
    assert dusus.onceki_market == "A101"
    assert dusus.son_market == "ŞOK"


# --- eşik ve sıralama ----------------------------------------------------


def test_esigin_altindaki_oynama_indirim_sayilmaz(db) -> None:
    """Kuruşluk dalgalanma mesajı çöpe çevirirdi."""
    m = _market(db, "sok", "ŞOK")
    d = _depo(db, f"{ONEK}-sok-esik", m)
    kalem = _kalem(db, "Az dusen", [f"{ONEK}14"])
    _fiyat(db, f"{ONEK}14", d, GUN1, "100.00")
    _fiyat(db, f"{ONEK}14", d, GUN2, "99.00")  # %1

    ayar = get_settings().model_copy(update={"price_drop_threshold_pct": Decimal("5.0")})
    analizler = [kalem_analiz_et(db, kalem, settings=ayar)]
    assert dusenler(analizler, settings=ayar) == []


def test_esigi_asan_dusus_yakalanir(db) -> None:
    m = _market(db, "sok", "ŞOK")
    d = _depo(db, f"{ONEK}-sok-gecen", m)
    kalem = _kalem(db, "Cok dusen", [f"{ONEK}15"])
    _fiyat(db, f"{ONEK}15", d, GUN1, "100.00")
    _fiyat(db, f"{ONEK}15", d, GUN2, "80.00")  # %20

    ayar = get_settings().model_copy(update={"price_drop_threshold_pct": Decimal("5.0")})
    analizler = [kalem_analiz_et(db, kalem, settings=ayar)]
    assert len(dusenler(analizler, settings=ayar)) == 1


def test_dusenler_en_cok_dusen_basta_siralanir(db) -> None:
    ayar = get_settings().model_copy(update={"price_drop_threshold_pct": Decimal("5.0")})
    kalemler = []
    for i, (once, sonra) in enumerate([("100.00", "90.00"), ("100.00", "60.00")]):
        m = _market(db, "sok", "ŞOK")
        d = _depo(db, f"{ONEK}-sok-sira{i}", m)
        spid = f"{ONEK}2{i}"
        kalem = _kalem(db, f"Sira {i}", [spid])
        _fiyat(db, spid, d, GUN1, once)
        _fiyat(db, spid, d, GUN2, sonra)
        kalemler.append(kalem_analiz_et(db, kalem, settings=ayar))

    sirali = dusenler(kalemler, settings=ayar)
    assert [a.dusus.yuzde for a in sirali] == [Decimal("40"), Decimal("10")]


# --- toplu analiz --------------------------------------------------------


def test_pasif_kalem_analiz_edilmiyor(db) -> None:
    m = _market(db, "sok", "ŞOK")
    d = _depo(db, f"{ONEK}-sok-pasif", m)
    kalem = _kalem(db, "Pasif", [f"{ONEK}30"])
    _fiyat(db, f"{ONEK}30", d, GUN1, "10.00")
    kalem.active = False
    db.flush()

    etiketler = [a.etiket for a in tum_kalemleri_analiz_et(db)]
    assert "Pasif" not in etiketler
