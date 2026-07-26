"""/markets ve /depots uçları.

`POST /depots/refresh` burada test EDİLMEZ — gerçek API'ye istek atar.
Onun mantığı `test_depot_resolver.py`'de sahte istemciyle test ediliyor;
burada yalnız okuma uçları doğrulanır.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_markets_listesi_donuyor() -> None:
    resp = client.get("/markets")
    assert resp.status_code == 200
    govde = resp.json()
    assert isinstance(govde, list)
    for market in govde:
        assert set(market) == {"id", "slug", "name"}


def test_depots_listesi_bicimi() -> None:
    resp = client.get("/depots")
    assert resp.status_code == 200
    govde = resp.json()
    assert isinstance(govde, list)
    for depo in govde:
        assert set(depo) == {
            "id", "market_id", "name", "latitude", "longitude",
            "distance_m", "active", "refreshed_at",
        }
        assert depo["active"] is True, "varsayılan yalnız aktifleri döndürmeli"


def test_depots_mesafeye_gore_sirali() -> None:
    """En yakın mağaza başta olmalı — panelde ve mesajda anlamlı sıra bu."""
    depolar = client.get("/depots").json()
    mesafeler = [float(d["distance_m"]) for d in depolar if d["distance_m"] is not None]
    assert mesafeler == sorted(mesafeler)


def test_pasif_depolar_istege_bagli_geliyor() -> None:
    yalniz_aktif = client.get("/depots").json()
    hepsi = client.get("/depots", params={"yalniz_aktif": False}).json()
    assert len(hepsi) >= len(yalniz_aktif)
