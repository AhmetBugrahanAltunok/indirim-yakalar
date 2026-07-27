"""Yedekleme testleri — gerçek Docker'a çıkmadan.

Yedek, 26.07.2026'nın verisini kaybettiren volume silinmesine karşı tek
savunma. Bu yüzden sessiz başarısızlık senaryoları burada özellikle kovalanıyor:
yarım dosya bırakmak, boş dosya üretmek, hatayı yutmak.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.config import Settings, get_settings
from app.services import backup
from app.services.backup import (
    YedekHatasi,
    eski_yedekleri_temizle,
    en_yeni_yedek,
    geri_yukle,
    yedek_al,
)

GUN = date(2026, 7, 27)


def _ayar(tmp_path: Path, saklanan_gun: int = 30) -> Settings:
    return get_settings().model_copy(update={
        "backup_dir": str(tmp_path),
        "backup_container": "test-db",
        "backup_retention_days": saklanan_gun,
    })


def _basarili(icerik: bytes = b"-- dump\n"):
    """Komutu çalıştırmış gibi yapıp dosyayı yazan sahte çalıştırıcı."""
    yakalanan: dict[str, list[str]] = {}

    def calistirici(komut, hedef: Path):
        yakalanan["komut"] = list(komut)
        hedef.write_bytes(icerik)
        return 0, ""

    return calistirici, yakalanan


# --- dump alma -----------------------------------------------------------


def test_dosya_adi_gunun_tarihini_tasiyor(tmp_path) -> None:
    calistirici, _ = _basarili()
    hedef = yedek_al(_ayar(tmp_path), gun=GUN, calistirici=calistirici)
    assert hedef.name == "indirim-yakalar-2026-07-27.sql"
    assert hedef.exists()


def test_docker_exec_tty_ile_cagrilmiyor(tmp_path) -> None:
    """`-t` verilirse dump'a CR eklenir ve geri yükleme SESSİZCE bozulur."""
    calistirici, yakalanan = _basarili()
    yedek_al(_ayar(tmp_path), gun=GUN, calistirici=calistirici)
    komut = yakalanan["komut"]
    assert "-i" in komut
    assert "-t" not in komut
    assert "-it" not in komut


def test_dump_kendi_droplarini_tasiyor(tmp_path) -> None:
    """--clean --if-exists olmadan dolu bir veritabanına geri yüklenemezdi."""
    calistirici, yakalanan = _basarili()
    yedek_al(_ayar(tmp_path), gun=GUN, calistirici=calistirici)
    assert "--clean" in yakalanan["komut"]
    assert "--if-exists" in yakalanan["komut"]


def test_ayni_gun_ikinci_kosu_uzerine_yaziyor(tmp_path) -> None:
    calistirici, _ = _basarili()
    ilk = yedek_al(_ayar(tmp_path), gun=GUN, calistirici=calistirici)
    ikinci = yedek_al(_ayar(tmp_path), gun=GUN, calistirici=calistirici)
    assert ilk == ikinci
    assert len(list(tmp_path.glob("*.sql"))) == 1


def test_hedef_dizin_yoksa_olusturuluyor(tmp_path) -> None:
    calistirici, _ = _basarili()
    dizin = tmp_path / "henuz" / "yok"
    ayar = get_settings().model_copy(update={"backup_dir": str(dizin)})
    yedek_al(ayar, gun=GUN, calistirici=calistirici)
    assert dizin.exists()


# --- başarısızlık: sessiz geçilmemeli ------------------------------------


def test_pg_dump_hata_verirse_yarim_dosya_birakilmiyor(tmp_path) -> None:
    """Yarım yedek, hiç yedek olmamasından kötüdür: var sanılıp güvenilir."""
    def calistirici(komut, hedef: Path):
        hedef.write_bytes(b"yarim")
        return 1, "connection refused"

    with pytest.raises(YedekHatasi, match="connection refused"):
        yedek_al(_ayar(tmp_path), gun=GUN, calistirici=calistirici)

    assert list(tmp_path.glob("*.sql")) == []


def test_bos_dosya_gecerli_yedek_sayilmiyor(tmp_path) -> None:
    calistirici, _ = _basarili(icerik=b"")
    with pytest.raises(YedekHatasi, match="boş"):
        yedek_al(_ayar(tmp_path), gun=GUN, calistirici=calistirici)
    assert list(tmp_path.glob("*.sql")) == []


# --- saklama süresi ------------------------------------------------------


