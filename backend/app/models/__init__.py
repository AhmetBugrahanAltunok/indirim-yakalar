"""SQLAlchemy modelleri.

Alembic autogenerate'in tabloları görebilmesi için her model burada import edilir
(`migrations/env.py` yalnız `app.models`'i import eder).

Şema kararlarının gerekçeleri Obsidian kasasındadır: SPEC §5 + Notlar 26.07.2026.
"""

from app.models.market import Depot, Market
from app.models.price_history import PriceHistory
from app.models.product import Product
from app.models.raw_record import RawRecord
from app.models.setting import Setting
from app.models.watchlist import WatchlistItem, WatchlistSourceId

__all__ = [
    "Market",
    "Depot",
    "Product",
    "PriceHistory",
    "RawRecord",
    "WatchlistItem",
    "WatchlistSourceId",
    "Setting",
]
