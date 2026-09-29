/* Render localized Telegram plan images. Run: node scripts/render_plans.cjs */
const fs = require('fs');
const path = require('path');
const { chromium } = require('@playwright/test');

const root = path.resolve(__dirname, '..');
const assets = path.join(root, 'web', 'assets');
const template = fs.readFileSync(path.join(assets, 'plans-template.svg'), 'utf8');
const welcome = fs.readFileSync(path.join(assets, 'welcome.svg'), 'utf8');
const brand = welcome.match(/href="(data:image\/png;base64,[^"]+)"/)[1];
const translations = {
  ru: ['Тарифы', 'Бесплатно', '2 разбора каждые 4 недели', '0 ₽', 'Подписка', '40 часов на 4 недели', '250 ₽', 'Часы', 'От 1 до 4 часов · не сгорают', 'от 50 ₽', '1,5 часа = 70 ₽ · 4 часа = 155 ₽'],
  en: ['Plans', 'Free', '2 summaries every 4 weeks', '₽0', 'Subscription', '40 hours for 4 weeks', '₽250', 'Hours', '1 to 4 hours · no expiry', 'from ₽50', '1.5 hours = ₽70 · 4 hours = ₽155'],
  es: ['Planes', 'Gratis', '2 resúmenes cada 4 semanas', '0 ₽', 'Suscripción', '40 horas por 4 semanas', '250 ₽', 'Horas', 'De 1 a 4 horas · no caducan', 'desde 50 ₽', '1,5 horas = 70 ₽ · 4 horas = 155 ₽'],
  fr: ['Offres', 'Gratuit', '2 résumés toutes les 4 semaines', '0 ₽', 'Abonnement', '40 heures pour 4 semaines', '250 ₽', 'Heures', 'De 1 à 4 heures · sans expiration', 'dès 50 ₽', '1,5 heure = 70 ₽ · 4 heures = 155 ₽'],
  de: ['Tarife', 'Kostenlos', '2 Zusammenfassungen alle 4 Wochen', '0 ₽', 'Abo', '40 Stunden für 4 Wochen', '250 ₽', 'Stunden', '1 bis 4 Stunden · ohne Verfall', 'ab 50 ₽', '1,5 Stunden = 70 ₽ · 4 Stunden = 155 ₽'],
  it: ['Piani', 'Gratis', '2 riassunti ogni 4 settimane', '0 ₽', 'Abbonamento', '40 ore per 4 settimane', '250 ₽', 'Ore', 'Da 1 a 4 ore · senza scadenza', 'da 50 ₽', '1,5 ore = 70 ₽ · 4 ore = 155 ₽'],
  pt: ['Planos', 'Grátis', '2 resumos a cada 4 semanas', '0 ₽', 'Assinatura', '40 horas por 4 semanas', '250 ₽', 'Horas', 'De 1 a 4 horas · não expiram', 'a partir de 50 ₽', '1,5 hora = 70 ₽ · 4 horas = 155 ₽'],
  tr: ['Paketler', 'Ücretsiz', 'Her 4 haftada 2 özet', '0 ₽', 'Abonelik', '4 hafta için 40 saat', '250 ₽', 'Saat', '1–4 saat · süresi dolmaz', '50 ₽’den', '1,5 saat = 70 ₽ · 4 saat = 155 ₽'],
  ar: ['الباقات', 'مجانًا', 'ملخصان كل 4 أسابيع', '0 ₽', 'اشتراك', '40 ساعة لمدة 4 أسابيع', '250 ₽', 'ساعات', 'من ساعة إلى 4 ساعات · بلا انتهاء', '50 ₽', 'ينخفض سعر الساعة عند شراء ساعات أكثر'],
  hi: ['प्लान', 'मुफ़्त', 'हर 4 हफ़्ते में 2 सारांश', '0 ₽', 'सदस्यता', '4 हफ़्तों के लिए 40 घंटे', '250 ₽', 'घंटे', '1 से 4 घंटे · कभी समाप्त नहीं', '50 ₽ से', '1.5 घंटे = 70 ₽ · 4 घंटे = 155 ₽'],
  tk: ['Nyrhnamalar', 'Mugt', 'Her 4 hepdede 2 gysgaça mazmun', '0 ₽', 'Abuna', '4 hepde üçin 40 sagat', '250 ₽', 'Sagatlar', '1-den 4 sagada çenli · möhletsiz', '50 ₽-dan', '1,5 sagat = 70 ₽ · 4 sagat = 155 ₽'],
};
const fields = ['HEADING', 'FREE', 'FREE_DETAIL', 'FREE_PRICE', 'SUBSCRIPTION', 'SUBSCRIPTION_DETAIL', 'SUBSCRIPTION_PRICE', 'HOURS', 'HOURS_DETAIL', 'HOURS_PRICE', 'EXAMPLE'];

function escapeXml(value) {
  return value.replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' })[char]);
}

(async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1200, height: 780 }, deviceScaleFactor: 1 });
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
