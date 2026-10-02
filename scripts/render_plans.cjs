/* Render the approved pricing layout in every bot interface language. */
const fs = require('fs');
const path = require('path');
const { chromium } = require('@playwright/test');

const root = path.resolve(__dirname, '..');
const assets = path.join(root, 'web', 'assets');
const template = path.join(assets, 'plans-template.html');
const output = path.join(assets, 'plans');

const source = [
  'Тарифы', 'Назад', 'Простые и понятные тарифы', 'Подписка', '1 месяц',
  'или часы без подписки', 'Бесплатно', 'каждый месяц', '2 разбора',
  'Что входит', 'Количество', 'Период', 'Оплата', 'не нужна',
  'Чтобы попробовать сервис', 'Для частых записей', 'за месяц',
  '40 часов записей', 'Объём', '40 часов', 'Для кого', 'частые записи',
  'Большой объём по одной цене', 'По часам', 'от', 'за первый час',
  '1–4 часа на выбор', '1 час', '2 часа', '3 часа', '4 часа',
  'Купленные часы не сгорают',
];

const translations = {
  ru: source,
  en: [
    'Plans', 'Back', 'Simple and transparent pricing', 'Subscription', '1 month',
    'or hours without a subscription', 'Free', 'every month', '2 summaries',
    'Included', 'Quantity', 'Period', 'Payment', 'not needed',
    'Try the service', 'For frequent recordings', 'per month',
    '40 hours of recordings', 'Volume', '40 hours', 'Best for', 'frequent recordings',
    'More hours at one price', 'By the hour', 'from', 'for the first hour',
    'Choose 1–4 hours', '1 hour', '2 hours', '3 hours', '4 hours',
    'Purchased hours never expire',
  ],
  es: [
    'Planes', 'Volver', 'Precios simples y transparentes', 'Suscripción', '1 mes',
    'u horas sin suscripción', 'Gratis', 'cada mes', '2 resúmenes',
    'Incluye', 'Cantidad', 'Período', 'Pago', 'no hace falta',
    'Para probar el servicio', 'Para grabaciones frecuentes', 'al mes',
    '40 horas de grabaciones', 'Volumen', '40 horas', 'Ideal para', 'uso frecuente',
    'Más horas por un precio fijo', 'Por horas', 'desde', 'por la primera hora',
    'Elige de 1 a 4 horas', '1 hora', '2 horas', '3 horas', '4 horas',
    'Las horas compradas no caducan',
  ],
  fr: [
    'Tarifs', 'Retour', 'Des prix simples et transparents', 'Abonnement', '1 mois',
    'ou des heures sans abonnement', 'Gratuit', 'chaque mois', '2 résumés',
    'Inclus', 'Quantité', 'Durée', 'Paiement', 'inutile',
    'Pour essayer le service', 'Pour les usages fréquents', 'par mois',
    '40 heures d’enregistrements', 'Volume', '40 heures', 'Idéal pour', 'usage fréquent',
    'Plus d’heures à prix fixe', 'À l’heure', 'dès', 'pour la première heure',
    'Choisis de 1 à 4 heures', '1 heure', '2 heures', '3 heures', '4 heures',
    'Les heures achetées n’expirent pas',
  ],
  de: [
    'Tarife', 'Zurück', 'Einfache und transparente Preise', 'Abo', '1 Monat',
    'oder Stunden ohne Abo', 'Kostenlos', 'jeden Monat', '2 Analysen',
    'Enthalten', 'Anzahl', 'Zeitraum', 'Zahlung', 'nicht nötig',
    'Zum Ausprobieren', 'Für häufige Aufnahmen', 'pro Monat',
    '40 Stunden Aufnahmen', 'Umfang', '40 Stunden', 'Für wen', 'häufige Aufnahmen',
    'Viele Stunden zum Festpreis', 'Stundenweise', 'ab', 'für die erste Stunde',
    'Wähle 1–4 Stunden', '1 Stunde', '2 Stunden', '3 Stunden', '4 Stunden',
    'Gekaufte Stunden verfallen nicht',
  ],
  it: [
    'Tariffe', 'Indietro', 'Prezzi semplici e trasparenti', 'Abbonamento', '1 mese',
    'oppure ore senza abbonamento', 'Gratis', 'ogni mese', '2 riassunti',
    'Include', 'Quantità', 'Periodo', 'Pagamento', 'non serve',
    'Per provare il servizio', 'Per registrazioni frequenti', 'al mese',
    '40 ore di registrazioni', 'Volume', '40 ore', 'Ideale per', 'uso frequente',
    'Più ore a prezzo fisso', 'A ore', 'da', 'per la prima ora',
    'Scegli da 1 a 4 ore', '1 ora', '2 ore', '3 ore', '4 ore',
    'Le ore acquistate non scadono',
  ],
  pt: [
    'Planos', 'Voltar', 'Preços simples e transparentes', 'Assinatura', '1 mês',
    'ou horas sem assinatura', 'Grátis', 'todo mês', '2 resumos',
    'Inclui', 'Quantidade', 'Período', 'Pagamento', 'não precisa',
    'Para testar o serviço', 'Para gravações frequentes', 'por mês',
    '40 horas de gravações', 'Volume', '40 horas', 'Ideal para', 'uso frequente',
    'Mais horas por preço fixo', 'Por hora', 'a partir de', 'pela primeira hora',
    'Escolha de 1 a 4 horas', '1 hora', '2 horas', '3 horas', '4 horas',
    'As horas compradas não expiram',
  ],
  tr: [
    'Paketler', 'Geri', 'Basit ve şeffaf fiyatlar', 'Abonelik', '1 ay',
    'veya aboneliksiz saatler', 'Ücretsiz', 'her ay', '2 özet',
    'Dahil olanlar', 'Adet', 'Süre', 'Ödeme', 'gerekmez',
    'Hizmeti denemek için', 'Sık kayıt yapanlar için', 'aylık',
    '40 saat kayıt', 'Miktar', '40 saat', 'Kime uygun', 'sık kayıt',
    'Tek fiyata daha çok saat', 'Saatlik', 'başlangıç', 'ilk saat için',
    '1–4 saat seç', '1 saat', '2 saat', '3 saat', '4 saat',
    'Alınan saatlerin süresi dolmaz',
  ],
  ar: [
    'الباقات', 'رجوع', 'أسعار بسيطة وواضحة', 'اشتراك', 'شهر واحد',
    'أو ساعات بلا اشتراك', 'مجاني', 'كل شهر', 'ملخصان',
    'يشمل', 'العدد', 'المدة', 'الدفع', 'غير مطلوب',
    'لتجربة الخدمة', 'للتسجيلات المتكررة', 'شهرياً',
    '40 ساعة تسجيل', 'الحجم', '40 ساعة', 'مناسب لـ', 'تسجيلات متكررة',
    'ساعات أكثر بسعر واحد', 'بالساعة', 'من', 'للساعة الأولى',
    'اختر من ساعة إلى 4', 'ساعة', 'ساعتان', '3 ساعات', '4 ساعات',
    'الساعات المشتراة لا تنتهي',
  ],
  hi: [
    'प्लान', 'वापस', 'सरल और स्पष्ट कीमतें', 'सदस्यता', '1 महीना',
    'या बिना सदस्यता घंटे', 'मुफ़्त', 'हर महीने', '2 सारांश',
    'क्या शामिल है', 'संख्या', 'अवधि', 'भुगतान', 'ज़रूरी नहीं',
    'सेवा आज़माने के लिए', 'नियमित रिकॉर्डिंग के लिए', 'प्रति माह',
    '40 घंटे की रिकॉर्डिंग', 'मात्रा', '40 घंटे', 'किसके लिए', 'नियमित रिकॉर्डिंग',
    'एक कीमत में अधिक घंटे', 'घंटे के हिसाब से', 'से', 'पहले घंटे के लिए',
    '1–4 घंटे चुनें', '1 घंटा', '2 घंटे', '3 घंटे', '4 घंटे',
    'खरीदे गए घंटे खत्म नहीं होते',
  ],
  tk: [
    'Nyrhnamalar', 'Yza', 'Ýönekeý we düşnükli nyrhlar', 'Abuna', '1 aý',
    'ýa-da abunasyz sagatlar', 'Mugt', 'her aý', '2 gysgaça mazmun',
    'Içine girýär', 'Sany', 'Döwri', 'Töleg', 'gerek däl',
    'Hyzmaty synap görmek üçin', 'Ýygy ýazgylar üçin', 'aýda',
    '40 sagat ýazgy', 'Möçberi', '40 sagat', 'Kim üçin', 'ýygy ýazgylar',
    'Bir bahadan köp sagat', 'Sagat boýunça', 'başlap', 'ilkinji sagat üçin',
    '1–4 sagat saýla', '1 sagat', '2 sagat', '3 sagat', '4 sagat',
    'Satyn alnan sagatlar möhletsiz',
  ],
};

