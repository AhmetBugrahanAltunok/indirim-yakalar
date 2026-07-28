"""WhatsApp gönderim testleri — GERÇEK gönderim yapmadan.

Node süreci hiç çalıştırılmıyor: `subprocess.Popen` taklit ediliyor. Gerçek
gönderim testi, her koşuda birine mesaj atmak demek olurdu.

Kovalanan asıl davranışlar, hepsi SESSİZ arıza adayı:
  - kapalıyken göndermek
  - başarısızlığı yutmak
  - aynı mesajı iki kez göndermek (alıcı için en can sıkıcı olan)
  - süre aşımında Chromium'u öksüz bırakmak (her hatada bir tane birikir)
  - iki koşunun aynı tarayıcı profilini bozması
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from app.config import Settings, get_settings
from app.services import whatsapp_sender
from app.services.whatsapp_sender import (
    WhatsAppHatasi,
    gonderilebilir_mi,
    mesajlari_gonder,
)


def _ayar(tmp_path: Path, **degisiklik) -> Settings:
    temel = {
        "whatsapp_enabled": True,
        "whatsapp_recipient": "905550000000",  # yer tutucu, gerçek numara değil
        "whatsapp_session_dir": str(tmp_path / "oturum"),
        "message_dir": str(tmp_path / "mesaj"),
    }
    temel.update(degisiklik)
    return get_settings().model_copy(update=temel)


@pytest.fixture
def mesaj(tmp_path) -> Path:
    yol = tmp_path / "mesaj-2026-07-29.txt"
    yol.write_text("🛒 Market Fiyatları", encoding="utf-8")
    return yol


class _SahtePopen:
    """Node sürecinin yerine geçer. `sure_asimi=True` ise communicate patlar."""

    def __init__(self, kod=0, cikti="", hata="", sure_asimi=False):
        self._kod, self._cikti, self._hata = kod, cikti, hata
        self._sure_asimi = sure_asimi
        self.pid = 4242
        self.returncode = kod
        self.communicate_cagrisi = 0

    def communicate(self, timeout=None):
        self.communicate_cagrisi += 1
        # İkinci çağrı (öldürmeden sonraki tahliye) her zaman döner.
        if self._sure_asimi and self.communicate_cagrisi == 1:
            raise subprocess.TimeoutExpired("node", timeout or 0)
        return self._cikti, self._hata


def _yakala(monkeypatch, sahte: _SahtePopen) -> dict:
    yakalanan: dict = {}

    def sahte_popen(komut, **kw):
        yakalanan["komut"] = komut
        yakalanan["env"] = kw.get("env", {})
        return sahte

    monkeypatch.setattr(subprocess, "Popen", sahte_popen)
    return yakalanan


@pytest.fixture
def oldurulenler(monkeypatch) -> list:
    """taskkill çağrılarını yakalar — gerçekten süreç öldürmeyelim."""
    cagrilar: list = []

    def sahte_run(komut, **kw):
        cagrilar.append(komut)
        return subprocess.CompletedProcess(komut, 0, "", "")

    monkeypatch.setattr(subprocess, "run", sahte_run)
    return cagrilar


# --- kapalıyken hiçbir şey göndermemeli ---------------------------------


def test_varsayilan_kapali() -> None:
    """Hiçbir kurulum kazara mesaj göndermemeli."""
    assert get_settings().whatsapp_enabled is False


def test_kapaliyken_surec_acilmiyor(monkeypatch, mesaj, tmp_path) -> None:
    yakalanan = _yakala(monkeypatch, _SahtePopen())
    assert mesajlari_gonder([mesaj], _ayar(tmp_path, whatsapp_enabled=False)) is False
    assert yakalanan == {}


def test_alici_yoksa_gonderilmiyor(monkeypatch, mesaj, tmp_path) -> None:
    yakalanan = _yakala(monkeypatch, _SahtePopen())
    assert mesajlari_gonder([mesaj], _ayar(tmp_path, whatsapp_recipient="")) is False
    assert yakalanan == {}


def test_dosya_yoksa_gonderilmiyor(monkeypatch, tmp_path) -> None:
    yakalanan = _yakala(monkeypatch, _SahtePopen())
    assert mesajlari_gonder([], _ayar(tmp_path)) is False
    assert yakalanan == {}


@pytest.mark.parametrize(("degisiklik", "beklenen"), [
    ({"whatsapp_enabled": False}, "ENABLED"),
    ({"whatsapp_recipient": "  "}, "RECIPIENT"),
])
def test_gonderilebilir_mi_nedeni_soyluyor(tmp_path, degisiklik, beklenen) -> None:
    uygun, neden = gonderilebilir_mi(_ayar(tmp_path, **degisiklik))
    assert uygun is False
    assert beklenen in neden


# --- başarılı gönderim ---------------------------------------------------


def test_basarili_gonderim(monkeypatch, mesaj, tmp_path) -> None:
    _yakala(monkeypatch, _SahtePopen(0, "gonderildi 1/1"))
    assert mesajlari_gonder([mesaj], _ayar(tmp_path)) is True


def test_dosya_yollari_argumana_ekleniyor(monkeypatch, tmp_path) -> None:
    yollar = []
    for i in (1, 2):
        y = tmp_path / f"mesaj-{i}.txt"
        y.write_text(f"icerik {i}", encoding="utf-8")
        yollar.append(y)

    yakalanan = _yakala(monkeypatch, _SahtePopen())
    mesajlari_gonder(yollar, _ayar(tmp_path))

    assert yakalanan["komut"][1].endswith("gonder.js")
    assert yakalanan["komut"][2:] == [str(y) for y in yollar]


def test_alici_ortam_degiskeniyle_geciyor(monkeypatch, mesaj, tmp_path) -> None:
    """Numara komut satırına YAZILMAZ: süreç listesinde görünür olurdu."""
    yakalanan = _yakala(monkeypatch, _SahtePopen())
    mesajlari_gonder([mesaj], _ayar(tmp_path))

    assert yakalanan["env"]["WHATSAPP_RECIPIENT"] == "905550000000"
    assert not any("905550000000" in str(p) for p in yakalanan["komut"])


def test_mevcut_ortam_korunuyor(monkeypatch, mesaj, tmp_path) -> None:
    """Boş ortamla Node Windows'ta açılmıyor (PATH, SystemRoot gerekli)."""
    yakalanan = _yakala(monkeypatch, _SahtePopen())
    mesajlari_gonder([mesaj], _ayar(tmp_path))
    assert "PATH" in {k.upper() for k in yakalanan["env"]}


