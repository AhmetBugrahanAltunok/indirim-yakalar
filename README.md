# İndirimYakalar

Market fiyatlarını her gün toplayan, aynı ürünün marketler arasındaki farkını ve
zaman içindeki düşüşünü bulan, sonucu WhatsApp'ta paylaşılabilir sade bir mesaja
çeviren kişisel bir sistem.

Türkiye'deki market zincirlerinin fiyatlarını [marketfiyati.org.tr](https://marketfiyati.org.tr)
üzerinden okur. Kendi takip listeni kurarsın (76 kalemlik bir liste örnek olarak
geliyor), sistem her gün fiyatları çeker ve birkaç günde bir "şu an en ucuz nerede,
ne düştü" mesajı üretir.

## Ne üretiyor

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

Mesaj bir metin dosyasına ve tıklanabilir bir HTML sayfasına yazılır. Sayfadaki
düğme WhatsApp'ı mesaj yazılı halde açar; göndermeye sen karar verirsin.

## Neden ilginç

Platformun verisi ilk bakışta göründüğü gibi değil. Projenin çoğu, gerçek veriyle
çalışırken çıkan şu bulgular üzerine kurulu:

**Aynı fiziksel ürün birden çok katalog kaydında olabiliyor.** Platform katalogu
zincir başına besliyor ve her zaman birleştirmiyor. Kayıtların depo kümeleri
**ayrık** oluyor ve her kayıt kendi içinde "en ucuz"unu ilan ediyor. Tek kayda
bakan kullanıcı %8,3 daha pahalıya yönlendirilebiliyor. Bu yüzden burada bir takip
kalemi 1..N platform kaydına bağlanır ve en ucuz hepsi birleştirilerek hesaplanır.

**Aynı zincirin şubeleri farklı fiyat verebiliyor** — aynı üründe iki şube
arasında %27 fark görüldü. Zincir düzeyinde en ucuz şube alınır, mesajda şube
iddia edilmez.

**Arama sonuçları günden güne değişiyor.** Bir kelime araması ertesi gün 7 üründen
5'ini döndürmedi, ama o ürünlerin ID'leri canlıydı. Bu yüzden takip kelimeyle değil
**ürün kimliğiyle** yapılır; kimliklerin günler arası kalıcı olduğu doğrulandı.

**Ürünün depo kümesi de oynuyor.** Aynı ürün bir gün bir şubede, ertesi gün başka
bir şubede görünebiliyor — fiyat aynıyken. Zaman serisi bu yüzden depo değil zincir
düzeyinde kurulur.

## Nasıl çalışıyor

```
gunluk_kosu.py  (her gün, Windows Görev Zamanlayıcı)
   │
   ├─ topla ......... her takip ID'si için platform API'si → raw_records (ham, dokunulmamış)
   ├─ işle .......... normalize → price_history (ürün + depo + gün = tek satır)
   ├─ analiz ........ en ucuz zincir + son mesajdan bu yana düşüş
   ├─ mesaj ......... N günde bir .txt + tıklanabilir .html
   └─ yedekle ....... pg_dump, repo dışına
```

Birkaç tasarım kuralı:

- **Para her yerde `Decimal`.** DB'de `NUMERIC(10,2)`, JSON `parse_float=Decimal`
  ile ayrıştırılır. Float yasak.
- **Ham veri kutsal.** Collector platformun yanıtını değiştirmeden saklar;
  normalize etme sonradan ve tekrarlanabilir. Ayrıştırma hatası bulunursa kaynak
  tekrar yorulmadan yeniden üretilir.
- **Gün sınırı `indexTime`'dan türer**, çekim saatinden değil. UTC kullanmak
  UTC+3'te günü gece 03:00'te döndürüyor ve gece koşusu bir önceki günün verisini
  eziyordu.
- **Kıyas yoksa iddia yok.** "En ucuz" ancak birden fazla marketin fiyatı
  biliniyorsa ve en az biri daha pahalıysa denir. Hepsi aynıysa "tüm marketlerde
  aynı", tek market biliniyorsa "yalnızca X'te" yazılır.
