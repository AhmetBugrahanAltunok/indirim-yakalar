"""FastAPI uygulaması. Faz 1: sağlık kontrolü + konum (market/depo) katmanı."""

from fastapi import FastAPI

from app.api import depots, health

app = FastAPI(
    title="İndirimYakalar",
    description="Market fiyatlarını toplayan, fiyat düşüşlerini yakalayan sistem.",
    version="0.2.0",
)

app.include_router(health.router)
app.include_router(depots.router)
