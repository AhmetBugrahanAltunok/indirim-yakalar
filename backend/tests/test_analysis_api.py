"""Faz 2 uçları: /comparisons, price-history, whatsapp-preview.

Bu testler CANLI veritabanına bakar (gerçek takip listesi ve toplanmış
fiyatlar). Bu yüzden sabit sayı beklenmez — sözleşme doğrulanır: alan adları,
tipler, ve "veri yoksa da anlamlı yanıt" davranışı. Hesabın doğruluğu
`test_analyzer.py`'de izole veriyle sınanıyor.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# --- /comparisons --------------------------------------------------------


def test_comparisons_sozlesmesi() -> None:
    resp = client.get("/comparisons")
    assert resp.status_code == 200
    govde = resp.json()
    assert isinstance(govde, list)

    for kalem in govde:
        assert set(kalem) == {
            "kalem_id", "etiket", "son_gun", "marketler", "market_sayisi",
            "en_ucuz_denebilir_mi", "beraberlik_var_mi", "en_pahali_fark", "dusus",
        }
        assert kalem["market_sayisi"] == len(kalem["marketler"])
        for market in kalem["marketler"]:
            assert set(market) == {"slug", "ad", "fiyat", "depo_sayisi"}


def test_comparisons_fiyatlar_ucuzdan_pahaliya() -> None:
    for kalem in client.get("/comparisons").json():
        fiyatlar = [Decimal(str(m["fiyat"])) for m in kalem["marketler"]]
        assert fiyatlar == sorted(fiyatlar)


def test_tek_market_biliniyorsa_en_ucuz_denmiyor() -> None:
    """Anayasa md. 7 uçta da geçerli."""
    for kalem in client.get("/comparisons").json():
        if kalem["market_sayisi"] <= 1:
            assert kalem["en_ucuz_denebilir_mi"] is False
            assert kalem["en_pahali_fark"] is None


def test_hepsi_ayni_fiyatsa_en_ucuz_denmiyor() -> None:
    for kalem in client.get("/comparisons").json():
        fiyatlar = {str(m["fiyat"]) for m in kalem["marketler"]}
        if len(fiyatlar) == 1 and kalem["market_sayisi"] > 1:
            assert kalem["en_ucuz_denebilir_mi"] is False


def test_gozlemi_olmayan_kalem_listede_yok() -> None:
    """Fiyatı bilinmeyen kalem "0,00 TL" gibi görünmemeli."""
    for kalem in client.get("/comparisons").json():
        assert kalem["marketler"], "boş market listesiyle kalem dönmemeli"


# --- fiyat geçmişi -------------------------------------------------------


def test_price_history_sozlesmesi() -> None:
    karsilastirmalar = client.get("/comparisons").json()
    if not karsilastirmalar:
        return  # henüz toplama yapılmamış

    kalem_id = karsilastirmalar[0]["kalem_id"]
    resp = client.get(f"/watchlist/{kalem_id}/price-history")
    assert resp.status_code == 200

    govde = resp.json()
    assert set(govde) == {"kalem_id", "etiket", "gozlem_gunu_sayisi", "noktalar"}
    assert govde["gozlem_gunu_sayisi"] >= 1
    for nokta in govde["noktalar"]:
        assert set(nokta) == {"gun", "slug", "market", "fiyat"}


def test_price_history_gunler_artan_sirada() -> None:
    karsilastirmalar = client.get("/comparisons").json()
    if not karsilastirmalar:
        return

    kalem_id = karsilastirmalar[0]["kalem_id"]
    gunler = [n["gun"] for n in client.get(f"/watchlist/{kalem_id}/price-history").json()["noktalar"]]
    assert gunler == sorted(gunler)


def test_olmayan_kalem_404() -> None:
    assert client.get("/watchlist/99999999/price-history").status_code == 404
    assert client.get("/watchlist/99999999/comparison").status_code == 404


# --- WhatsApp mesajı -----------------------------------------------------


def test_whatsapp_onizleme_sozlesmesi() -> None:
    resp = client.get("/messages/whatsapp-preview")
    assert resp.status_code == 200

    govde = resp.json()
    assert set(govde) == {"mesajlar", "aciklama"}
    assert govde["aciklama"], "boş liste bile sessiz kalmamalı"

    for mesaj in govde["mesajlar"]:
        assert set(mesaj) == {"metin", "sayfa", "toplam_sayfa", "kalem_sayisi"}
        assert mesaj["metin"].startswith("🛒")


def test_whatsapp_mesajinda_para_virgullu_yazilmis() -> None:
    """Anayasa md. 2: kullanıcıya görünen para 189,00 TL biçiminde.

    Yakalanan hata biçimi "59.50 TL" — nokta ondalıklı yazım.
    """
    goruldu = 0
    for mesaj in client.get("/messages/whatsapp-preview").json()["mesajlar"]:
        for satir in mesaj["metin"].splitlines():
            if " TL" not in satir:
                continue
            tutar = satir.split(" TL")[0].split()[-1].strip("*_")
            assert "," in tutar, f"kuruş virgülle ayrılmalı: {satir!r}"
            # Nokta yalnız binlik ayıracı olabilir ve virgülden ÖNCE gelir.
            if "." in tutar:
                assert tutar.index(".") < tutar.index(","), satir
            goruldu += 1

    if client.get("/comparisons").json():
        assert goruldu > 0, "fiyat satırı hiç görülmedi — test boşa koşmuş"


def test_sayfa_numaralari_tutarli() -> None:
    mesajlar = client.get("/messages/whatsapp-preview").json()["mesajlar"]
    for i, mesaj in enumerate(mesajlar, start=1):
        assert mesaj["sayfa"] == i
        assert mesaj["toplam_sayfa"] == len(mesajlar)


def test_kalem_siniri_uygulaniyor() -> None:
    govde = client.get("/messages/whatsapp-preview?kalem_siniri=3").json()
    for mesaj in govde["mesajlar"]:
        assert mesaj["kalem_sayisi"] <= 3


def test_bayat_kalem_ucu_sozlesmesi() -> None:
    resp = client.get("/watchlist/stale")
    assert resp.status_code == 200

    for kalem in resp.json():
        assert set(kalem) == {
            "kalem_id", "etiket", "son_veri", "gun_farki",
            "bagli_id_sayisi", "hic_veri_yok",
        }
        # Hiç verisi yoksa gün farkı anlamsızdır ve null olmalı.
        if kalem["hic_veri_yok"]:
            assert kalem["son_veri"] is None
            assert kalem["gun_farki"] is None
        else:
            assert kalem["gun_farki"] >= 0


def test_bayat_esigi_yukseltilince_liste_kisalir() -> None:
    az = len(client.get("/watchlist/stale?esik_gun=1").json())
    cok = len(client.get("/watchlist/stale?esik_gun=90").json())
    assert cok <= az


def test_gecersiz_bayat_esigi_reddediliyor() -> None:
    assert client.get("/watchlist/stale?esik_gun=-1").status_code == 422
    assert client.get("/watchlist/stale?esik_gun=999").status_code == 422


def test_gecersiz_kalem_siniri_reddediliyor() -> None:
    assert client.get("/messages/whatsapp-preview?kalem_siniri=0").status_code == 422
    assert client.get("/messages/whatsapp-preview?kalem_siniri=999").status_code == 422
