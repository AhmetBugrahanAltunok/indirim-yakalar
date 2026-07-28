"""WhatsApp gönderim testleri — GERÇEK gönderim yapmadan.

Node süreci hiç çalıştırılmıyor: `subprocess.run` taklit ediliyor. Gerçek
gönderim testi, her koşuda birine mesaj atmak demek olurdu.

Kovalanan asıl davranış: **kapalıyken hiçbir şey göndermemek** ve
**başarısızlığı yutmamak**. Bu iki hatanın ikisi de sessiz olurdu.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.config import Settings, get_settings
from app.services import whatsapp_sender
from app.services.whatsapp_sender import (
    WhatsAppHatasi,
    gonderilebilir_mi,
    mesajlari_gonder,
)


def _ayar(**degisiklik) -> Settings:
    temel = {
        "whatsapp_enabled": True,
        "whatsapp_recipient": "905550000000",  # yer tutucu, gerçek numara değil
        "whatsapp_session_dir": r"C:\ornek\oturum",
    }
    temel.update(degisiklik)
    return get_settings().model_copy(update=temel)


@pytest.fixture
def mesaj(tmp_path) -> Path:
    yol = tmp_path / "mesaj-2026-07-29.txt"
    yol.write_text("🛒 Market Fiyatları", encoding="utf-8")
    return yol


class _SahteSonuc:
    def __init__(self, kod: int = 0, cikti: str = "", hata: str = "") -> None:
        self.returncode = kod
        self.stdout = cikti
        self.stderr = hata


def _yakala(monkeypatch, sonuc: _SahteSonuc) -> dict:
    """subprocess.run'ı taklit eder ve çağrıyı yakalar."""
    yakalanan: dict = {}

    def sahte_run(komut, **kw):
        yakalanan["komut"] = komut
        yakalanan["env"] = kw.get("env", {})
        yakalanan["timeout"] = kw.get("timeout")
        return sonuc

    monkeypatch.setattr(subprocess, "run", sahte_run)
    return yakalanan


# --- kapalıyken hiçbir şey göndermemeli ---------------------------------


def test_varsayilan_kapali() -> None:
    """Hiçbir kurulum kazara mesaj göndermemeli."""
    assert get_settings().whatsapp_enabled is False


def test_kapaliyken_node_calistirilmiyor(monkeypatch, mesaj) -> None:
    yakalanan = _yakala(monkeypatch, _SahteSonuc())
    assert mesajlari_gonder([mesaj], _ayar(whatsapp_enabled=False)) is False
    assert yakalanan == {}, "kapalıyken süreç açılmamalı"


def test_alici_yoksa_gonderilmiyor(monkeypatch, mesaj) -> None:
    yakalanan = _yakala(monkeypatch, _SahteSonuc())
    assert mesajlari_gonder([mesaj], _ayar(whatsapp_recipient="")) is False
    assert yakalanan == {}


def test_dosya_yoksa_gonderilmiyor(monkeypatch) -> None:
    """Paylaşılacak bir şey yokken boş mesaj atılmamalı."""
    yakalanan = _yakala(monkeypatch, _SahteSonuc())
    assert mesajlari_gonder([], _ayar()) is False
    assert yakalanan == {}


@pytest.mark.parametrize(("degisiklik", "beklenen"), [
    ({"whatsapp_enabled": False}, "ENABLED"),
    ({"whatsapp_recipient": "  "}, "RECIPIENT"),
])
def test_gonderilebilir_mi_nedeni_soyluyor(degisiklik, beklenen) -> None:
    uygun, neden = gonderilebilir_mi(_ayar(**degisiklik))
    assert uygun is False
    assert beklenen in neden


# --- başarılı gönderim ---------------------------------------------------


def test_basarili_gonderim(monkeypatch, mesaj) -> None:
    _yakala(monkeypatch, _SahteSonuc(0, "gonderildi 1/1 (18 karakter)"))
    assert mesajlari_gonder([mesaj], _ayar()) is True


