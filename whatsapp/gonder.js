/**
 * Mesaj dosyalarini WhatsApp'tan gonderir. Once baglan.js calistirilmis olmali.
 *
 *   node whatsapp/gonder.js <dosya1> [dosya2 ...]
 *
 * Alici WHATSAPP_RECIPIENT'tan okunur (ulke koduyla, or. 905550000000).
 *
 * Cikis kodlari — cagiran (gunluk_kosu.py) bunlara gore ayirt eder:
 *   0 gonderildi · 2 yapilandirma hatasi · 3 oturum yok (baglan.js gerekli)
 *   4 alicinin WhatsApp'i yok · 5 gonderim hatasi · 6 sure asimi
 */

const fs = require("node:fs");

const { istemciOlustur, numarayiCozumle, zamanAsimi } = require("./ortak");

const HAZIR_BEKLEME_SN = 120;
// Ard arda gonderimde bekleme: WhatsApp hizli seri mesaji istenmeyen davranis
// sayabiliyor. Gunde birkac mesaj icin 3 sn fazlasiyla yeter.
const MESAJ_ARASI_MS = 3000;

class YapilandirmaHatasi extends Error {}
class OturumYok extends Error {}
class AliciYok extends Error {}

// Hata yolunda da kapatabilmek icin main() disinda tutuluyor.
let acikIstemci = null;

/**
 * QR istendi mi. TESHIS ICIN KRITIK.
 *
 * Oturum dustugunde whatsapp-web.js once "qr" yayiyor, sonra tarayici
 * kapanirken "Protocol error: Execution context was destroyed" firlatiyor.
 * O hata yarisi kazanirsa cikis kodu 5 (genel hata) oluyor ve kullanici
 * log'da "gonderim hatasi" gorup baglan.js calistirmasi gerektigini
 * anlamiyor. QR gorulduyse tanı her zaman "oturum yok"tur.
 */
let qrGoruldu = false;

function dosyalariOku(yollar) {
  if (yollar.length === 0) {
    throw new YapilandirmaHatasi("Gonderilecek dosya verilmedi.");
  }
  return yollar.map((yol) => {
    if (!fs.existsSync(yol)) {
      throw new YapilandirmaHatasi(`Dosya yok: ${yol}`);
    }
    const metin = fs.readFileSync(yol, "utf8").trim();
    if (!metin) {
      throw new YapilandirmaHatasi(`Dosya bos: ${yol}`);
    }
    return metin;
  });
}

/**
 * Tarayiciyi kapatir. HER cikis yolunda cagrilmali.
 *
 * Cagrilmazsa Chromium OKSUZ KALIR: gunluk kosuda her hatada bir chrome.exe
 * birikir ve makine yavaslar. process.exit() cocuk surecleri kendiliginde
 * oldurmez.
 */
async function kapat(istemci) {
  if (!istemci) return;
  try {
    // destroy() bazen asili kaliyor; 10 sn sonra yine de cikilir.
    await Promise.race([
      istemci.destroy(),
      new Promise((c) => setTimeout(c, 10_000)),
    ]);
  } catch {
    // Kapatirken cikan hata, asil hatayi golgelememeli.
  }
}

async function main() {
  const alici = (process.env.WHATSAPP_RECIPIENT || "").trim();
  if (!alici) {
    throw new YapilandirmaHatasi(
      "WHATSAPP_RECIPIENT bos. .env'e alicinin numarasini yaz (or. 905550000000).",
    );
  }

  const metinler = dosyalariOku(process.argv.slice(2));
  const hedef = numarayiCozumle(alici);
  const istemci = istemciOlustur();
  acikIstemci = istemci;

  const hazir = new Promise((coz, reddet) => {
    istemci.on("ready", coz);
    // Kayitli oturum varken QR istenmesi, oturumun DUSTUGU anlamina gelir.
    istemci.on("qr", () => {
      qrGoruldu = true;
      reddet(
        new OturumYok(
          "Oturum dusmus (QR isteniyor). Cozum: node whatsapp/baglan.js",
        ),
      );
    });
    istemci.on("auth_failure", (m) =>
      reddet(new OturumYok(`Kimlik dogrulama basarisiz: ${m}`)),
    );
  });

  await istemci.initialize();
  await Promise.race([
    hazir,
    zamanAsimi(HAZIR_BEKLEME_SN, "SURE_ASIMI: WhatsApp Web hazir olmadi."),
  ]);

  // Numaranin WhatsApp'ta kayitli oldugunu once dogrula: dogrulamadan
  // gondermek sessizce bosluga mesaj atmak olur.
  const kimlik = await istemci.getNumberId(hedef.replace("@c.us", ""));
  if (!kimlik) {
    throw new AliciYok(`${alici} WhatsApp'ta kayitli degil.`);
  }

  for (const [sira, metin] of metinler.entries()) {
    if (sira > 0) {
      await new Promise((c) => setTimeout(c, MESAJ_ARASI_MS));
    }
    await istemci.sendMessage(kimlik._serialized, metin);
    console.log(`gonderildi ${sira + 1}/${metinler.length} (${metin.length} karakter)`);
  }
}

function kodBelirle(hata) {
  if (hata instanceof YapilandirmaHatasi) return 2;
  if (hata instanceof AliciYok) return 4;
  // QR gorulduyse asil sebep oturumun dusmesidir; tarayici kapanirken cikan
  // protokol hatasi yarisi kazanmis olabilir, ona bakip yanlis teshis koyma.
  if (hata instanceof OturumYok || qrGoruldu) return 3;
  if (String(hata.message).startsWith("SURE_ASIMI")) return 6;
  return 5;
}

// Son emniyet: her sey ters giderse bile surec asili kalmasin. Gorev
// Zamanlayici asili sureci bekler ve ertesi gunku kosu ustune biner.
const oldurucu = setTimeout(() => {
  console.error("HATA: sert sure asimi — surec zorla kapatiliyor.");
  process.exit(6);
}, (Number(process.env.WHATSAPP_HARD_TIMEOUT_SEC) || 300) * 1000);
oldurucu.unref();

main()
  .then(async () => {
    await kapat(acikIstemci);
    process.exit(0);
  })
  .catch(async (hata) => {
    const kod = kodBelirle(hata);
    if (kod === 3 && !(hata instanceof OturumYok)) {
      console.error(
        `HATA: Oturum dusmus. Cozum: node whatsapp/baglan.js  (asil belirti: ${hata.message})`,
      );
    } else {
      console.error(`HATA: ${hata.message}`);
    }
    await kapat(acikIstemci);
    process.exit(kod);
  });