# --- aynı mesaj iki kez gitmemeli ---------------------------------------


def test_ayni_mesaj_ikinci_kez_gonderilmiyor(monkeypatch, mesaj, tmp_path) -> None:
    """Günlük koşu aynı gün iki kez çalışırsa alıcı mesajı iki kez alırdı."""
    ayar = _ayar(tmp_path)
    _yakala(monkeypatch, _SahtePopen())

    assert mesajlari_gonder([mesaj], ayar) is True
    assert mesajlari_gonder([mesaj], ayar) is False, "ikinci kez gitmemeli"


def test_icerik_degisirse_yeniden_gonderiliyor(monkeypatch, mesaj, tmp_path) -> None:
    """Yeni veri geldiyse mesaj gitmeli — koruma güncellemeyi engellememeli."""
    ayar = _ayar(tmp_path)
    _yakala(monkeypatch, _SahtePopen())

    assert mesajlari_gonder([mesaj], ayar) is True
    mesaj.write_text("🛒 Yeni fiyatlar", encoding="utf-8")
    assert mesajlari_gonder([mesaj], ayar) is True


def test_zorla_korumayi_deliyor(monkeypatch, mesaj, tmp_path) -> None:
    ayar = _ayar(tmp_path)
    _yakala(monkeypatch, _SahtePopen())

    assert mesajlari_gonder([mesaj], ayar) is True
    assert mesajlari_gonder([mesaj], ayar, zorla=True) is True


