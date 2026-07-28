# WhatsApp gönderimi — 29.07.2026 itibarıyla ÇALIŞMIYOR

> **Bu klasördeki kod tamamlanmış ve test edilmiş durumda, ama `whatsapp-web.js`
> kütüphanesi şu anda WhatsApp Web'e bağlanamıyor.** Sorun bizim kurulumumuzda
> değil, kütüphanenin kendisinde.

## Belirti

`node baglan.js` çalıştırıldığında QR kodu **hiç çıkmıyor**, bunun yerine:

```
Protocol error (Runtime.callFunctionOn): Execution context was destroyed.
```

Aynı hata `gonder.js`'te de çıkıyor.

## Denenenler (hepsi aynı sonucu verdi)

| Deneme | Sonuç |
|---|---|
| Puppeteer'ın kendi Chromium'u (146.0.7680.31) | Aynı hata |
| Sistemdeki Chrome | Aynı hata |
| `webVersionCache` ile WhatsApp Web sürümü sabitleme (`2.3000.1041716477-alpha`) | Aynı hata |

Üç farklı yapılandırmada birebir aynı hata çıkması, sorunun yapılandırmada
değil kütüphanede olduğunu gösteriyor.

## Yukarı akış durumu

Bilinen ve **açık** bir sorun. Kütüphane WhatsApp Web sayfasına kod enjekte
ederek çalışıyor; WhatsApp sayfayı değiştirdiğinde kırılıyor.

- [Issue #127056](https://github.com/wwebjs/whatsapp-web.js/issues/127056) — Şubat 2026, v1.34.4'te tam bu hata
- [Issue #3652](https://github.com/pedroslopez/whatsapp-web.js/issues/3652), [#3658](https://github.com/pedroslopez/whatsapp-web.js/issues/3658), [#3792](https://github.com/wwebjs/whatsapp-web.js/issues/3792) — aynı belirti, farklı sürümler

Kurulu sürümler: `whatsapp-web.js@1.34.7`, `puppeteer@24.38.0`.

## Şu an ne oluyor

`WHATSAPP_ENABLED` **kapalı**. Kapalıyken hiçbir süreç açılmıyor, günlük koşu
etkilenmiyor. Mesaj dosyaya yazılmaya devam ediyor
(`mesaj-YYYY-AA-GG.txt`) — elle kopyalanıp gönderilebilir.

## Tekrar denemek için

Kütüphane güncellenmiş olabilir:

```bash
cd whatsapp && npm update whatsapp-web.js && node baglan.js
```

QR çıkarsa sorun çözülmüş demektir. Çıkmazsa `WHATSAPP_WEB_VERSION` ile
[wa-version](https://github.com/wppconnect-team/wa-version/tree/main/html)
deposundan daha yeni bir sürüm denenebilir.

## Alternatif

`@whiskeysockets/baileys` bambaşka bir yaklaşım kullanıyor: tarayıcı
çalıştırmıyor, WhatsApp'ın WebSocket protokolüne doğrudan bağlanıyor. Bu
sınıftan hatalara açık değil. Aynı kullanım şartları riski geçerli.
