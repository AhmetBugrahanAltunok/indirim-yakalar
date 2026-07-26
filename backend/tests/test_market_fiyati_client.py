"""API istemcisinin kendi güvenlik kuralları — ağa çıkmadan test edilir.

Burada test edilen şey "API ne döndürüyor" değil, "istemci kendi kurallarına
uyuyor mu": konumsuz çağrı engelleniyor mu, 418 hataya dönüyor mu, bekleme
uygulanıyor mu, para Decimal olarak mı ayrıştırılıyor.
"""

from __future__ import annotations

import time
from decimal import Decimal

import httpx
import pytest

from app.collectors.market_fiyati_client import (
    MAKS_SAYFA_BOYUTU,
    MarketFiyatiClient,
    MarketFiyatiError,
    WafBlockedError,
)

BASE = "https://api.marketfiyati.org.tr"


def _istemci(handler, delay_sec: float = 0.0) -> MarketFiyatiClient:
    """Gerçek ağ yerine httpx MockTransport kullanan istemci."""
    api = MarketFiyatiClient(base_url=BASE, delay_sec=delay_sec)
    api._client = httpx.Client(transport=httpx.MockTransport(handler))
    return api


def test_depotsuz_arama_engelleniyor() -> None:
    """Konumsuz çağrı sessizce yanlış şehirden veri getirir — baştan durdurulur."""
    api = _istemci(lambda r: httpx.Response(200, json={}))
    with pytest.raises(ValueError, match="depots"):
        api.search("süt", depots=[], latitude=37.0, longitude=35.0, distance_km=10)
    with pytest.raises(ValueError, match="depots"):
        api.search_by_identity("1LMO", depots=[], latitude=37.0,
                               longitude=35.0, distance_km=10)


def test_418_waf_hatasina_donusuyor() -> None:
    api = _istemci(lambda r: httpx.Response(418, text="Your Access Has Been Blocked"))
    with pytest.raises(WafBlockedError):
        api.nearest(37.0, 35.0, 10)


def test_diger_http_hatalari_ayirt_ediliyor() -> None:
    """500, WAF bloğu değildir — farklı istisna, farklı tepki."""
    api = _istemci(lambda r: httpx.Response(500, text="bozuk"))
    with pytest.raises(MarketFiyatiError) as bilgi:
        api.nearest(37.0, 35.0, 10)
    assert not isinstance(bilgi.value, WafBlockedError)


def test_fiyat_decimal_olarak_ayristiriliyor() -> None:
    """JSON'daki 59.5 float olarak değil Decimal olarak gelmeli (anayasa md. 1)."""
    govde = '{"content":[{"id":"1LMO","productDepotInfoList":[{"price":59.5}]}]}'
    api = _istemci(lambda r: httpx.Response(200, text=govde))
    sonuc = api.search_by_identity("1LMO", depots=["sok-0001"], latitude=37.0,
                                   longitude=35.0, distance_km=10)
    fiyat = sonuc["content"][0]["productDepotInfoList"][0]["price"]
    assert isinstance(fiyat, Decimal)
    assert fiyat == Decimal("59.5")


def test_govde_beklenen_alanlari_tasiyor() -> None:
    """Tanınmayan alan WAF bloğu yiyor — gönderdiğimiz alanlar sabit olmalı."""
    yakalanan: dict = {}

    def handler(istek: httpx.Request) -> httpx.Response:
        import json
        yakalanan.update(json.loads(istek.content))
        yakalanan["_yol"] = istek.url.path
        yakalanan["_yontem"] = istek.method
        return httpx.Response(200, json={"content": []})

    api = _istemci(handler)
    api.search_by_identity("1TOK", depots=["a101-0001"], latitude=40.0,
                           longitude=30.0, distance_km=10)

    assert yakalanan["_yontem"] == "POST", "GET 418 blok yiyor"
    assert yakalanan["_yol"] == "/api/v2/searchByIdentity"
    assert set(yakalanan) - {"_yol", "_yontem"} == {
        "identity", "identityType", "depots", "latitude", "longitude", "distance",
    }
    assert yakalanan["identityType"] == "id"
    assert yakalanan["depots"] == ["a101-0001"]


def test_sayfa_boyutu_sinira_kirpiliyor() -> None:
    """Sunucu ~25'ten fazlasını dönmüyor; fazlasını istemek anlamsız."""
    yakalanan: dict = {}

    def handler(istek: httpx.Request) -> httpx.Response:
        import json
        yakalanan.update(json.loads(istek.content))
        return httpx.Response(200, json={"content": []})

    api = _istemci(handler)
    api.search("süt", depots=["sok-0001"], latitude=37.0, longitude=35.0,
               distance_km=10, size=100)
    assert yakalanan["size"] == MAKS_SAYFA_BOYUTU


def test_istekler_arasinda_bekleniyor() -> None:
    """Kaynağa saygılı hız: ikinci istek gecikmeli gitmeli."""
    api = _istemci(lambda r: httpx.Response(200, json=[]), delay_sec=0.3)
    baslangic = time.monotonic()
    api.nearest(37.0, 35.0, 10)
    api.nearest(37.0, 35.0, 10)
    gecen = time.monotonic() - baslangic
    assert gecen >= 0.3, f"bekleme uygulanmadı ({gecen:.2f} sn)"


def test_ilk_istek_gereksiz_beklemiyor() -> None:
    api = _istemci(lambda r: httpx.Response(200, json=[]), delay_sec=5.0)
    baslangic = time.monotonic()
    api.nearest(37.0, 35.0, 10)
    assert time.monotonic() - baslangic < 1.0


def test_nearest_liste_disinda_bir_sey_donerse_hata() -> None:
    """Sözleşme değişirse fark edilsin."""
    api = _istemci(lambda r: httpx.Response(200, json={"content": []}))
    with pytest.raises(MarketFiyatiError, match="liste"):
        api.nearest(37.0, 35.0, 10)
