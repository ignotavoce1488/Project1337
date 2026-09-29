/* Render the static Telegram plan cards. Run: node scripts/render_plans.cjs */
const fs = require('fs');
const path = require('path');
const { chromium } = require('@playwright/test');

const root = path.resolve(__dirname, '..');
const assets = path.join(root, 'web', 'assets');
const template = fs.readFileSync(path.join(assets, 'plans-template.svg'), 'utf8');
const welcome = fs.readFileSync(path.join(assets, 'welcome.svg'), 'utf8');
const brand = welcome.match(/href="(data:image\/png;base64,[^"]+)"/)[1];
const translations = {
  ru: ['Выбирай свой формат', 'Бесплатно', 'Подписка', 'Часы'],
  en: ['Choose your plan', 'Free', 'Subscription', 'Hours'],
  es: ['Elige tu plan', 'Gratis', 'Suscripción', 'Horas'],
  fr: ['Choisis ton forfait', 'Gratuit', 'Abonnement', 'Heures'],
  de: ['Wähle deinen Tarif', 'Kostenlos', 'Abo', 'Stunden'],
  it: ['Scegli il tuo piano', 'Gratis', 'Abbonamento', 'Ore'],
  pt: ['Escolha seu plano', 'Grátis', 'Assinatura', 'Horas'],
  tr: ['Planını seç', 'Ücretsiz', 'Abonelik', 'Saatler'],
  ar: ['اختر خطتك', 'مجاني', 'اشتراك', 'ساعات'],
  hi: ['अपना प्लान चुनें', 'मुफ़्त', 'सदस्यता', 'घंटे'],
  tk: ['Nyrhnamaňy saýla', 'Mugt', 'Abuna', 'Sagatlar'],
};

function escapeXml(value) {
  return value.replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;'}[char]));
}

(async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1200, height: 760 }, deviceScaleFactor: 1 });
    const directory = path.join(assets, 'plans');
    fs.mkdirSync(directory, { recursive: true });
    for (const [language, [heading, free, subscription, hours]] of Object.entries(translations)) {
      const svg = template
        .replace('__BRAND_IMAGE__', brand)
        .replace('__HEADING__', escapeXml(heading))
        .replace('__FREE__', escapeXml(free))
        .replace('__SUBSCRIPTION__', escapeXml(subscription))
        .replace('__HOURS__', escapeXml(hours));
      await page.goto(`data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`);
      await page.screenshot({ path: path.join(directory, `${language}.png`) });
    }
    console.log(`Rendered ${Object.keys(translations).length} plan cards`);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
