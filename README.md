# İndirimYakalar

Market fiyatlarını otomatik toplayan, zaman içindeki fiyat düşüşlerini yakalayan ve
"şu an en ucuz nerede + ne düştü" bilgisini WhatsApp'ta paylaşılabilir sade bir mesaja
dönüştüren sistem.

> **Proje hafızası bu repo'da değil.** Spesifikasyon, faz planı ve karar kaydı ayrı bir
> Obsidian kasasında tutulur (giriş dosyası: `İndirimYakalar.md`).
> Kod ve hafıza bilerek ayrı tutulur.

**Durum:** Faz 0 tamam — iskelet ayakta, `GET /health` çalışıyor. İş mantığı yok.

## Gereksinimler

- Python 3.13 (SPEC: 3.12+)
- Docker Desktop
- Windows PowerShell

## Kurulum

```powershell
# 1) Ortam dosyası — kopyaladıktan sonra LOCATION_LAT / LOCATION_LON'u kendi
#    koordinatınla değiştir (zorunlu, varsayılanı yok).
Copy-Item .env.example .env

# 2) PostgreSQL
docker compose up -d

# 3) Backend
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 4) Şema
alembic upgrade head

# 5) Çalıştır
uvicorn app.main:app --reload
```

Sonra: <http://127.0.0.1:8000/health> → `{"status":"ok","db":true}`
API dokümanı: <http://127.0.0.1:8000/docs>

## Test

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pytest
```

## Yapı

```
indirim-yakalar/
├── backend/          # FastAPI + SQLAlchemy + Alembic
├── frontend/         # React panel (Faz 4 — henüz boş)
├── docker-compose.yml
└── .env.example
```

## Durdurma

```powershell
docker compose down        # veriyi korur
docker compose down -v     # veriyi de siler
```
