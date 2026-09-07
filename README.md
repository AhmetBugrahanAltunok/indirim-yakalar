# İndirimYakalar

[![Testler](https://github.com/AhmetBugrahanAltunok/indirim-yakalar/actions/workflows/testler.yml/badge.svg)](https://github.com/AhmetBugrahanAltunok/indirim-yakalar/actions/workflows/testler.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A personal system that collects Turkish grocery prices daily, finds the cheapest
chain for each tracked product and any price drops over time, then turns the
result into a plain WhatsApp message you can share.

Prices come from [marketfiyati.org.tr](https://marketfiyati.org.tr), a public
price-comparison platform covering the major Turkish grocery chains. You define a
watchlist (a 76-item starter list ships with the project), the system pulls prices
every day and every few days produces a "cheapest right now, and what dropped"
message.

**Stack:** FastAPI · PostgreSQL 16 · SQLAlchemy 2.x · Alembic · APScheduler · pytest

## What it produces

Output is Turkish, since that's who the message is for:

```
🛒 *Son Gözlem — Market Fiyatları*
📅 28.07.2026

*Muratbey Tam Yağlı Taze Kaşar 500 g*
✅ En uygun: *CarrefourSA — 299,95 TL*
A101: 449,00 TL
Migros: 499,90 TL
────────────
*Carrefour Kaşar Peyniri 500 g*
ℹ️ Yalnızca CarrefourSA: *199,00 TL*
🔻 Düştü (%12,5): 27.07.2026 227,50 TL → 28.07.2026 199,00 TL
────────────
*Çaykur Rize Turist Çay 1 kg*
✅ En uygun: *A101 / BİM / ŞOK — 365,00 TL*
CarrefourSA: 369,95 TL
Migros: 399,95 TL
────────────
```

The message is written to a text file and to a clickable HTML page. The page's
button opens WhatsApp with the message pre-filled — you decide whether to send it.

## Why it's interesting

The platform's data is not what it looks like at first glance. Most of this
project's design comes from findings made while working with real data:

**The same physical product can live in several catalog records.** The platform
builds its catalog per chain and doesn't always merge them. Duplicate records have
**disjoint depot sets**, and each record declares its own "cheapest" within itself.
A user looking at a single record can be pointed to a price 8.3% higher than what's
actually available. So here a watchlist item links to 1..N platform records, and
the cheapest price is computed across all of them.

**Branches of the same chain can quote different prices** — a 27% spread was
observed between two branches of one chain for the same product. The system takes
the cheapest branch per chain and never claims a specific branch in the message.

**Search results drift between days.** A keyword query returned 5 of 7 products the
next day — but every one of those product IDs was still alive when queried
directly. So tracking is done by **product identity**, never by keyword. ID
persistence across days was verified before relying on it.

**A product's depot set moves too.** The same product appeared under one branch on
one day and a different branch the next, at an identical price. Time series are
therefore built at chain level, not depot level — a naive depot-level view would
show phantom gaps.

## How it works

```
gunluk_kosu.py  (daily, via Windows Task Scheduler)
   │
   ├─ collect ..... platform API per tracked ID → raw_records (verbatim, untouched)
   ├─ ingest ...... normalize → price_history (product + depot + day = one row)
   ├─ analyze ..... cheapest chain + drops since the last message
   ├─ message ..... every N days: .txt + clickable .html
   └─ backup ...... pg_dump, written outside the repo
```

Design rules worth knowing:

- **Money is `Decimal` everywhere.** `NUMERIC(10,2)` in the database, JSON parsed
  with `parse_float=Decimal`. Floats are banned.
- **Raw data is sacred.** Collectors store the platform's response unmodified;
  normalization happens later and is repeatable. If a parsing bug is found, the
  history can be rebuilt without hitting the source again.
- **Day boundaries come from the platform's `indexTime`,** not from when we
  fetched. Using UTC rolled the day at 03:00 local time (UTC+3), so a run just
  after midnight overwrote the previous day's data.
- **No claim without a comparison.** "Cheapest" is only said when more than one
  chain's price is known *and* at least one is more expensive. If all are equal it
  says so; if only one chain is known it says "only at X".
- **No invented dates.** "Yesterday" is used only when it really was yesterday. If
  the machine was off and days were skipped, real dates are printed instead.

## Respecting the data source

The platform's WAF is aggressive: unknown endpoints and unrecognized body fields
are blocked with `HTTP 418`. Accordingly:

- All HTTP goes through a single client (`collectors/market_fiyati_client.py`)
- Only observed endpoints and fields are used — none are ever guessed
- A mandatory delay sits between requests (2s by default)
- On `418`, collection stops **immediately**

One run per day, roughly 80 requests for the sample watchlist. This project is
intended for personal, non-commercial use.

## Privacy

This repository is deliberately free of personal data, and CI enforces it.

**Not in this repo, and never committed:**

| What | Where it lives instead |
|---|---|
| Your coordinates (`LOCATION_LAT` / `LOCATION_LON`) | `.env` — gitignored |
| WhatsApp recipient number | `.env` — gitignored, ships empty on purpose |
| WhatsApp session keys | `WHATSAPP_SESSION_DIR`, **outside** the repo |
| Database dumps (real prices, depots, location) | `BACKUP_DIR`, **outside** the repo |
| Generated messages (`.txt` / `.html`) | `MESSAGE_DIR`, outside the repo by default |

The coordinates in `.env.example` and in CI are a placeholder (Ankara/Kızılay), not
a real address. The recipient number ships blank rather than as a sample: a sample
would mean anyone who copied the file and enabled sending would message a stranger.

A [CI job](.github/workflows/testler.yml) fails the build if a real-looking
coordinate pair, a real store ID, an API key, or a tracked `.env` ever appears in
the tree.

Postgres is published on `127.0.0.1` only. The password in `docker-compose.yml` is
a local development password; binding it to all interfaces would expose the
database on any shared network.

## Setup

Requires **Python 3.12+**, **Docker Desktop**, and **Node 20+** (only for WhatsApp
sending).

```bash
cp .env.example .env
```

Then **set `LOCATION_LAT` / `LOCATION_LON` in `.env` to your own coordinates.**
There is no default — the app refuses to start without them. Location is applied
through the platform's `depots` list; coordinates alone are ignored and prices come
back from the wrong city **silently**.

```bash
docker compose up -d
```

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate        # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
```

Resolve the depots for your location once. This writes the depot list the collector
filters by; without it every search would come back unscoped:

```bash
python -c "from app.database.session import SessionLocal; from app.services.depot_resolver import depolari_coz; db=SessionLocal(); print(depolari_coz(db)); db.close()"
```

```bash
python seed.py                # sample watchlist (76 items)
python gunluk_kosu.py         # first collection
```

API docs: <http://127.0.0.1:8000/docs> (`uvicorn app.main:app --reload`)

### Configuration

Every setting is read from `.env`; nothing is hardcoded. The ones that matter:

| Key | Default | Notes |
|---|---|---|
| `DATABASE_URL` | — | required |
| `LOCATION_LAT` / `LOCATION_LON` | — | **required, no default** — a wrong value fails silently |
| `LOCATION_DISTANCE_KM` | `10` | search radius |
| `COLLECTOR_REQUEST_DELAY_SEC` | `2.0` | delay between requests to the platform |
| `PIPELINE_AUTOSTART` | `false` | start the daily scheduler with the app |
| `PIPELINE_SCHEDULE_HOUR` | `13` | platform indexes around noon |
| `MESSAGE_INTERVAL_DAYS` | `3` | message frequency — collection stays daily regardless |
| `MESSAGE_ITEM_LIMIT` | `100` | products per message before it splits |
| `PRICE_DROP_THRESHOLD_PCT` | `5.0` | below this, a drop is not called a discount |
| `BACKUP_DIR` | `../indirim-yakalar-yedek` | keep it outside the repo |
| `WHATSAPP_ENABLED` | `false` | read the warning below before enabling |

See [`.env.example`](.env.example) for the full annotated list.

### Daily automation (Windows)

```powershell
$action  = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -File scripts\gunluk-kosu.cmd"
$trigger = New-ScheduledTaskTrigger -Daily -At 13:00
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "IndirimYakalar-Toplama" -Action $action -Trigger $trigger -Settings $settings
```

`StartWhenAvailable` matters: if the machine is off at that hour, the run is caught
up on next boot. The wrapper script starts Docker if needed.

## Backup and restore

`gunluk_kosu.py` runs `pg_dump` at the end of every collection, into `BACKUP_DIR`
(outside the repo), keeping `BACKUP_RETENTION_DAYS` days.

This is not decoration. The Docker `pgdata` volume has been destroyed twice, and
**the platform does not serve historical prices** — a day that was not collected is
gone permanently. Restoring from a dump is always preferred over rebuilding:

```bash
python restore.py --yedekten              # newest dump (recommended)
python restore.py --yedekten --dosya X    # a specific dump
python restore.py --sifirdan              # last resort: schema + watchlist only, no history
```

Run `python -m alembic upgrade head` first.

## Tests

```bash
cd backend && pytest
```

295 tests. They need a running PostgreSQL (`docker compose up -d`) — SQLite is not
a substitute, since `ON CONFLICT` and `NUMERIC` behave differently and a stand-in
database would give false confidence. Nothing touches the network: the platform
client is tested through `MockTransport` and WhatsApp sending through a faked
subprocess.

CI runs the same suite against PostgreSQL 16 on every push, plus the leak scan
described under [Privacy](#privacy).

> `pytest.ini` sets `--basetemp=.pytest-tmp`. **Pytest wipes that directory on
> every run** — do not repoint it at a path that holds anything you care about.

## Status

| Phase | State |
|---|---|
| 0 — Skeleton, PostgreSQL, FastAPI | done |
| 1 — Collector, schema, time series | done |
| 2 — Analyzer, WhatsApp message | done |
| 3 — Leaflet reading (vision LLM) | planned |
| 4 — React dashboard | planned |

**Automatic WhatsApp sending does not work.** The library used to drive WhatsApp
Web currently cannot connect, and the official Cloud API is closed to this use case
(template parameters cannot contain newlines; body is capped at 1024 characters,
while these messages run past 2,600). Details in
[`whatsapp/DURUM.md`](whatsapp/DURUM.md). The working path is the one-click
`whatsapp://` link on the generated HTML page.

> **Warning.** The `whatsapp/` directory drives WhatsApp Web through
> `whatsapp-web.js`, which is **not** an official API — it automates your own
> session. This is against WhatsApp's Terms of Service and carries a real risk of
> the number being banned. It ships disabled (`WHATSAPP_ENABLED=false`) and the
> HTML link path needs none of it. Enable it only if you accept that risk.

## Layout

```
backend/
  app/
    api/          FastAPI routers
    collectors/   platform client (the only HTTP exit) + collector
    models/       SQLAlchemy 2.x
    services/     business logic — analyzer, messaging, backup, normalization
    utils/        dates, formatting, files
  tests/
  gunluk_kosu.py  daily run entry point
  restore.py      disaster recovery
whatsapp/         WhatsApp sending (Node) — see DURUM.md
scripts/          Task Scheduler wrapper
```

Identifiers, comments and commit messages are in Turkish. That is deliberate: the
domain is Turkish groceries and the reasoning reads better in the language the
problem lives in.

## License

MIT — see [LICENSE](LICENSE).
