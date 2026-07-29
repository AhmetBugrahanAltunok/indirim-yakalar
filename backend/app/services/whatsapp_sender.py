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

import hashlib
import json
import logging
import os
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from app.config import Settings, get_settings
from app.services.message_export import mesaj_dizini

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


def _kurulum_durumu() -> tuple[bool, str]:
    """Node tarafı kurulu mu.

    Ayrı fonksiyon: gönderim mantığının testleri bu kontrolü değiştirebilsin.
    Aksi halde testler `whatsapp/node_modules`'ün varlığına bağlı olurdu —
    geliştirme makinesinde geçip CI'da düşen, yani değeri sahte testler.
    """
    if not _GONDER_JS.exists():
        return False, f"gonder.js bulunamadı: {_GONDER_JS}"
    if not (_GONDER_JS.parent / "node_modules").exists():
        return False, "whatsapp/node_modules yok — `npm install` gerekli"
    return True, "kurulu"


def gonderilebilir_mi(settings: Settings | None = None) -> tuple[bool, str]:
    """(gönderilebilir, neden). Kapalıysa ya da eksik yapılandırma varsa False."""
    settings = settings or get_settings()

    if not settings.whatsapp_enabled:
        return False, "WHATSAPP_ENABLED kapalı"
    if not (settings.whatsapp_recipient or "").strip():
        return False, "WHATSAPP_RECIPIENT boş"

    kurulu, neden = _kurulum_durumu()
    if not kurulu:
        return False, neden
    return True, "hazır"


def _icerik_ozeti(dosyalar: list[Path]) -> str:
    """Gönderilecek metnin parmak izi. Aynı içerik iki kez gönderilmesin diye."""
    ozet = hashlib.sha256()
    for dosya in dosyalar:
        ozet.update(dosya.read_bytes())
        ozet.update(b"\0")
    return ozet.hexdigest()


def _durum_dosyasi(settings: Settings) -> Path:
    return mesaj_dizini(settings) / "gonderim-durumu.json"


def _son_gonderilen(settings: Settings) -> str | None:
    yol = _durum_dosyasi(settings)
    if not yol.exists():
        return None
    try:
        return json.loads(yol.read_text(encoding="utf-8")).get("ozet")
    except (json.JSONDecodeError, OSError):
        # Bozuk durum dosyası gönderimi engellememeli; en kötü ihtimalle
        # bir mesaj tekrar gider, bu sessizce hiç gitmemesinden iyidir.
        return None


