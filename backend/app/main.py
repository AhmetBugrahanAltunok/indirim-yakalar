"""FastAPI uygulaması. Faz 0: yalnız iskelet + sağlık kontrolü."""

from fastapi import FastAPI

from app.api import health

app = FastAPI(
    title="İndirimYakalar",
    description="Market fiyatlarını toplayan, fiyat düşüşlerini yakalayan sistem.",
    version="0.1.0",
)

app.include_router(health.router)
