"""FastAPI uygulaması. Faz 1: sağlık + konum + takip listesi + pipeline."""

from fastapi import FastAPI

from app.api import depots, health, pipeline, watchlist

app = FastAPI(
    title="İndirimYakalar",
    description="Market fiyatlarını toplayan, fiyat düşüşlerini yakalayan sistem.",
    version="0.4.0",
)

app.include_router(health.router)
app.include_router(depots.router)
app.include_router(watchlist.router)
app.include_router(pipeline.router)
