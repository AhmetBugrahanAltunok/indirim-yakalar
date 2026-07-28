/**
 * TEK SEFERLIK eslestirme: QR kodu gosterir, telefonla okutulur.
 *
 * Calistirma (repo kokunden):
 *   node whatsapp/baglan.js
 *
 * Telefonda: WhatsApp > Ayarlar > Bagli cihazlar > Cihaz bagla > QR'i okut.
 *
 * Oturum WHATSAPP_SESSION_DIR altina yazilir ve kalicidir; bir daha QR
 * istenmez. Telefon 14 gunden uzun cevrimdisi kalirsa ya da "Bagli cihazlar"
 * ekranindan cikis yapilirsa oturum duser ve bu betik tekrar calistirilir.
 */

const qrterminal = require("qrcode-terminal");

const { istemciOlustur, oturumDizini, zamanAsimi } = require("./ortak");

const QR_BEKLEME_SN = 180;

async function main() {
  console.log(`Oturum klasoru: ${oturumDizini()}`);
  console.log("Baglaniliyor...\n");

  const istemci = istemciOlustur();
  let qrGosterildi = false;

  const hazir = new Promise((coz, reddet) => {
    istemci.on("qr", (qr) => {
      qrGosterildi = true;
      console.log("Telefonunla bu QR kodu okut:");
      console.log("WhatsApp > Ayarlar > Bagli cihazlar > Cihaz bagla\n");
      qrterminal.generate(qr, { small: true });
    });

    istemci.on("authenticated", () => console.log("\nKimlik dogrulandi."));

    istemci.on("ready", async () => {
      const bilgi = istemci.info;
      console.log(`\nBAGLANDI: ${bilgi.pushname} (${bilgi.wid.user})`);
      coz();
    });

    istemci.on("auth_failure", (m) =>
      reddet(new Error(`Kimlik dogrulama basarisiz: ${m}`)),
    );
  });

  await istemci.initialize();
  await Promise.race([
    hazir,
    zamanAsimi(
      QR_BEKLEME_SN,
      qrGosterildi
        ? "QR okutulmadi (3 dk). Betigi tekrar calistir."
        : "WhatsApp Web acilamadi (3 dk).",
    ),
  ]);

  console.log("\nOturum kaydedildi. Artik gonder.js QR istemeden calisir.");
  await istemci.destroy();
}

main()
  .then(() => process.exit(0))
  .catch((hata) => {
    console.error(`\nHATA: ${hata.message}`);
    process.exit(1);
  });
