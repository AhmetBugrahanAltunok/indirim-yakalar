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
