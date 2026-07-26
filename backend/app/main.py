"""FastAPI uygulaması. Faz 1: sağlık + konum + takip listesi + pipeline."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import scheduler
from app.api import depots, health, pipeline, watchlist

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def yasam_dongusu(app: FastAPI) -> AsyncIterator[None]:
    """Zamanlayıcı uygulama ile birlikte açılıp kapanır.

    `PIPELINE_AUTOSTART` kapalıysa hiçbir şey başlamaz — geliştirme ve test
    sırasında uygulamayı açmak gerçek API'ye istek atmamalı.
    """
    scheduler.baslat()
    try:
        yield
    finally:
        scheduler.durdur()


app = FastAPI(
    title="İndirimYakalar",
    description="Market fiyatlarını toplayan, fiyat düşüşlerini yakalayan sistem.",
    version="0.5.0",
    lifespan=yasam_dongusu,
)

app.include_router(health.router)
app.include_router(depots.router)
app.include_router(watchlist.router)
app.include_router(pipeline.router)