def test_basarisiz_gonderim_isaretlenmiyor(monkeypatch, mesaj, tmp_path) -> None:
    """Hata durumunda işaretlemek, hiç gitmemiş mesajı gitmiş saymak olurdu."""
    ayar = _ayar(tmp_path)
    _yakala(monkeypatch, _SahtePopen(kod=5, hata="patladi"))

    with pytest.raises(WhatsAppHatasi):
        mesajlari_gonder([mesaj], ayar)

    # Şimdi başarılı olsun: koruma tetiklenmemeli.
    _yakala(monkeypatch, _SahtePopen(kod=0))
    assert mesajlari_gonder([mesaj], ayar) is True


def test_bozuk_durum_dosyasi_gonderimi_durdurmuyor(monkeypatch, mesaj, tmp_path) -> None:
    """Sessizce hiç göndermemektense bir mesajı tekrar göndermek yeğdir."""
    ayar = _ayar(tmp_path)
    durum = Path(ayar.message_dir)
    durum.mkdir(parents=True, exist_ok=True)
    (durum / "gonderim-durumu.json").write_text("{bozuk", encoding="utf-8")

    _yakala(monkeypatch, _SahtePopen())
    assert mesajlari_gonder([mesaj], ayar) is True


def test_durum_dosyasi_okunabilir_json(monkeypatch, mesaj, tmp_path) -> None:
    ayar = _ayar(tmp_path)
    _yakala(monkeypatch, _SahtePopen())
    mesajlari_gonder([mesaj], ayar)

    icerik = json.loads(
        (Path(ayar.message_dir) / "gonderim-durumu.json").read_text(encoding="utf-8")
    )
    assert len(icerik["ozet"]) == 64  # sha256
    assert "zaman" in icerik


# --- süre aşımı: Chromium öksüz kalmamalı -------------------------------


def test_sure_asiminda_surec_agaci_olduruluyor(
    monkeypatch, mesaj, tmp_path, oldurulenler
) -> None:
    """Chromium torun süreç; öldürülmezse her hatada bir chrome.exe birikir."""
    _yakala(monkeypatch, _SahtePopen(sure_asimi=True))

    with pytest.raises(WhatsAppHatasi, match="süreç ağacı sonlandırıldı"):
        mesajlari_gonder([mesaj], _ayar(tmp_path))

    assert len(oldurulenler) == 1
    komut = oldurulenler[0]
    assert komut[0] == "taskkill"
    assert "/T" in komut, "/T olmadan yalnız Node ölür, Chromium kalır"
    assert "/F" in komut
    assert "4242" in komut


def test_sure_asiminda_kilit_biraktiriliyor(
    monkeypatch, mesaj, tmp_path, oldurulenler
) -> None:
    """Kilit kalsaydı sonraki koşular kalıcı olarak engellenirdi."""
    ayar = _ayar(tmp_path)
    _yakala(monkeypatch, _SahtePopen(sure_asimi=True))

    with pytest.raises(WhatsAppHatasi):
        mesajlari_gonder([mesaj], ayar)

    kilit = Path(ayar.whatsapp_session_dir) / "gonderim.lock"
    assert not kilit.exists()


def test_node_yoksa_anlamli_hata(monkeypatch, mesaj, tmp_path) -> None:
    def patlat(komut, **kw):
        raise FileNotFoundError("node")

    monkeypatch.setattr(subprocess, "Popen", patlat)
    with pytest.raises(WhatsAppHatasi, match="Node çalıştırılamadı"):
        mesajlari_gonder([mesaj], _ayar(tmp_path))


# --- kilit: iki koşu çakışmamalı ----------------------------------------


