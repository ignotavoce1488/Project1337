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
  'BADGE', 'FREE_UNIT', 'SUB_UNIT', 'HOUR_UNIT',
];
const translations = {
  ru: ['Простые и понятные тарифы', 'Начните бесплатно. Больше часов — когда понадобятся.', 'Бесплатно', 'Подписка', 'По часам',
    '0 ₽', '250 ₽', '50 ₽', '2 разбора', 'каждые 4 недели', '40 часов записей', 'на 4 недели', 'От 1 до 4 часов', 'Часы не сгорают'],
  en: ['Simple, clear pricing', 'Start free. Add more hours when you need them.', 'Free', 'Subscription', 'By the hour',
    '₽0', '₽250', '₽50', '2 recordings', 'every 4 weeks', '40 hours of audio', 'for 4 weeks', 'Choose 1 to 4 hours', 'No expiry'],
  es: ['Precios claros y sencillos', 'Empieza gratis. Añade horas cuando las necesites.', 'Gratis', 'Suscripción', 'Por horas',
    '0 ₽', '250 ₽', '50 ₽', '2 grabaciones', 'cada 4 semanas', '40 horas de audio', 'por 4 semanas', 'De 1 a 4 horas', 'Sin vencimiento'],
  fr: ['Des tarifs simples et clairs', 'Commence gratuitement. Ajoute des heures si besoin.', 'Gratuit', 'Abonnement', 'À la carte',
    '0 ₽', '250 ₽', '50 ₽', '2 enregistrements', 'sur 4 semaines', '40 heures d’audio', 'pour 4 semaines', 'De 1 à 4 heures', 'Sans expiration'],
  de: ['Einfach. Klar. Fair.', 'Starte kostenlos. Buche bei Bedarf weitere Stunden.', 'Kostenlos', 'Abo', 'Einzelstunden',
    '0 ₽', '250 ₽', '50 ₽', '2 Aufnahmen', 'alle 4 Wochen', '40 Stunden Audio', 'für 4 Wochen', '1–4 Stunden', 'Ohne Ablaufdatum'],
  it: ['Prezzi semplici e chiari', 'Inizia gratis. Aggiungi ore quando ti servono.', 'Gratis', 'Abbonamento', 'A ore',
    '0 ₽', '250 ₽', '50 ₽', '2 registrazioni', 'ogni 4 settimane', '40 ore di audio', 'per 4 settimane', 'Da 1 a 4 ore', 'Senza scadenza'],
  pt: ['Preços simples e claros', 'Comece grátis. Compre mais horas quando precisar.', 'Grátis', 'Assinatura', 'Por horas',
    '0 ₽', '250 ₽', '50 ₽', '2 gravações', 'a cada 4 semanas', '40 horas de áudio', 'por 4 semanas', 'De 1 a 4 horas', 'Sem vencimento'],
  tr: ['Basit ve açık fiyatlar', 'Ücretsiz başla. Gerektiğinde saat ekle.', 'Ücretsiz', 'Abonelik', 'Saatlik',
    '0 ₽', '250 ₽', '50 ₽', '2 kayıt', 'her 4 haftada', '40 saat ses kaydı', '4 hafta boyunca', '1–4 saat seç', 'Süresi dolmaz'],
  ar: ['أسعار بسيطة وواضحة', 'ابدأ مجاناً، وأضف ساعات عند الحاجة.', 'مجاناً', 'اشتراك', 'بالساعة',
    '0 ₽', '250 ₽', '50 ₽', 'تسجيلان', 'كل 4 أسابيع', '40 ساعة صوتية', 'لمدة 4 أسابيع', 'اختر من 1 إلى 4 ساعات', 'الساعات لا تنتهي'],
  hi: ['सरल और स्पष्ट कीमतें', 'मुफ़्त शुरू करें। ज़रूरत पड़ने पर घंटे जोड़ें।', 'मुफ़्त', 'सदस्यता', 'घंटे खरीदें',
    '0 ₽', '250 ₽', '50 ₽', '2 रिकॉर्डिंग', 'हर 4 हफ़्ते में', '40 घंटे की ऑडियो', '4 हफ़्तों के लिए', '1 से 4 घंटे चुनें', 'कोई समाप्ति नहीं'],
  tk: ['Ýönekeý we düşnükli nyrhlar', 'Mugt başla. Gerek bolanda goşmaça sagat al.', 'Mugt', 'Abuna', 'Sagat boýunça',
    '0 ₽', '250 ₽', '50 ₽', '2 ýazgy', 'her 4 hepdede', '40 sagat audio', '4 hepde üçin', '1–4 sagat saýla', 'Möhleti ýok'],
};
const units = {
  ru: ['ЧАСТЫЕ ЗАПИСИ', 'за 4 недели', 'за 4 недели', 'за первый час'],
  en: ['REGULAR USE', 'per 4 weeks', 'per 4 weeks', 'for the first hour'],
  es: ['USO FRECUENTE', 'por 4 semanas', 'por 4 semanas', 'por la primera hora'],
  fr: ['USAGE RÉGULIER', 'pour 4 semaines', 'pour 4 semaines', 'pour la première heure'],
  de: ['REGELMÄSSIG', 'für 4 Wochen', 'für 4 Wochen', 'für die erste Stunde'],
  it: ['USO FREQUENTE', 'per 4 settimane', 'per 4 settimane', 'per la prima ora'],
  pt: ['USO FREQUENTE', 'por 4 semanas', 'por 4 semanas', 'pela primeira hora'],
  tr: ['DÜZENLİ KULLANIM', '4 hafta için', '4 hafta için', 'ilk saat için'],
  ar: ['للاستخدام المنتظم', 'كل 4 أسابيع', 'لمدة 4 أسابيع', 'للساعة الأولى'],
  hi: ['नियमित उपयोग', 'हर 4 हफ़्ते', '4 हफ़्तों के लिए', 'पहले घंटे के लिए'],
  tk: ['YZYGLY ULANIŞ', 'her 4 hepde', '4 hepde üçin', 'ilkinji sagat üçin'],
};

function escapeXml(value) {
  return value.replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' })[char]);
}

(async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1200, height: 850 }, deviceScaleFactor: 1 });
    const directory = path.join(assets, 'plans');
    fs.mkdirSync(directory, { recursive: true });
    for (const [language, copy] of Object.entries(translations)) {
      let svg = template.replace('__BRAND_IMAGE__', brand);
      const localized = copy.concat(units[language]);
      fields.forEach((field, index) => { svg = svg.replace(`__${field}__`, escapeXml(localized[index])); });
      await page.goto(`data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`);
      await page.waitForTimeout(100);
      const overflows = await page.evaluate(() => {
        const columns = { 224: [55, 393], 128: [55, 393], 600: [431, 769],
          504: [431, 769], 976: [807, 1145], 880: [807, 1145] };
        return [...document.querySelectorAll('text')].flatMap(element => {
          const x = Number(element.getAttribute('x'));
          const y = Number(element.getAttribute('y'));
          if (!columns[x] || y < 300) return [];
          const bounds = element.getBBox();
          const [left, right] = columns[x];
          return bounds.x < left + 16 || bounds.x + bounds.width > right - 16
            ? [element.textContent] : [];
        });
      });
      if (overflows.length) throw new Error(`Text outside ${language} cards: ${overflows.join(', ')}`);
      await page.screenshot({ path: path.join(directory, `${language}.png`) });
    }
    console.log(`Rendered ${Object.keys(translations).length} plan images`);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