- **Uydurma tarih yok.** "dün" yalnız gerçekten dünse yazılır; makine kapalı
  kaldıysa araya gün girer ve gerçek tarihler basılır.

## Veri kaynağına saygı

Platformun WAF'ı agresif: bilinmeyen uç noktalara ve tanınmayan gövde alanlarına
`HTTP 418` ile blok veriyor. Bu yüzden:

- Tüm HTTP tek bir istemciden geçer (`collectors/market_fiyati_client.py`)
- Yalnız gözlemlenmiş uç noktalar ve alanlar kullanılır, hiçbiri tahmin edilmez
- İstekler arasında zorunlu bekleme var (varsayılan 2 sn)
- `418` görülürse toplama **derhal** durur

Günde bir koşu, takip listesi başına ~80 istek. Bu proje kişisel kullanım içindir.

## Kurulum

Gereksinimler: Python 3.12+, Docker Desktop, Node 20+ (yalnız WhatsApp gönderimi için).

```bash
cp .env.example .env
```

`.env` içinde **`LOCATION_LAT` / `LOCATION_LON`'u kendi koordinatınla değiştir** —
varsayılanı yoktur, eksikse uygulama açılmaz. Konum, platformun `depots` listesiyle
uygulanır; koordinat tek başına yok sayılır ve fiyatlar **sessizce** yanlış şehirden
gelir.

```bash
docker compose up -d

cd backend
python -m venv .venv
.venv/Scripts/activate        # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head

python -c "from app.database.session import SessionLocal; from app.services.depot_resolver import depolari_coz; db=SessionLocal(); print(depolari_coz(db)); db.close()"
python seed.py                # örnek takip listesi (76 kalem)
python gunluk_kosu.py         # ilk toplama
```

API: <http://127.0.0.1:8000/docs> (`uvicorn app.main:app --reload`)

### Günlük otomatik koşu (Windows)

```powershell
$action  = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -File scripts\gunluk-kosu.cmd"
$trigger = New-ScheduledTaskTrigger -Daily -At 13:00
$ayar    = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "IndirimYakalar-Toplama" -Action $action -Trigger $trigger -Settings $ayar
```

`StartWhenAvailable` önemli: makine o saatte kapalıysa koşu açılışta telafi edilir.
Sarmalayıcı betik gerekirse Docker'ı da başlatır.

## Test

```bash
cd backend && pytest
```

277 test. Çalışan bir PostgreSQL ister (`docker compose up -d`); ağa çıkmaz —
platform istemcisi `MockTransport` ile, WhatsApp gönderimi taklit süreçle test edilir.

## Durum

| Faz | Durum |
|---|---|
| 0 — İskelet, PostgreSQL, FastAPI | ✅ |
| 1 — Collector, şema, zaman serisi | ✅ |
| 2 — Analyzer, WhatsApp mesajı | ✅ |
| 3 — Broşür okuma (Vision LLM) | planlandı |
| 4 — React panel | planlandı |

WhatsApp'ın **otomatik** gönderimi çalışmıyor: kullanılan kütüphane WhatsApp Web'e
şu an bağlanamıyor ve resmî Cloud API bu kullanıma kapalı (şablon değişkenlerinde
satır başı yasak, gövde 1024 karakter). Ayrıntı: [`whatsapp/DURUM.md`](whatsapp/DURUM.md).
Çalışan yol, HTML sayfasındaki tek tıklık `whatsapp://` bağlantısı.

## Yapı

```
backend/
  app/
    api/          FastAPI router'ları
    collectors/   platform istemcisi (tek HTTP çıkışı) + toplayıcı
    models/       SQLAlchemy 2.x
    services/     iş mantığı — analyzer, mesaj, yedek, normalize
    utils/        tarih, biçim, dosya
  tests/
  gunluk_kosu.py  günlük koşunun giriş noktası
  restore.py      felaket kurtarma
whatsapp/         WhatsApp gönderimi (Node) — bkz. DURUM.md
scripts/          Görev Zamanlayıcı sarmalayıcısı
```

Kod Türkçe adlandırılmıştır; bu bilinçli bir tercihtir.

## Lisans

MIT — bkz. [LICENSE](LICENSE).
