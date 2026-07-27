"""WhatsApp mesajı üretici (SPEC §7).

Mesaj otomatik GÖNDERİLMEZ; panoya kopyalanmak üzere üretilir.

Neyin mesaja gireceği bilinçli olarak dar tutuldu. 76 takip kaleminin hepsini
yazmak mesajı okunmaz eder ve asıl bilgiyi gömer. Girenler:
  1. Eşiği aşan fiyat düşüşü olanlar (en çok düşen başta)
  2. Marketler arası farkı olan kalemler (en çok tasarruf başta)

Fiyatı tek marketten bilinen ve düşüşü de olmayan kalem mesaja girmez — ortada
söylenecek bir şey yoktur. "Yalnızca X'te" ifadesi yalnız düşüş varken kullanılır
(anayasa md. 7: kıyas yoksa "en ucuz" denmez).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.config import Settings, get_settings
from app.services.analyzer import KalemAnalizi, dusenler
from app.utils.bicim import para_yaz, tarih_yaz, yuzde_yaz
from app.utils.tarih import yerel_bugun

# SPEC §7: mesaj başına en fazla 10 ürün.
VARSAYILAN_KALEM_SINIRI = 10

AYRAC = "────────────"


@dataclass(frozen=True)
class Mesaj:
    metin: str
    sayfa: int
    toplam_sayfa: int
    kalem_sayisi: int


def whatsapp_mesajlari(
    analizler: list[KalemAnalizi],
    *,
    gun: date | None = None,
    kalem_siniri: int = VARSAYILAN_KALEM_SINIRI,
    settings: Settings | None = None,
) -> list[Mesaj]:
    """Analizlerden bölünmüş WhatsApp mesajları üretir.

    Söylenecek bir şey yoksa BOŞ liste döner — "indirim yok" diye mesaj
    üretmek, kullanıcıyı boş yere bildirime boğardı.
    """
    settings = settings or get_settings()
    bugun = gun or yerel_bugun()

    secilen = _mesaja_girecekler(analizler, settings=settings)
    if not secilen:
        return []

    # ⚠️ Başlıktaki tarih ÇEKİM günü değil GÖZLEM günüdür. Toplama kaçtıysa
    # eldeki en taze veri dünün olabilir; başlığa "bugün"ün tarihini yazmak
    # eski fiyatı bugünün fiyatı gibi gösterirdi.
    gozlem = max(a.son_gun for a in secilen)

    sayfalar = [
        secilen[i:i + kalem_siniri]
        for i in range(0, len(secilen), kalem_siniri)
    ]

    return [
        Mesaj(
            metin=_sayfa_yaz(grup, gozlem, bugun, sayfa_no + 1, len(sayfalar)),
            sayfa=sayfa_no + 1,
            toplam_sayfa=len(sayfalar),
            kalem_sayisi=len(grup),
        )
        for sayfa_no, grup in enumerate(sayfalar)
    ]


def _mesaja_girecekler(
    analizler: list[KalemAnalizi], *, settings: Settings
) -> list[KalemAnalizi]:
    """Önce düşenler, sonra fark yaratanlar. Aynı kalem iki kez girmez."""
    dusen = dusenler(analizler, settings=settings)
    dusen_idler = {a.kalem_id for a in dusen}

    farkli = [
        a for a in analizler
        if a.kalem_id not in dusen_idler
        and a.en_ucuz_denebilir_mi
        and (a.en_pahali_fark or 0) > 0
    ]
    farkli.sort(key=lambda a: a.en_pahali_fark or 0, reverse=True)

    return dusen + farkli


def _sayfa_yaz(
    grup: list[KalemAnalizi], gozlem: date, bugun: date, sayfa: int, toplam: int
) -> str:
    gunu = "Bugünün" if gozlem == bugun else "Son Gözlem —"
    baslik = f"🛒 *{gunu} Market Fiyatları*"
    if toplam > 1:
        baslik += f"  ({sayfa}/{toplam})"

    tarih_satiri = f"📅 {tarih_yaz(gozlem)}"
    if gozlem != bugun:
        gun_farki = (bugun - gozlem).days
        tarih_satiri += f"  _({gun_farki} gün önce toplandı)_"

    satirlar = [baslik, tarih_satiri, ""]
    for analiz in grup:
        satirlar.extend(_kalem_yaz(analiz, bugun))
        satirlar.append(AYRAC)

    return "\n".join(satirlar).rstrip()


def _kalem_yaz(analiz: KalemAnalizi, bugun: date) -> list[str]:
    satirlar = [f"*{analiz.etiket}*"]

    en_ucuzlar = analiz.en_ucuz_marketler
    if not en_ucuzlar:
        return satirlar

    fiyat = para_yaz(en_ucuzlar[0].fiyat)
    isimler = " / ".join(m.ad for m in en_ucuzlar)

    if analiz.en_ucuz_denebilir_mi:
        satirlar.append(f"✅ En uygun: *{isimler} — {fiyat}*")
    elif analiz.market_sayisi > 1:
        # Hepsi aynı fiyatta: ortada "en ucuz" yok, kıyas da yok.
        satirlar.append(f"ℹ️ Tüm marketlerde aynı: *{fiyat}*")
    else:
        # Tek market biliniyor — "en ucuz" iddiası edilmez (anayasa md. 7).
        satirlar.append(f"ℹ️ Yalnızca {isimler}: *{fiyat}*")

    if analiz.dusus is not None and analiz.dusus.dustu_mu:
        satirlar.append(_dusus_yaz(analiz, bugun))

    # Kalan marketler, ucuzdan pahalıya. En ucuz(lar) yukarıda yazıldı.
    yazilan = {m.market_id for m in en_ucuzlar}
    for market in analiz.market_fiyatlari:
        if market.market_id not in yazilan:
            satirlar.append(f"{market.ad}: {para_yaz(market.fiyat)}")

    return satirlar


def _dusus_yaz(analiz: KalemAnalizi, bugun: date) -> str:
    dusus = analiz.dusus
    assert dusus is not None

    once = _gun_ifadesi(dusus.onceki_gun, bugun)
    sonra = _gun_ifadesi(dusus.son_gun, bugun)

    if dusus.market_degisti_mi:
        # Fiyat, eski market indirim yaptığı için değil, daha ucuz bir market
        # listeye girdiği için düşmüş olabilir. Market adları bunu görünür kılar.
        govde = (
            f"{once} {dusus.onceki_market} {para_yaz(dusus.onceki_fiyat)}"
            f" → {sonra} {dusus.son_market} {para_yaz(dusus.son_fiyat)}"
        )
    else:
        govde = (
            f"{once} {para_yaz(dusus.onceki_fiyat)}"
            f" → {sonra} {para_yaz(dusus.son_fiyat)}"
        )

    return f"🔻 Düştü ({yuzde_yaz(dusus.yuzde)}): {govde}"


def _gun_ifadesi(gun: date, bugun: date) -> str:
    """"bugün"/"dün" YALNIZ gerçekten öyleyse.

    Pipeline kişisel makinede koşuyor ve makine kapalıyken gün atlanıyor;
    araya 13 gün girmişken "dün" yazmak düpedüz yanlış bilgi olurdu
    (SPEC §6.3 — veri boşluğu dürüstlüğü).
    """
    fark = (bugun - gun).days
    if fark == 0:
        return "bugün"
    if fark == 1:
        return "dün"
    return tarih_yaz(gun)
