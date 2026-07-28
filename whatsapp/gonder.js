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

  const hazir = new Promise((coz, reddet) => {
    istemci.on("ready", coz);
    // Kayitli oturum varken QR istenmesi, oturumun DUSTUGU anlamina gelir.
    istemci.on("qr", () =>
      reddet(
        new OturumYok(
          "Oturum dusmus (QR isteniyor). Cozum: node whatsapp/baglan.js",
        ),
      ),
    );
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
    await istemci.destroy();
    console.error(`ALICI_YOK: ${alici} WhatsApp'ta kayitli degil.`);
    process.exit(4);
  }

  for (const [sira, metin] of metinler.entries()) {
    if (sira > 0) {
      await new Promise((c) => setTimeout(c, MESAJ_ARASI_MS));
    }
    await istemci.sendMessage(kimlik._serialized, metin);
    console.log(`gonderildi ${sira + 1}/${metinler.length} (${metin.length} karakter)`);
  }

  await istemci.destroy();
}

main()
  .then(() => process.exit(0))
  .catch(async (hata) => {
    console.error(`HATA: ${hata.message}`);
    if (hata instanceof YapilandirmaHatasi) process.exit(2);
    if (hata instanceof OturumYok) process.exit(3);
    if (String(hata.message).startsWith("SURE_ASIMI")) process.exit(6);
    process.exit(5);
  });
