"""FastAPI uygulaması. Faz 1: sağlık + konum (market/depo) + takip listesi."""

from fastapi import FastAPI

from app.api import depots, health, watchlist

app = FastAPI(
    title="İndirimYakalar",
    description="Market fiyatlarını toplayan, fiyat düşüşlerini yakalayan sistem.",
    version="0.3.0",
)

app.include_router(health.router)
app.include_router(depots.router)
app.include_router(watchlist.router)