(async () => {
  const browser = await chromium.launch();
  fs.mkdirSync(output, { recursive: true });
  try {
    const page = await browser.newPage({ viewport: { width: 978, height: 840 }, deviceScaleFactor: 2 });
    for (const [language, copy] of Object.entries(translations)) {
      if (copy.length !== source.length) throw new Error(`Incomplete ${language} translation`);
      await page.goto(`file://${template}`);
      const missing = await page.evaluate(({ source, copy, language }) => {
        document.documentElement.lang = language;
        document.body.classList.add(`lang-${language}`);
        const translated = new Set();
        const map = new Map(source.map((key, index) => [key, copy[index]]));
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        let node;
        while ((node = walker.nextNode())) {
          const key = node.textContent.trim();
          if (map.has(key)) {
            node.textContent = map.get(key);
            node.parentElement.dir = 'auto';
            translated.add(key);
          }
        }
        return source.filter(key => !translated.has(key));
      }, { source, copy, language });
      if (missing.length) throw new Error(`Missing ${language} source text: ${missing.join(', ')}`);
      const overflow = await page.evaluate(() => {
        return [...document.querySelectorAll('.card')].flatMap(card => {
          const bounds = card.getBoundingClientRect();
          const walker = document.createTreeWalker(card, NodeFilter.SHOW_TEXT);
          const problems = [];
          let node;
          while ((node = walker.nextNode())) {
            if (!node.textContent.trim()) continue;
            const range = document.createRange();
            range.selectNodeContents(node);
            const textBounds = range.getBoundingClientRect();
            if (textBounds.left < bounds.left + 7 || textBounds.right > bounds.right - 7 ||
                textBounds.bottom > bounds.bottom - 7) {
              problems.push(node.textContent.trim());
            }
          }
          return problems;
        });
      });
      if (overflow.length) throw new Error(`Text outside ${language} cards: ${overflow.join(', ')}`);
      await page.screenshot({ path: path.join(output, `${language}.png`) });
    }
    console.log(`Rendered ${Object.keys(translations).length} plan images`);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
