"""Veritabanı yedeği — `pg_dump` ile tek dosyaya.

Neden var: 27.07.2026'da Docker Desktop'ın `pgdata` volume'ü ikinci kez yok
oldu ve 26.07'nin 115 fiyat kaydı kalıcı olarak gitti. Platform yalnız GÜNCEL
fiyatı döndürüyor — geçmişe dönük sorgu yok, kaçan gün tekrar toplanamaz
(bkz. [[Gotchas]]). Bu yüzden veri tek bir Docker volume'ünde bırakılmaz.

Yedek repo DIŞINA yazılır: gerçek fiyat/depo verisi ve konum içerir, commit
edilmez (anayasa md. 5).

⚠️ `docker exec` çağrısında `-t` KULLANILMAZ: TTY ayrılırsa çıktıdaki her
satır sonuna CR eklenir ve dump `psql` ile geri yüklenemeyecek şekilde bozulur.
Bozulma sessizdir — dosya oluşur, boyutu makul görünür.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

from sqlalchemy.engine import make_url

from app.config import Settings, get_settings
from app.utils.dosya import tarihli_dosyalari_temizle
from app.utils.tarih import yerel_bugun

logger = logging.getLogger(__name__)

DOSYA_ONEKI = "indirim-yakalar-"
DOSYA_UZANTISI = ".sql"

# Komutu çalıştırıp (donus_kodu, hata_metni) döndüren çağrılabilir.
# Testlerde gerçek Docker'a çıkmamak için dışarıdan verilebilir.
Calistirici = Callable[[Sequence[str], Path], tuple[int, str]]


class YedekHatasi(RuntimeError):
    """Yedek alınamadı — çağıran karar verir (koşu iptal mi, uyarı mı)."""


def _varsayilan_calistirici(komut: Sequence[str], hedef: Path) -> tuple[int, str]:
    with hedef.open("wb") as dosya:
        sonuc = subprocess.run(
            list(komut),
            stdout=dosya,
            stderr=subprocess.PIPE,
            check=False,
        )
    return sonuc.returncode, sonuc.stderr.decode("utf-8", errors="replace")


def yedek_dosya_yolu(dizin: Path, gun: date) -> Path:
    return dizin / f"{DOSYA_ONEKI}{gun.isoformat()}{DOSYA_UZANTISI}"


def _yedek_dizini(settings: Settings) -> Path:
    """Yedek klasörü. Boş ayar sessizce çalışma klasörüne yazmaya dönüşmez.

    `.env`'de `BACKUP_DIR=` (boş) yazmak pydantic için geçerli bir değerdir ve
    varsayılanı devre dışı bırakır; `Path("")` de çalışma klasörünü gösterir.
    Yedeğin nereye gittiğinin bilinmemesi, yedek olmamasıyla aynı şeydir.
    """
    ham = (settings.backup_dir or "").strip()
    if not ham:
        raise YedekHatasi(
            "BACKUP_DIR boş. Yedek klasörü belirtilmeli — .env'deki satırı "
            "yorumda bırakırsan varsayılan kullanılır."
        )
    return Path(ham).expanduser()


def yedek_al(
    settings: Settings | None = None,
    *,
    gun: date | None = None,
    calistirici: Calistirici | None = None,
) -> Path:
    """Veritabanını `<backup_dir>/indirim-yakalar-YYYY-MM-DD.sql` dosyasına döker.

    Aynı gün ikinci kez çalışırsa dosya üzerine yazılır — günde bir yedek yeter
    ve klasör şişmez. Eski yedekler `backup_retention_days` sonrası silinir.
    """
    settings = settings or get_settings()
    gun = gun or yerel_bugun()
    calistirici = calistirici or _varsayilan_calistirici

    dizin = _yedek_dizini(settings)
    dizin.mkdir(parents=True, exist_ok=True)
    hedef = yedek_dosya_yolu(dizin, gun)

    url = make_url(settings.database_url)
    komut = [
        "docker", "exec", "-i", settings.backup_container,
        "pg_dump", "-U", url.username or "postgres", "-d", url.database or "postgres",
        # --clean --if-exists: dump kendi DROP'larını taşır. Böylece geri yükleme
        # `alembic upgrade head` sonrası (yani tabloların var olduğu) bir veritabanına
        # da yapılabilir; aksi halde felaket anında önce elle temizlemek gerekirdi.
        "--clean", "--if-exists",
    ]

    donus_kodu, hata = calistirici(komut, hedef)

    if donus_kodu != 0:
        # Yarım dosya bırakılmaz: var sanılıp güvenilmesi, hiç olmamasından kötüdür.
        hedef.unlink(missing_ok=True)
        raise YedekHatasi(
            f"pg_dump başarısız (kod {donus_kodu}): {hata.strip() or 'çıktı yok'}"
        )

    if not hedef.exists() or hedef.stat().st_size == 0:
        hedef.unlink(missing_ok=True)
        raise YedekHatasi("pg_dump boş dosya üretti — yedek geçersiz sayıldı.")

    logger.info("Yedek alındı: %s (%d bayt)", hedef, hedef.stat().st_size)
    return hedef


def en_yeni_yedek(settings: Settings | None = None) -> Path | None:
    """Yedek klasöründeki en güncel dump. Yoksa None."""
    settings = settings or get_settings()
    dizin = _yedek_dizini(settings)
    if not dizin.exists():
        return None
    adaylar = sorted(dizin.glob(f"{DOSYA_ONEKI}*{DOSYA_UZANTISI}"))
    return adaylar[-1] if adaylar else None


def geri_yukle(
    kaynak: Path,
    settings: Settings | None = None,
    *,
    calistirici: Calistirici | None = None,
) -> None:
    """Dump dosyasını veritabanına geri yükler.

    ⚠️ Yıkıcı: dump `--clean` ile alındığı için mevcut tablolar DÜŞÜRÜLÜP
    yeniden kurulur. Çağıran onay almış olmalıdır.

    `ON_ERROR_STOP=1` şart: olmazsa psql hatalı satırları atlayıp 0 döner ve
    yarım yüklenmiş bir veritabanı başarılı sanılır.
    """
    settings = settings or get_settings()
    calistirici = calistirici or _geri_yukle_calistirici

    if not kaynak.exists() or kaynak.stat().st_size == 0:
        raise YedekHatasi(f"Yedek dosyası yok ya da boş: {kaynak}")

    url = make_url(settings.database_url)
    komut = [
        "docker", "exec", "-i", settings.backup_container,
        "psql", "-U", url.username or "postgres", "-d", url.database or "postgres",
        "-v", "ON_ERROR_STOP=1",
    ]

    donus_kodu, hata = calistirici(komut, kaynak)
    if donus_kodu != 0:
        raise YedekHatasi(
            f"psql geri yükleme başarısız (kod {donus_kodu}): "
            f"{hata.strip() or 'çıktı yok'}"
        )
    logger.info("Yedek geri yüklendi: %s", kaynak)


def _geri_yukle_calistirici(komut: Sequence[str], kaynak: Path) -> tuple[int, str]:
    with kaynak.open("rb") as dosya:
        sonuc = subprocess.run(
            list(komut),
            stdin=dosya,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
        )
    return sonuc.returncode, sonuc.stderr.decode("utf-8", errors="replace")


def eski_yedekleri_temizle(
    settings: Settings | None = None, *, gun: date | None = None
) -> list[Path]:
    """Saklama süresini aşan yedekleri siler. Silinenlerin listesini döner."""
    settings = settings or get_settings()
    gun = gun or yerel_bugun()

    silinen = tarihli_dosyalari_temizle(
        _yedek_dizini(settings),
        onek=DOSYA_ONEKI,
        uzanti=DOSYA_UZANTISI,
        gun=gun,
        saklanan_gun=settings.backup_retention_days,
    )
    if silinen:
        logger.info("%d eski yedek silindi", len(silinen))
    return silinen
