@echo off
setlocal enabledelayedexpansion

REM ---------------------------------------------------------------------------
REM Daily collection wrapper for Windows Task Scheduler.
REM   collect -> ingest -> pg_dump backup
REM
REM NOTE: this file is deliberately ASCII-only. Batch files are read with the
REM console codepage (857/850 here, not UTF-8), so Turkish characters would come
REM out as mojibake in the log. Turkish docs live in the .py files instead.
REM
REM Exit codes: 0 ok | 1 collection failed | 2 backup failed | 3 docker failed
REM ---------------------------------------------------------------------------

pushd "%~dp0.."
set "REPO=%CD%"
popd

set "BACKEND=%REPO%\backend"
set "PY=%BACKEND%\.venv\Scripts\python.exe"
set "LOGDIR=%REPO%\..\indirim-yakalar-yedek\log"

REM Python otherwise writes its Turkish log lines in the console OEM codepage
REM (cp857 here) while the batch lines are ASCII, producing a mixed-encoding
REM file that no single reader decodes correctly.
set "PYTHONIOENCODING=utf-8"

if not exist "%LOGDIR%" mkdir "%LOGDIR%"

REM Sortable date (YYYY-MM-DD) independent of regional settings.
for /f %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set "TODAY=%%d"
set "LOG=%LOGDIR%\kosu-%TODAY%.log"

call :log "=== gunluk kosu basladi ==="

if not exist "%PY%" (
    call :log "HATA: sanal ortam bulunamadi: %PY%"
    exit /b 3
)

REM --- Docker engine ---------------------------------------------------------
docker info >nul 2>&1
if errorlevel 1 (
    call :log "Docker kapali, baslatiliyor..."
    start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"

    REM Cold start measured at ~150s on this machine; allow up to 5 minutes.
    set "READY="
    for /l %%i in (1,1,60) do (
        if not defined READY (
            timeout /t 5 /nobreak >nul
            docker info >nul 2>&1
            if not errorlevel 1 set "READY=1"
        )
    )
    if not defined READY (
        call :log "HATA: Docker 5 dakikada hazir olmadi."
        exit /b 3
    )
    call :log "Docker hazir."
)

REM --- Database container ----------------------------------------------------
docker compose -f "%REPO%\docker-compose.yml" up -d >>"%LOG%" 2>&1
if errorlevel 1 (
    call :log "HATA: veritabani konteyneri baslatilamadi."
    exit /b 3
)

REM Healthcheck: pg_isready. Without this the first connection can fail while
REM Postgres is still doing crash recovery.
set "HEALTHY="
for /l %%i in (1,1,30) do (
    if not defined HEALTHY (
        for /f %%s in ('docker inspect --format "{{.State.Health.Status}}" indirim-yakalar-db 2^>nul') do (
            if "%%s"=="healthy" set "HEALTHY=1"
        )
        if not defined HEALTHY timeout /t 3 /nobreak >nul
    )
)
if not defined HEALTHY (
    call :log "HATA: veritabani saglikli duruma gelmedi."
    exit /b 3
)

REM --- Run -------------------------------------------------------------------
cd /d "%BACKEND%"
"%PY%" gunluk_kosu.py >>"%LOG%" 2>&1
set "RC=%errorlevel%"

if "%RC%"=="0" call :log "=== tamamlandi ==="
if "%RC%"=="1" call :log "=== TOPLAMA BASARISIZ ==="
if "%RC%"=="2" call :log "=== YEDEK ALINAMADI (veri korumasiz) ==="

exit /b %RC%

:log
echo [%date% %time%] %~1>>"%LOG%"
echo [%date% %time%] %~1
exit /b 0
