"""Mesaj dosyalarını WhatsApp'tan gönderir (`whatsapp/gonder.js` üzerinden).

⚠️ Resmî API DEĞİL. Meta'nın Cloud API'si bu kullanıma kapalı: konuşmayı
gönderen başlatıyorsa şablon zorunlu, şablon değişkenlerinde **satır başı
yasak**, gövde 1024 karakterle sınırlı. Bizim mesajımız 100+ satır. Serbest
metin yalnız alıcı son 24 saatte yazmışsa mümkün. Bu yüzden kullanıcının kendi
WhatsApp Web oturumu kullanılıyor (whatsapp-web.js).

Bu yol WhatsApp'ın kullanım şartlarına aykırıdır ve numaranın kapatılma riskini
taşır. Proje sahibi riski bilerek kabul etti (29.07.2026, bkz. [[Notlar]]).

Node tarafı ayrı süreçte koşuyor: whatsapp-web.js bir tarayıcı sürüyor ve
Python'dan yönetilmesi anlamsız bir bağımlılık olurdu. İletişim çıkış koduyla.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

# gonder.js ile birebir aynı olmalı — orada da belgeli.
CIKIS_KODLARI = {
    0: "gönderildi",
    2: "yapılandırma hatası",
    3: "oturum yok — `node whatsapp/baglan.js` çalıştırılmalı",
    4: "alıcı WhatsApp'ta kayıtlı değil",
    5: "gönderim hatası",
    6: "süre aşımı",
}

_REPO_KOKU = Path(__file__).resolve().parents[3]
_GONDER_JS = _REPO_KOKU / "whatsapp" / "gonder.js"


class WhatsAppHatasi(RuntimeError):
    """Gönderim başarısız. Çağıran koşuyu düşürmez, loglar."""


def _node_yolu(settings: Settings) -> str:
    """Node yürütülebiliri. Ayarlanmamışsa PATH'teki `node`.

    Kasadaki hook'lar sürümü sabitliyor ([[Gotchas]]); burada da sabitlemek
    isteyen `.env`'den verir.
    """
    return (settings.whatsapp_node_path or "").strip() or "node"


def gonderilebilir_mi(settings: Settings | None = None) -> tuple[bool, str]:
    """(gönderilebilir, neden). Kapalıysa ya da eksik yapılandırma varsa False."""
    settings = settings or get_settings()

    if not settings.whatsapp_enabled:
        return False, "WHATSAPP_ENABLED kapalı"
    if not (settings.whatsapp_recipient or "").strip():
        return False, "WHATSAPP_RECIPIENT boş"
    if not _GONDER_JS.exists():
        return False, f"gonder.js bulunamadı: {_GONDER_JS}"
    if not (_GONDER_JS.parent / "node_modules").exists():
        return False, "whatsapp/node_modules yok — `npm install` gerekli"
    return True, "hazır"


def mesajlari_gonder(
    dosyalar: list[Path], settings: Settings | None = None
) -> bool:
    """Verilen mesaj dosyalarını gönderir. Gönderildiyse True.

    Kapalı ya da eksik yapılandırmada sessizce False döner — bu bir hata
    değil, bilinçli bir durum. Gerçek başarısızlıkta `WhatsAppHatasi` atar.
    """
    settings = settings or get_settings()

    uygun, neden = gonderilebilir_mi(settings)
    if not uygun:
        logger.info("WhatsApp gönderimi atlandı: %s", neden)
        return False

    if not dosyalar:
        logger.info("WhatsApp gönderimi atlandı: gönderilecek dosya yok")
        return False

    ortam = {
        "WHATSAPP_RECIPIENT": settings.whatsapp_recipient.strip(),
        "WHATSAPP_SESSION_DIR": settings.whatsapp_session_dir,
        "WHATSAPP_CHROME_PATH": settings.whatsapp_chrome_path,
    }

    try:
        sonuc = subprocess.run(
            [_node_yolu(settings), str(_GONDER_JS), *[str(d) for d in dosyalar]],
            cwd=str(_GONDER_JS.parent),
            env=_ortami_kur(ortam),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=settings.whatsapp_timeout_sec,
            check=False,
        )
    except FileNotFoundError as hata:
        raise WhatsAppHatasi(f"Node çalıştırılamadı: {hata}") from hata
    except subprocess.TimeoutExpired as hata:
        raise WhatsAppHatasi(
            f"Gönderim {settings.whatsapp_timeout_sec} sn içinde bitmedi"
        ) from hata

    for satir in (sonuc.stdout or "").splitlines():
        logger.info("whatsapp: %s", satir)

    if sonuc.returncode != 0:
        aciklama = CIKIS_KODLARI.get(sonuc.returncode, f"bilinmeyen kod {sonuc.returncode}")
        raise WhatsAppHatasi(f"{aciklama} — {(sonuc.stderr or '').strip()}")

    logger.info("WhatsApp: %d mesaj gönderildi", len(dosyalar))
    return True


def _ortami_kur(ek: dict[str, str]) -> dict[str, str]:
    """Süreç ortamı + bizim değişkenler.

    Mevcut ortam korunuyor: Node'un PATH, SystemRoot ve TEMP'e ihtiyacı var,
    boş bir ortamla Windows'ta açılmıyor.
    """
    import os

    ortam = dict(os.environ)
    ortam.update({k: v for k, v in ek.items() if v})
    return ortam