def test_dosya_yollari_argumana_ekleniyor(monkeypatch, tmp_path) -> None:
    yollar = []
    for i in (1, 2):
        y = tmp_path / f"mesaj-{i}.txt"
        y.write_text("x", encoding="utf-8")
        yollar.append(y)

    yakalanan = _yakala(monkeypatch, _SahteSonuc())
    mesajlari_gonder(yollar, _ayar())

    komut = yakalanan["komut"]
    assert komut[1].endswith("gonder.js")
    assert komut[2:] == [str(y) for y in yollar]


def test_alici_ortam_degiskeniyle_gecirilliyor(monkeypatch, mesaj) -> None:
    """Numara komut satırına YAZILMAZ: süreç listesinde görünür olurdu."""
    yakalanan = _yakala(monkeypatch, _SahteSonuc())
    mesajlari_gonder([mesaj], _ayar())

    assert yakalanan["env"]["WHATSAPP_RECIPIENT"] == "905550000000"
    assert not any("905550000000" in str(p) for p in yakalanan["komut"])


def test_mevcut_ortam_korunuyor(monkeypatch, mesaj) -> None:
    """Boş ortamla Node Windows'ta açılmıyor (PATH, SystemRoot gerekli)."""
    yakalanan = _yakala(monkeypatch, _SahteSonuc())
    mesajlari_gonder([mesaj], _ayar())
    assert "PATH" in {k.upper() for k in yakalanan["env"]}


def test_sure_asimi_ayardan(monkeypatch, mesaj) -> None:
    yakalanan = _yakala(monkeypatch, _SahteSonuc())
    mesajlari_gonder([mesaj], _ayar(whatsapp_timeout_sec=99))
    assert yakalanan["timeout"] == 99


# --- başarısızlık yutulmamalı -------------------------------------------


@pytest.mark.parametrize(("kod", "parca"), [
    (2, "yapılandırma"),
    (3, "baglan.js"),
    (4, "kayıtlı değil"),
    (5, "gönderim hatası"),
    (6, "süre aşımı"),
])
def test_cikis_kodu_anlamli_hataya_ceviriliyor(monkeypatch, mesaj, kod, parca) -> None:
    _yakala(monkeypatch, _SahteSonuc(kod, hata="ayrinti"))
    with pytest.raises(WhatsAppHatasi, match=parca):
        mesajlari_gonder([mesaj], _ayar())


def test_bilinmeyen_kod_da_hata(monkeypatch, mesaj) -> None:
    _yakala(monkeypatch, _SahteSonuc(99))
    with pytest.raises(WhatsAppHatasi, match="99"):
        mesajlari_gonder([mesaj], _ayar())


def test_node_yoksa_anlamli_hata(monkeypatch, mesaj) -> None:
    def patlat(komut, **kw):
        raise FileNotFoundError("node")

    monkeypatch.setattr(subprocess, "run", patlat)
    with pytest.raises(WhatsAppHatasi, match="Node çalıştırılamadı"):
        mesajlari_gonder([mesaj], _ayar())


def test_sure_asiminda_anlamli_hata(monkeypatch, mesaj) -> None:
    def patlat(komut, **kw):
        raise subprocess.TimeoutExpired(komut, 240)

    monkeypatch.setattr(subprocess, "run", patlat)
    with pytest.raises(WhatsAppHatasi, match="240"):
        mesajlari_gonder([mesaj], _ayar())


# --- çıkış kodu sözleşmesi ----------------------------------------------


def test_cikis_kodlari_gonder_js_ile_ayni() -> None:
    """Kodlar iki dosyada elle tutuluyor; sapma sessiz yanlış teşhis olurdu."""
    kaynak = (Path(whatsapp_sender.__file__).resolve().parents[3]
              / "whatsapp" / "gonder.js").read_text(encoding="utf-8")
    for kod in (2, 3, 4, 5, 6):
        assert f"process.exit({kod})" in kaynak, f"gonder.js'te {kod} yok"