def test_kilit_gonderim_sonrasi_kalkiyor(monkeypatch, mesaj, tmp_path) -> None:
    ayar = _ayar(tmp_path)
    _yakala(monkeypatch, _SahtePopen())
    mesajlari_gonder([mesaj], ayar)

    assert not (Path(ayar.whatsapp_session_dir) / "gonderim.lock").exists()


def test_taze_kilit_varken_gonderilmiyor(monkeypatch, mesaj, tmp_path) -> None:
    """İki Node aynı Chromium profilini açarsa oturum bozulur, QR baştan istenir."""
    ayar = _ayar(tmp_path)
    kilit = Path(ayar.whatsapp_session_dir) / "gonderim.lock"
    kilit.parent.mkdir(parents=True, exist_ok=True)
    kilit.write_text("9999", encoding="utf-8")

    yakalanan = _yakala(monkeypatch, _SahtePopen())
    with pytest.raises(WhatsAppHatasi, match="Başka bir gönderim sürüyor"):
        mesajlari_gonder([mesaj], ayar)
    assert yakalanan == {}, "kilitliyken süreç açılmamalı"


def test_bayat_kilit_devraliniyor(monkeypatch, mesaj, tmp_path) -> None:
    """Tek bir çökme gönderimi kalıcı olarak durdurmamalı."""
    ayar = _ayar(tmp_path, whatsapp_timeout_sec=10)
    kilit = Path(ayar.whatsapp_session_dir) / "gonderim.lock"
    kilit.parent.mkdir(parents=True, exist_ok=True)
    kilit.write_text("9999", encoding="utf-8")

    # Kilidi bayatlat: eşik = timeout + 60 sn.
    eski = time.time() - 200
    import os as _os
    _os.utime(kilit, (eski, eski))

    _yakala(monkeypatch, _SahtePopen())
    assert mesajlari_gonder([mesaj], ayar) is True


# --- başarısızlık yutulmamalı -------------------------------------------


@pytest.mark.parametrize(("kod", "parca"), [
    (2, "yapılandırma"),
    (3, "baglan.js"),
    (4, "kayıtlı değil"),
    (5, "gönderim hatası"),
    (6, "süre aşımı"),
])
def test_cikis_kodu_anlamli_hataya_ceviriliyor(
    monkeypatch, mesaj, tmp_path, kod, parca
) -> None:
    _yakala(monkeypatch, _SahtePopen(kod=kod, hata="ayrinti"))
    with pytest.raises(WhatsAppHatasi, match=parca):
        mesajlari_gonder([mesaj], _ayar(tmp_path))


def test_bilinmeyen_kod_da_hata(monkeypatch, mesaj, tmp_path) -> None:
    _yakala(monkeypatch, _SahtePopen(kod=99))
    with pytest.raises(WhatsAppHatasi, match="99"):
        mesajlari_gonder([mesaj], _ayar(tmp_path))


# --- Node tarafıyla sözleşme --------------------------------------------


def _gonder_js() -> str:
    yol = (Path(whatsapp_sender.__file__).resolve().parents[3]
           / "whatsapp" / "gonder.js")
    return yol.read_text(encoding="utf-8")


def test_cikis_kodlari_gonder_js_ile_ayni() -> None:
    """Kodlar iki dosyada elle tutuluyor; sapma sessiz yanlış teşhis olurdu."""
    kaynak = _gonder_js()
    for kod in (2, 3, 4, 5, 6):
        assert f"return {kod};" in kaynak or f"process.exit({kod})" in kaynak


def test_gonder_js_her_cikista_tarayiciyi_kapatiyor() -> None:
    """`kapat()` çağrılmazsa Chromium öksüz kalır — Node tarafındaki asıl tuzak."""
    kaynak = _gonder_js()
    assert kaynak.count("await kapat(acikIstemci)") >= 2, (
        "hem başarı hem hata yolunda kapatılmalı"
    )


def test_gonder_js_sert_sure_asimi_tasiyor() -> None:
    """Python öldüremezse Node kendini kapatabilmeli."""
    assert "WHATSAPP_HARD_TIMEOUT_SEC" in _gonder_js()
