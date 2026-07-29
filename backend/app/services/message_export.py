"""WhatsApp mesajını dosyaya yazar — sistemi panelsiz kullanabilmek için.

Faz 4 paneli gelene kadar mesaja ulaşmanın tek yolu API'yi elle çağırmaktı.
Günlük koşu mesajı dosyaya da yazınca kullanım şu kadar basitleşiyor:
dosyayı aç → tümünü seç → kopyala → WhatsApp'a yapıştır.

Bu yüzden dosyada BAŞKA HİÇBİR ŞEY yok: başlık, açıklama, tarih damgası
eklenmiyor. "Tümünü seç"in doğrudan çalışması gerekiyor; dosyaya eklenen her
satır kullanıcının elle silmesi gereken bir satır olurdu.

Birden çok sayfa varsa her sayfa AYRI dosyaya yazılır. Tek dosyada birleştirmek
10 ürün sınırını (SPEC §7) anlamsız kılardı.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.services.analyzer import tum_kalemleri_analiz_et
from app.services.message_builder import whatsapp_mesajlari
from app.utils.dosya import tarihli_dosyalari_temizle
from app.utils.tarih import yerel_bugun

logger = logging.getLogger(__name__)

DOSYA_ONEKI = "mesaj-"
DOSYA_UZANTISI = ".txt"


def mesaj_dizini(settings: Settings) -> Path:
    """Mesaj klasörü. Ayarlanmamışsa yedeklerin yanına yazılır.

    Ayrı bir klasör açmak yerine bilinen klasör kullanılıyor: kullanıcı zaten
    yedekler ve log için oraya bakıyor.
    """
    ham = (settings.message_dir or "").strip() or settings.backup_dir
    return Path(ham).expanduser()


def mesaj_dosya_yolu(dizin: Path, gun: date, sayfa: int, toplam: int) -> Path:
    ek = "" if toplam == 1 else f"-{sayfa}"
    return dizin / f"{DOSYA_ONEKI}{gun.isoformat()}{ek}{DOSYA_UZANTISI}"


def mesajlari_yaz(
    db: Session,
    *,
    gun: date | None = None,
    settings: Settings | None = None,
) -> list[Path]:
    """Güncel analizden mesaj üretip dosyaya yazar. Yazılan dosyaları döner.

    Söylenecek bir şey yoksa hiçbir dosya yazılmaz — boş bir dosya bırakmak,
    kullanıcıyı açıp bakmaya sonra da boşuna uğraşmaya iterdi.
    """
    settings = settings or get_settings()
    gun = gun or yerel_bugun()

    analizler = tum_kalemleri_analiz_et(db, settings=settings)
    mesajlar = whatsapp_mesajlari(analizler, gun=gun, settings=settings)

    if not mesajlar:
        logger.info("Paylaşılacak bir şey yok — mesaj dosyası yazılmadı.")
        return []

    dizin = mesaj_dizini(settings)
    dizin.mkdir(parents=True, exist_ok=True)

    # Aynı gün daha önce daha ÇOK sayfa yazılmışsa artıklar kalmasın: dünkü
    # "-3" dosyası bugün 2 sayfa üretildiğinde yanıltıcı olurdu.
    for eski in dizin.glob(f"{DOSYA_ONEKI}{gun.isoformat()}*{DOSYA_UZANTISI}"):
        eski.unlink()

    yazilan: list[Path] = []
    for mesaj in mesajlar:
        hedef = mesaj_dosya_yolu(dizin, gun, mesaj.sayfa, mesaj.toplam_sayfa)
        # UTF-8 şart: mesaj emoji ve Türkçe karakter taşıyor.
        hedef.write_text(mesaj.metin, encoding="utf-8")
        yazilan.append(hedef)

    logger.info(
        "Mesaj yazıldı: %d dosya, %d kalem → %s",
        len(yazilan),
        sum(m.kalem_sayisi for m in mesajlar),
        dizin,
    )
    return yazilan


def eski_mesajlari_temizle(
    settings: Settings | None = None, *, gun: date | None = None
) -> list[Path]:
    """Saklama süresini aşan mesaj dosyalarını siler (.txt ve .html)."""
    settings = settings or get_settings()
    gun = gun or yerel_bugun()

    silinen: list[Path] = []
    for uzanti in (DOSYA_UZANTISI, ".html"):
        silinen.extend(tarihli_dosyalari_temizle(
            mesaj_dizini(settings),
            onek=DOSYA_ONEKI,
            uzanti=uzanti,
            gun=gun,
            saklanan_gun=settings.backup_retention_days,
        ))
    if silinen:
        logger.info("%d eski mesaj dosyası silindi", len(silinen))
    return silinen