def _yedek_yaz(dizin: Path, gun: str) -> Path:
    yol = dizin / f"indirim-yakalar-{gun}.sql"
    yol.write_text("-- dump", encoding="utf-8")
    return yol


def test_suresi_gecen_yedek_siliniyor(tmp_path) -> None:
    eski = _yedek_yaz(tmp_path, "2026-01-01")
    yeni = _yedek_yaz(tmp_path, "2026-07-26")
    silinen = eski_yedekleri_temizle(_ayar(tmp_path, saklanan_gun=30), gun=GUN)
    assert silinen == [eski]
    assert not eski.exists()
    assert yeni.exists()


def test_sinirdaki_yedek_korunuyor(tmp_path) -> None:
    """Tam saklama sınırındaki gün silinmez — sınır dahildir."""
    sinirdaki = _yedek_yaz(tmp_path, "2026-06-27")  # GUN - 30
    eski_yedekleri_temizle(_ayar(tmp_path, saklanan_gun=30), gun=GUN)
    assert sinirdaki.exists()


def test_tanimadigimiz_dosyaya_dokunulmuyor(tmp_path) -> None:
    """Desenimize uymayan dosya bizim değildir; silmek veri kaybı olur."""
    yabanci = tmp_path / "onemli-notlar.sql"
    yabanci.write_text("dokunma", encoding="utf-8")
    bozuk = _yedek_yaz(tmp_path, "tarih-degil")

    eski_yedekleri_temizle(_ayar(tmp_path, saklanan_gun=1), gun=GUN)

    assert yabanci.exists()
    assert bozuk.exists()


def test_dizin_yoksa_temizlik_patlamiyor(tmp_path) -> None:
    ayar = get_settings().model_copy(update={"backup_dir": str(tmp_path / "yok")})
    assert eski_yedekleri_temizle(ayar, gun=GUN) == []


# --- yanlış yapılandırma -------------------------------------------------


@pytest.mark.parametrize("deger", ["", "   "])
def test_bos_backup_dir_reddediliyor(deger) -> None:
    """Boş ayar sessizce çalışma klasörüne yazmaya dönüşmemeli."""
    ayar = get_settings().model_copy(update={"backup_dir": deger})
    with pytest.raises(YedekHatasi, match="BACKUP_DIR"):
        yedek_al(ayar, gun=GUN, calistirici=_basarili()[0])


# --- en yeni yedek -------------------------------------------------------


def test_en_yeni_yedek_secildi(tmp_path) -> None:
    _yedek_yaz(tmp_path, "2026-07-25")
    beklenen = _yedek_yaz(tmp_path, "2026-07-27")
    _yedek_yaz(tmp_path, "2026-07-26")
    assert en_yeni_yedek(_ayar(tmp_path)) == beklenen


def test_yedek_yoksa_none(tmp_path) -> None:
    assert en_yeni_yedek(_ayar(tmp_path)) is None


# --- geri yükleme --------------------------------------------------------


def test_geri_yukleme_hata_durdurma_ile_cagriliyor(tmp_path) -> None:
    """ON_ERROR_STOP olmadan psql hatalı satırı atlar ve 0 döner —
    yarım yüklenmiş veritabanı başarılı sanılırdı."""
    kaynak = _yedek_yaz(tmp_path, "2026-07-27")
    yakalanan: dict[str, list[str]] = {}

    def calistirici(komut, gelen: Path):
        yakalanan["komut"] = list(komut)
        return 0, ""

    geri_yukle(kaynak, _ayar(tmp_path), calistirici=calistirici)
    assert "ON_ERROR_STOP=1" in yakalanan["komut"]
    assert "psql" in yakalanan["komut"]


def test_olmayan_dosyadan_geri_yukleme_reddediliyor(tmp_path) -> None:
    with pytest.raises(YedekHatasi, match="yok ya da boş"):
        geri_yukle(tmp_path / "yok.sql", _ayar(tmp_path))


def test_bos_dosyadan_geri_yukleme_reddediliyor(tmp_path) -> None:
    bos = tmp_path / "bos.sql"
    bos.touch()
    with pytest.raises(YedekHatasi, match="yok ya da boş"):
        geri_yukle(bos, _ayar(tmp_path))


def test_psql_hatasi_yutulmuyor(tmp_path) -> None:
    kaynak = _yedek_yaz(tmp_path, "2026-07-27")

    def calistirici(komut, gelen: Path):
        return 1, "relation already exists"

    with pytest.raises(YedekHatasi, match="relation already exists"):
        geri_yukle(kaynak, _ayar(tmp_path), calistirici=calistirici)