def _gonderildi_isaretle(settings: Settings, ozet: str) -> None:
    yol = _durum_dosyasi(settings)
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_text(
        json.dumps(
            {"ozet": ozet, "zaman": datetime.now().isoformat(timespec="seconds")},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


@contextmanager
def _kilit(settings: Settings):
    """Aynı anda iki gönderim çalışmasın.

    İki Node süreci aynı Chromium profilini açarsa oturum bozulur ve QR'ı
    baştan okutmak gerekir. Görev Zamanlayıcı `IgnoreNew` ile korunuyor ama
    elle çalıştırma bunu deler.

    Bayat kilit (süreç çökmüş, dosya kalmış) devralınır: aksi halde tek bir
    çökme gönderimi kalıcı olarak durdururdu.
    """
    yol = Path(settings.whatsapp_session_dir).expanduser() / "gonderim.lock"
    yol.parent.mkdir(parents=True, exist_ok=True)

    if yol.exists():
        yas = time.time() - yol.stat().st_mtime
        if yas < settings.whatsapp_timeout_sec + 60:
            raise WhatsAppHatasi(
                f"Başka bir gönderim sürüyor ({int(yas)} sn önce başladı)"
            )
        logger.warning("Bayat kilit devralındı (%d sn)", yas)

    yol.write_text(str(os.getpid()), encoding="utf-8")
    try:
        yield
    finally:
        yol.unlink(missing_ok=True)


def mesajlari_gonder(
    dosyalar: list[Path],
    settings: Settings | None = None,
    *,
    zorla: bool = False,
) -> bool:
    """Verilen mesaj dosyalarını gönderir. Gönderildiyse True.

    Kapalı ya da eksik yapılandırmada sessizce False döner — bu bir hata
    değil, bilinçli bir durum. Gerçek başarısızlıkta `WhatsAppHatasi` atar.

    Aynı içerik daha önce gönderildiyse tekrar gönderilmez: günlük koşu aynı
    gün ikinci kez çalıştığında alıcı aynı mesajı iki kez alırdı. `zorla=True`
    bu korumayı devre dışı bırakır.
    """
    settings = settings or get_settings()

    uygun, neden = gonderilebilir_mi(settings)
    if not uygun:
        logger.info("WhatsApp gönderimi atlandı: %s", neden)
        return False

    if not dosyalar:
        logger.info("WhatsApp gönderimi atlandı: gönderilecek dosya yok")
        return False

    ozet = _icerik_ozeti(dosyalar)
    if not zorla and ozet == _son_gonderilen(settings):
        logger.info("WhatsApp gönderimi atlandı: aynı mesaj zaten gönderildi")
        return False

    ortam = {
        "WHATSAPP_RECIPIENT": settings.whatsapp_recipient.strip(),
        "WHATSAPP_SESSION_DIR": settings.whatsapp_session_dir,
        "WHATSAPP_CHROME_PATH": settings.whatsapp_chrome_path,
        # Node kendini Python'un zorla öldürmesinden ÖNCE kapatsın: kendi
        # kapanışında Chromium'u düzgünce sonlandırır, taskkill ise sert keser.
        "WHATSAPP_HARD_TIMEOUT_SEC": str(max(30, settings.whatsapp_timeout_sec - 30)),
    }

    with _kilit(settings):
        kod, cikti, hata_metni = _node_calistir(
            [_node_yolu(settings), str(_GONDER_JS), *[str(d) for d in dosyalar]],
            ortam=_ortami_kur(ortam),
            sure_sn=settings.whatsapp_timeout_sec,
        )

    for satir in (cikti or "").splitlines():
        logger.info("whatsapp: %s", satir)

    if kod != 0:
        aciklama = CIKIS_KODLARI.get(kod, f"bilinmeyen kod {kod}")
        raise WhatsAppHatasi(f"{aciklama} — {(hata_metni or '').strip()}")

    # İşaret ancak gönderim BAŞARILI olunca konur: hata durumunda işaretlemek,
    # hiç gitmemiş mesajı gitmiş saymak olurdu.
    _gonderildi_isaretle(settings, ozet)
    logger.info("WhatsApp: %d mesaj gönderildi", len(dosyalar))
    return True


def _node_calistir(
    komut: list[str], *, ortam: dict[str, str], sure_sn: int
) -> tuple[int, str, str]:
    """Node'u çalıştırır. (çıkış kodu, stdout, stderr).

    ⚠️ Süre aşımında SÜREÇ AĞACININ TAMAMI öldürülür. `subprocess.run(timeout=)`
    yalnız doğrudan çocuğu öldürür; Node'un başlattığı Chromium torun süreç
    olduğu için hayatta kalır. Her hatada bir `chrome.exe` birikir ve makine
    haftalar içinde yavaşlar — sessiz, yavaş büyüyen bir arıza.
    """
    try:
        surec = subprocess.Popen(
            komut,
            cwd=str(_GONDER_JS.parent),
            env=ortam,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as hata:
        raise WhatsAppHatasi(f"Node çalıştırılamadı: {hata}") from hata

    try:
        cikti, hata_metni = surec.communicate(timeout=sure_sn)
    except subprocess.TimeoutExpired:
        _surec_agacini_oldur(surec.pid)
        surec.communicate()
        raise WhatsAppHatasi(
            f"Gönderim {sure_sn} sn içinde bitmedi — süreç ağacı sonlandırıldı"
        ) from None

    return surec.returncode, cikti, hata_metni


def _surec_agacini_oldur(pid: int) -> None:
    """Süreci ve tüm alt süreçlerini sonlandırır (Windows: taskkill /T)."""
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=30,
            check=False,
        )
        logger.warning("WhatsApp süreç ağacı sonlandırıldı (pid %s)", pid)
    except Exception as hata:  # noqa: BLE001 — temizlik asıl hatayı gölgelememeli
        logger.error("Süreç ağacı sonlandırılamadı (pid %s): %s", pid, hata)


def _ortami_kur(ek: dict[str, str]) -> dict[str, str]:
    """Süreç ortamı + bizim değişkenler.

    Mevcut ortam korunuyor: Node'un PATH, SystemRoot ve TEMP'e ihtiyacı var,
    boş bir ortamla Windows'ta açılmıyor.
    """
    ortam = dict(os.environ)
    ortam.update({k: v for k, v in ek.items() if v})
    return ortam
