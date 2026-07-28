"""Günlük koşu: topla → işle → mesajı yaz → WhatsApp'tan gönder → yedekle.

Windows Görev Zamanlayıcı bunu çağırır (bkz. `scripts/gunluk-kosu.cmd`).
Uygulamanın açık olmasına gerek yoktur — `app/scheduler.py` yalnız FastAPI
süreci ayaktayken çalışır, makine kapalıyken o gün kaçar.

Çıkış kodları: 0 başarılı ya da zaten toplanmış · 1 toplama başarısız ·
2 toplama başarılı ama yedek alınamadı (veri var, koruması yok — sessiz
geçilmez, anayasa md. 10).

Aynı gün ikinci kez çalışması zararsızdır: `bugun_toplandi_mi` görürse API
tekrar yorulmaz, `--zorla` ile bilerek geçilebilir.
"""

from __future__ import annotations

import argparse
import logging
import sys

from app.database.session import SessionLocal
from app.services.backup import (
    YedekHatasi,
    eski_yedekleri_temizle,
    yedek_al,
)
from app.services.message_export import eski_mesajlari_temizle, mesajlari_yaz
from app.services.pipeline_runner import bugun_toplandi_mi, pipeline_calistir
from app.services.whatsapp_sender import WhatsAppHatasi, mesajlari_gonder
from app.utils.tarih import yerel_bugun

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("gunluk_kosu")


def main(argv: list[str] | None = None) -> int:
    ayristirici = argparse.ArgumentParser(description="Günlük fiyat toplama koşusu")
    ayristirici.add_argument(
        "--zorla",
        action="store_true",
        help="Bugün zaten toplanmış olsa da tekrar topla",
    )
    ayristirici.add_argument(
        "--yedeksiz",
        action="store_true",
        help="Yedek alma adımını atla (Docker yoksa elle koşu için)",
    )
    ayristirici.add_argument(
        "--gondersiz",
        action="store_true",
        help="WhatsApp gönderimini atla (dosya yine yazılır)",
    )
    args = ayristirici.parse_args(argv)

    gun = yerel_bugun()
    logger.info("Günlük koşu başladı — %s", gun.strftime("%d.%m.%Y"))

    db = SessionLocal()
    try:
        # Toplama atlansa bile YEDEK ADIMINA DEVAM EDİLİR: veri uygulamanın
        # kendi zamanlayıcısıyla girmiş olabilir ve o yedek almaz. "Zaten
        # toplanmış" diye çıkmak, veriyi korumasız bırakırdı.
        if not args.zorla and bugun_toplandi_mi(db, gun):
            logger.info("Bugün zaten toplanmış, API yorulmadı — yedeğe geçiliyor.")
        else:
            sonuc = pipeline_calistir(db)
            logger.info("Sonuç: %s", sonuc.ozet())

            if sonuc.toplama.durduruldu:
                logger.error("Toplama durduruldu: %s", sonuc.toplama.durma_nedeni)

            if not sonuc.basarili_mi:
                logger.error("Hiç kayıt alınamadı — yedek adımına geçilmiyor.")
                return 1

        # Mesaj yazımı yedekten ÖNCE ve kendi hatasına dayanıklı: mesaj
        # üretilemese bile toplanan veri yedeklenmeli.
        yazilan: list = []
        try:
            yazilan = mesajlari_yaz(db, gun=gun)
            for yol in yazilan:
                logger.info("Mesaj: %s", yol)
            for silinen in eski_mesajlari_temizle(gun=gun):
                logger.info("Eski mesaj silindi: %s", silinen.name)
        except Exception as hata:  # noqa: BLE001 — koşuyu düşürmemeli
            logger.error("Mesaj dosyası yazılamadı: %s", hata)

        # Gönderim ayrı korumada: WhatsApp tarafı kırılgan (oturum düşebilir,
        # tarayıcı açılmayabilir) ama bu, toplanan verinin yedeklenmesini
        # engellememeli. Dosya zaten diskte, elle de gönderilebilir.
        if not args.gondersiz:
            try:
                mesajlari_gonder(yazilan)
            except WhatsAppHatasi as hata:
                logger.error("WhatsApp gönderilemedi: %s", hata)
    finally:
        db.close()

    if args.yedeksiz:
        logger.info("Yedek atlandı (--yedeksiz).")
        return 0

    try:
        hedef = yedek_al(gun=gun)
        logger.info("Yedek: %s (%d bayt)", hedef, hedef.stat().st_size)
        for silinen in eski_yedekleri_temizle(gun=gun):
            logger.info("Eski yedek silindi: %s", silinen.name)
    except YedekHatasi as hata:
        # Veri toplandı ama korumasız duruyor: bu durum sessiz geçilmez.
        logger.error("YEDEK ALINAMADI: %s", hata)
        return 2

    logger.info("Günlük koşu tamamlandı.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
