/* Render localized Telegram plan images. Run: node scripts/render_plans.cjs */
const fs = require('fs');
const path = require('path');
const { chromium } = require('@playwright/test');

const root = path.resolve(__dirname, '..');
const assets = path.join(root, 'web', 'assets');
const template = fs.readFileSync(path.join(assets, 'plans-template.svg'), 'utf8');
const welcome = fs.readFileSync(path.join(assets, 'welcome.svg'), 'utf8');
const brand = welcome.match(/href="(data:image\/png;base64,[^"]+)"/)[1];

const fields = [
  'HEADING', 'INTRO', 'FREE', 'SUBSCRIPTION', 'HOURS',
  'FREE_PRICE', 'SUB_PRICE', 'HOUR_PRICE',
  'FREE_LINE1', 'FREE_LINE2', 'SUB_LINE1', 'SUB_LINE2', 'HOUR_LINE1', 'HOUR_LINE2',
];
const translations = {
  ru: ['Тарифы', 'Начните бесплатно. Больше часов — когда понадобятся.', 'Бесплатно', 'Подписка', 'Без подписки',
    '0 ₽', '250 ₽', 'от 50 ₽', '2 разбора', 'каждые 4 недели', '40 часов записей', 'на 4 недели', 'От 1 до 4 часов', 'Часы не сгорают'],
  en: ['Plans', 'Start free. Add more hours when you need them.', 'Free', 'Subscription', 'Pay as you go',
    '₽0', '₽250', 'from ₽50', '2 recordings', 'every 4 weeks', '40 hours of audio', 'for 4 weeks', 'Choose 1 to 4 hours', 'Hours do not expire'],
  es: ['Planes', 'Empieza gratis. Añade horas cuando las necesites.', 'Gratis', 'Suscripción', 'Por horas',
    '0 ₽', '250 ₽', 'desde 50 ₽', '2 grabaciones', 'cada 4 semanas', '40 horas de audio', 'por 4 semanas', 'Elige de 1 a 4 horas', 'Las horas no caducan'],
  fr: ['Offres', 'Commence gratuitement. Ajoute des heures si besoin.', 'Gratuit', 'Abonnement', 'À la carte',
    '0 ₽', '250 ₽', 'dès 50 ₽', '2 enregistrements', 'toutes les 4 semaines', '40 heures d’audio', 'pour 4 semaines', 'Choisis 1 à 4 heures', 'Heures sans expiration'],
  de: ['Tarife', 'Starte kostenlos. Buche bei Bedarf weitere Stunden.', 'Kostenlos', 'Abo', 'Einzelstunden',
    '0 ₽', '250 ₽', 'ab 50 ₽', '2 Aufnahmen', 'alle 4 Wochen', '40 Stunden Audio', 'für 4 Wochen', 'Wähle 1 bis 4 Stunden', 'Stunden verfallen nicht'],
  it: ['Piani', 'Inizia gratis. Aggiungi ore quando ti servono.', 'Gratis', 'Abbonamento', 'A ore',
    '0 ₽', '250 ₽', 'da 50 ₽', '2 registrazioni', 'ogni 4 settimane', '40 ore di audio', 'per 4 settimane', 'Scegli da 1 a 4 ore', 'Le ore non scadono'],
  pt: ['Planos', 'Comece grátis. Compre mais horas quando precisar.', 'Grátis', 'Assinatura', 'Por horas',
    '0 ₽', '250 ₽', 'desde 50 ₽', '2 gravações', 'a cada 4 semanas', '40 horas de áudio', 'por 4 semanas', 'Escolha de 1 a 4 horas', 'As horas não expiram'],
  tr: ['Paketler', 'Ücretsiz başla. Gerektiğinde saat ekle.', 'Ücretsiz', 'Abonelik', 'Saatlik',
    '0 ₽', '250 ₽', '50 ₽’den', '2 kayıt', 'her 4 haftada', '40 saat ses kaydı', '4 hafta boyunca', '1–4 saat seç', 'Saatlerin süresi dolmaz'],
  ar: ['الباقات', 'ابدأ مجاناً، وأضف ساعات عند الحاجة.', 'مجاناً', 'اشتراك', 'بالساعة',
    '0 ₽', '250 ₽', '50 ₽', 'تسجيلان', 'كل 4 أسابيع', '40 ساعة صوتية', 'لمدة 4 أسابيع', 'اختر من 1 إلى 4 ساعات', 'الساعات لا تنتهي'],
  hi: ['प्लान', 'मुफ़्त शुरू करें। ज़रूरत पड़ने पर घंटे जोड़ें।', 'मुफ़्त', 'सदस्यता', 'घंटे खरीदें',
    '0 ₽', '250 ₽', '50 ₽ से', '2 रिकॉर्डिंग', 'हर 4 हफ़्ते में', '40 घंटे की ऑडियो', '4 हफ़्तों के लिए', '1 से 4 घंटे चुनें', 'घंटे समाप्त नहीं होते'],
  tk: ['Nyrhnamalar', 'Mugt başla. Gerek bolanda goşmaça sagat al.', 'Mugt', 'Abuna', 'Sagat boýunça',
    '0 ₽', '250 ₽', '50 ₽-dan', '2 ýazgy', 'her 4 hepdede', '40 sagat audio', '4 hepde üçin', '1–4 sagat saýla', 'Sagatlar möhletsiz'],
};

function escapeXml(value) {
  return value.replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' })[char]);
}

(async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1200, height: 800 }, deviceScaleFactor: 1 });
    const directory = path.join(assets, 'plans');
    fs.mkdirSync(directory, { recursive: true });
    for (const [language, copy] of Object.entries(translations)) {
      let svg = template.replace('__BRAND_IMAGE__', brand);
      fields.forEach((field, index) => { svg = svg.replace(`__${field}__`, escapeXml(copy[index])); });
      await page.goto(`data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`);
      await page.waitForTimeout(100);
      await page.screenshot({ path: path.join(directory, `${language}.png`) });
    }
    console.log(`Rendered ${Object.keys(translations).length} plan images`);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
