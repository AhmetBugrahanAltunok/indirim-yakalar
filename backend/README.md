# Backend

FastAPI + SQLAlchemy 2.x + Alembic + PostgreSQL. Kurulum adımları kök `README.md`'de.

## Klasörler

| Klasör | İş |
|---|---|
| `app/api/` | Router'lar. **İş mantığı yazılmaz**, `services/`'e delege edilir. |
| `app/services/` | İş mantığı (normalizer, product_identity, analyzer, message_builder — Faz 1-2) |
| `app/collectors/` | Veri kaynağı adaptörleri (marketfiyati — Faz 1; broşür — Faz 3) |
| `app/models/` | SQLAlchemy modelleri (Faz 1) |
| `app/schemas/` | Pydantic şemaları |
| `app/llm/` | VisionExtractor arayüzü + sağlayıcılar (Faz 3) |
| `app/database/` | Motor, oturum, taban sınıf |
| `app/utils/` | Yardımcılar |
| `migrations/` | Alembic revizyonları |
| `tests/` | pytest |

## Alembic

```powershell
alembic upgrade head                        # şemayı güncelle
alembic revision --autogenerate -m "aciklama"   # model değişince yeni revizyon
alembic downgrade -1                        # bir adım geri
```

Bağlantı adresi `alembic.ini`'de **tutulmaz**; `migrations/env.py` `.env`'den okur.

## Dikkat edilecekler

- **Para `Decimal`.** API fiyatları JSON'da float gelir; collector `json.loads(..., parse_float=Decimal)` kullanır.
- **Türkçe normalizasyon:** `casefold()` öncesi `I→ı, İ→i` dönüşümü yapılır.
- **API kuralları (Faz 1):** yalnız POST, yalnız bilinen uç nokta/alanlar, istekler arası
  bekleme, `HTTP 418` görülürse derhal durulur. Konum `depots` listesiyle uygulanır.
  Ayrıntı: kasadaki `Kaynaklar/Veri-Kaynaklari.md`.
