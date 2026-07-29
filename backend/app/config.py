"""Uygulama ayarları — tüm değerler .env'den okunur, koda sabitlenmez."""

from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# app/config.py -> app -> backend -> repo kökü
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_DIR.parent

# Mutlak yol: hangi klasörden çalıştırılırsa çalıştırılsın .env bulunur.
# Repo kökü asıl yer; backend/.env varsa o kazanır (kişisel geçersiz kılma).
_ENV_FILES = (_REPO_ROOT / ".env", _BACKEND_DIR / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Veritabanı
    database_url: str

    # marketfiyati.org.tr iç API'si (Faz 1)
    marketfiyati_base_url: str = "https://api.marketfiyati.org.tr"

    # Konum — aramanın sınırlandığı bölge. Bilerek varsayılansız: eksikse uygulama
    # açılışta hata verir. Varsayılan koymak, yanlış şehirden fiyat toplamayı SESSİZ
    # bir hataya çevirirdi (bkz. anayasa md. 13).
    # Not: konum "depots" listesiyle uygulanır; koordinat tek başına yeterli değildir.
    location_lat: float
    location_lon: float
    location_distance_km: int = 10

    # Kaynağa saygılı çekim
    collector_request_delay_sec: float = 2.0

    # Günlük toplama zamanlayıcısı. Varsayılan KAPALI: uygulamayı başlatmak
    # (test dahil) gerçek API'ye istek atmamalı. Üretimde .env'den açılır.
    pipeline_autostart: bool = False
    # Platform öğlen civarı indeksliyor (`indexTime`), sonrasında çekmek mantıklı.
    pipeline_schedule_hour: int = 13
    pipeline_schedule_minute: int = 0
    # Boş bırakılırsa sistemin yerel saati kullanılır. Elle verilecekse IANA
    # adı olmalı (ör. Europe/Istanbul) — Windows adları geçersizdir.
    pipeline_timezone: str = ""

    # Yedekleme. Varsayılan yol repo DIŞINDA: yedek gerçek fiyat/depo verisi ve
    # konum içerir, kazara commit'lenmemeli (anayasa md. 5).
    backup_dir: str = str(_REPO_ROOT.parent / "indirim-yakalar-yedek")
    backup_container: str = "indirim-yakalar-db"
    backup_retention_days: int = 30

    # Günlük koşunun WhatsApp mesajını yazacağı klasör. Boş bırakılırsa
    # `backup_dir` kullanılır — kullanıcı zaten log ve yedek için oraya bakıyor.
    message_dir: str = ""
    # Mesaj başına ürün sayısı. SPEC §7 10 diyordu; proje sahibi 29.07.2026'da
    # "dosya sayısı artmasın" diye yükseltilmesini istedi. Bölme mekanizması
    # duruyor — liste büyürse tek mesaj okunmaz hale gelmesin.
    message_item_limit: int = 100
    # Mesaj kaç günde bir üretilsin. Veri HER GÜN toplanır; bu yalnız alıcıya
    # gidecek mesajın sıklığı (proje sahibi 29.07.2026'da 3 gün istedi).
    message_interval_days: int = 3

    # --- WhatsApp gönderimi ---
    # ⚠️ Resmî API DEĞİL: kullanıcının kendi WhatsApp Web oturumu taklit edilir
    # (whatsapp-web.js). Kullanım şartlarına aykırıdır, numara kapatılma riski
    # taşır. Proje sahibi riski bilerek kabul etti (29.07.2026).
    # Varsayılan KAPALI: hiçbir kurulum kazara mesaj göndermemeli.
    whatsapp_enabled: bool = False
    # Alıcı numarası ülke koduyla, ör. 905550000000. KİŞİSEL VERİ — yalnız
    # `.env`'de durur, commit edilmez (anayasa md. 5).
    whatsapp_recipient: str = ""
    # Oturum anahtarları burada; repo DIŞINDA olmalı.
    whatsapp_session_dir: str = str(_REPO_ROOT.parent / "indirim-yakalar-oturum")
    whatsapp_node_path: str = ""
    whatsapp_chrome_path: str = ""
    # Gönderim tarayıcı açıp WhatsApp Web'i yüklüyor; yavaş makinede uzayabilir.
    whatsapp_timeout_sec: int = 240

    # Analiz (Faz 2) — para/oran karşılaştırmaları Decimal ile yapılır
    price_drop_threshold_pct: Decimal = Decimal("5.0")

    # LLM (Faz 3)
    llm_provider: str = "nvidia_nim"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_base_url: str = ""


@lru_cache
def get_settings() -> Settings:
    """Ayarlar bir kez okunur ve önbelleklenir."""
    return Settings()  # type: ignore[call-arg]
