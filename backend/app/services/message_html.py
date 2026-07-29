"""Mesajı tıklanabilir bir HTML sayfası olarak da yazar.

Neden: `whatsapp://send?phone=...&text=...` bağlantısı **resmî** bir yol.
Windows'ta kurulu WhatsApp uygulaması bu protokolü karşılıyor (Store paketi
manifest'inde `windows.protocol` / `whatsapp` olarak tanımlı, 29.07.2026'da
doğrulandı). Tıklayınca uygulama açılıp mesajı yazılmış halde getiriyor;
göndermeye kullanıcı karar veriyor.

Otomatik gönderim değil ama tek tık — ve `whatsapp-web.js`'in aksine kırılgan
değil, kullanım şartlarını da ihlal etmiyor (bkz. `whatsapp/DURUM.md`).

⚠️ Uzun mesajlarda bağlantı kesilebilir: 2.641 karakterlik mesaj URL
kodlamasıyla 6.268 karaktere çıkıyor ve protokol bağlantılarının pratik sınırı
belirsiz. Bu yüzden sayfada **her zaman** "Panoya Kopyala" düğmesi de var —
bağlantı kesilirse kopyala yolu çalışmaya devam eder.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.services.analyzer import tum_kalemleri_analiz_et
from app.services.message_builder import whatsapp_mesajlari
from app.services.message_export import mesaj_dizini
from app.utils.bicim import tarih_yaz
from app.utils.tarih import yerel_bugun

logger = logging.getLogger(__name__)

DOSYA_ONEKI = "mesaj-"
DOSYA_UZANTISI = ".html"

_SAYFA = """<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Market Fiyatları — {tarih}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    max-width: 46rem; margin: 0 auto; padding: 1.5rem;
    line-height: 1.5;
  }}
  h1 {{ font-size: 1.25rem; margin: 0 0 .25rem; }}
  .tarih {{ opacity: .7; font-size: .9rem; margin-bottom: 1.5rem; }}
  .kart {{
    border: 1px solid rgba(128,128,128,.35); border-radius: .6rem;
    padding: 1rem; margin-bottom: 1.5rem;
  }}
  .dugmeler {{ display: flex; gap: .6rem; flex-wrap: wrap; margin-bottom: .9rem; }}
  button, a.dugme {{
    font: inherit; padding: .6rem 1.1rem; border-radius: .5rem;
    border: 1px solid transparent; cursor: pointer; text-decoration: none;
  }}
  a.dugme {{ background: #25d366; color: #062; font-weight: 600; }}
  button {{ background: transparent; border-color: rgba(128,128,128,.5); color: inherit; }}
  pre {{
    white-space: pre-wrap; word-wrap: break-word; margin: 0;
    font-family: ui-monospace, Consolas, monospace; font-size: .85rem;
    max-height: 22rem; overflow-y: auto;
  }}
  .not {{ font-size: .8rem; opacity: .65; margin-top: .8rem; }}
</style>
</head>
<body>
<h1>🛒 Market Fiyatları</h1>
<div class="tarih">{tarih} · {sayfa_sayisi}</div>
<div id="icerik"></div>
<script>
const MESAJLAR = {mesajlar_json};
const ALICI = {alici_json};

const icerik = document.getElementById("icerik");

MESAJLAR.forEach((metin, i) => {{
  const kart = document.createElement("div");
  kart.className = "kart";

  const dugmeler = document.createElement("div");
  dugmeler.className = "dugmeler";

  const bag = document.createElement("a");
  bag.className = "dugme";
  // Alici yoksa kisi secme ekrani acilir.
  const temel = ALICI ? `whatsapp://send?phone=${{ALICI}}&text=` : "whatsapp://send?text=";
  bag.href = temel + encodeURIComponent(metin);
  bag.textContent = "WhatsApp'ta Aç";
  dugmeler.appendChild(bag);

  const kopyala = document.createElement("button");
  kopyala.textContent = "Panoya Kopyala";
  kopyala.onclick = async () => {{
    await navigator.clipboard.writeText(metin);
    kopyala.textContent = "Kopyalandı ✓";
    setTimeout(() => (kopyala.textContent = "Panoya Kopyala"), 2000);
  }};
  dugmeler.appendChild(kopyala);

  kart.appendChild(dugmeler);

  const on = document.createElement("pre");
  on.textContent = metin;
  kart.appendChild(on);

  const not = document.createElement("div");
  not.className = "not";
  not.textContent =
    "Bağlantı mesajı kesik getirirse Panoya Kopyala'yı kullan — o her zaman tam metni verir.";
  kart.appendChild(not);

  icerik.appendChild(kart);
}});
</script>
</body>
</html>
"""


def html_dosya_yolu(dizin: Path, gun: date) -> Path:
    return dizin / f"{DOSYA_ONEKI}{gun.isoformat()}{DOSYA_UZANTISI}"


def html_yaz(
    db: Session,
    *,
    gun: date | None = None,
    settings: Settings | None = None,
    taban_gun: date | None = None,
) -> Path | None:
    """Tıklanabilir sayfayı yazar. Söylenecek bir şey yoksa None."""
    settings = settings or get_settings()
    gun = gun or yerel_bugun()

    analizler = tum_kalemleri_analiz_et(db, settings=settings, taban_gun=taban_gun)
    mesajlar = whatsapp_mesajlari(analizler, gun=gun, settings=settings)
    if not mesajlar:
        return None

    dizin = mesaj_dizini(settings)
    dizin.mkdir(parents=True, exist_ok=True)
    hedef = html_dosya_yolu(dizin, gun)

    gozlem = max(a.son_gun for a in analizler if a.son_gun)
    sayfa_sayisi = (
        "1 mesaj" if len(mesajlar) == 1 else f"{len(mesajlar)} mesaj (ayrı ayrı gönder)"
    )

    hedef.write_text(
        _SAYFA.format(
            tarih=tarih_yaz(gozlem),
            sayfa_sayisi=sayfa_sayisi,
            # json.dumps hem kaçışı hem tırnakları doğru yapar; elle string
            # birleştirmek emoji/tırnak/satır başı yüzünden bozuk HTML üretirdi.
            mesajlar_json=json.dumps([m.metin for m in mesajlar], ensure_ascii=False),
            alici_json=json.dumps(_sadece_rakam(settings.whatsapp_recipient)),
        ),
        encoding="utf-8",
    )

    logger.info("Tıklanabilir sayfa: %s", hedef)
    return hedef


def _sadece_rakam(ham: str | None) -> str:
    return "".join(k for k in (ham or "") if k.isdigit())
