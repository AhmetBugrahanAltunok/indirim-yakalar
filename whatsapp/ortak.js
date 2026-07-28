/**
 * WhatsApp istemcisi — baglan.js ve gonder.js tarafindan paylasilir.
 *
 * ONEMLI: Bu, WhatsApp'in RESMI API'si degildir. whatsapp-web.js, WhatsApp
 * Web oturumunu taklit eder. Resmi Cloud API sablon disi cok satirli mesaji
 * 24 saatlik pencere disinda gondermiyor (sablon degiskenlerinde satir basi
 * yasak), bu yuzden bu yol secildi. Kullanim sartlarina aykiridir ve numara
 * kapatilma riski tasir — proje sahibi riski bilerek kabul etti (29.07.2026).
 *
 * Oturum verisi kimlik dogrulama anahtari icerir: repo DISINDA tutulur ve
 * asla commit edilmez (anayasa md. 5).
 */

const fs = require("node:fs");
const path = require("node:path");

const { Client, LocalAuth } = require("whatsapp-web.js");

// Puppeteer'in kendi Chromium'u bulunamazsa denenecek yerler.
const CHROME_ADAYLARI = [
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
  path.join(
    process.env.LOCALAPPDATA || "",
    "Google\\Chrome\\Application\\chrome.exe",
  ),
];

function oturumDizini() {
  const ham = (process.env.WHATSAPP_SESSION_DIR || "").trim();
  if (!ham) {
    throw new Error(
      "WHATSAPP_SESSION_DIR bos. Oturum klasoru repo disinda olmali.",
    );
  }
  return ham;
}

function chromeYolu() {
  const ayarli = (process.env.WHATSAPP_CHROME_PATH || "").trim();
  if (ayarli) {
    if (!fs.existsSync(ayarli)) {
      throw new Error(`WHATSAPP_CHROME_PATH bulunamadi: ${ayarli}`);
    }
    return ayarli;
  }
  // undefined dondurmek puppeteer'in kendi cozumlemesini kullanmasini saglar.
  return CHROME_ADAYLARI.find((y) => y && fs.existsSync(y)) || undefined;
}

/**
 * Telefon numarasini WhatsApp'in bekledigi kimlige cevirir.
 * "+90 555 000 00 00" -> "905550000000@c.us"
 */
function numarayiCozumle(ham) {
  const rakamlar = String(ham || "").replace(/\D/g, "");
  if (rakamlar.length < 10) {
    throw new Error(
      `Gecersiz numara: ulke koduyla birlikte yazilmali (or. 905550000000). Gelen: ${rakamlar.length} rakam`,
    );
  }
  return `${rakamlar}@c.us`;
}

// whatsapp-web.js, WhatsApp Web'in canli sayfasina kod enjekte ediyor. Sayfa
// degistiginde kutuphane kiriliyor ve "Protocol error (Runtime.callFunctionOn):
// Execution context was destroyed" veriyor — QR bile cikmiyor. Bilinen tek
// hafifletme, sayfayi bilinen bir surume sabitlemek.
// Kirilirsa: wppconnect-team/wa-version deposundan daha yeni bir surum secilir.
const VARSAYILAN_WEB_SURUMU = "2.3000.1041716477-alpha";

function webSurumOnbellegi() {
  const surum = (process.env.WHATSAPP_WEB_VERSION || "").trim() || VARSAYILAN_WEB_SURUMU;
  if (surum.toLowerCase() === "kapali") return undefined;
  return {
    type: "remote",
    remotePath: `https://raw.githubusercontent.com/wppconnect-team/wa-version/main/html/${surum}.html`,
  };
}

function istemciOlustur() {
  const dizin = oturumDizini();
  fs.mkdirSync(dizin, { recursive: true });

  return new Client({
    authStrategy: new LocalAuth({ dataPath: dizin }),
    webVersionCache: webSurumOnbellegi(),
    puppeteer: {
      headless: true,
      executablePath: chromeYolu(),
      // --no-sandbox: Windows'ta hizmet/gorev baglaminda sandbox acilmayabiliyor.
      args: ["--no-sandbox", "--disable-setuid-sandbox"],
    },
  });
}

/** Sure asiminda sureci asili birakmamak icin. Gorev Zamanlayici bekler. */
function zamanAsimi(saniye, mesaj) {
  return new Promise((_, reddet) =>
    setTimeout(() => reddet(new Error(mesaj)), saniye * 1000),
  );
}

module.exports = { istemciOlustur, numarayiCozumle, oturumDizini, zamanAsimi };
