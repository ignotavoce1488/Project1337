// Interface language comes from the bot's saved setting, not the device locale.
const UI_TEXT = {
  ru: ['Умные заметки','Все записи','Здесь появятся ваши конспекты','Отправьте аудио или голосовое сообщение боту @slovech_bot. Конспект появится здесь.','Последний конспект','Коротко о главном','Конспект','Расшифровка','Скопировать конспект','Скопировать расшифровку','Поиск в тексте расшифровки...','Библиотека','Мои конспекты','Поиск по истории...'],
  en: ['Smart notes','All notes','Your notes will appear here','Send audio or a voice message to @slovech_bot. Your notes will appear here.','Latest notes','Key points','Notes','Transcript','Copy notes','Copy transcript','Search transcript...','Library','My notes','Search history...'],
  es: ['Notas inteligentes','Todas las notas','Tus notas aparecerán aquí','Envía audio o un mensaje de voz a @slovech_bot. Las notas aparecerán aquí.','Últimas notas','Ideas principales','Notas','Transcripción','Copiar notas','Copiar transcripción','Buscar en la transcripción...','Biblioteca','Mis notas','Buscar en el historial...'],
  fr: ['Notes intelligentes','Toutes les notes','Vos notes apparaîtront ici','Envoyez un audio ou un message vocal à @slovech_bot. Vos notes apparaîtront ici.','Dernières notes','Points clés','Notes','Transcription','Copier les notes','Copier la transcription','Rechercher dans la transcription...','Bibliothèque','Mes notes','Rechercher dans l’historique...'],
  de: ['Intelligente Notizen','Alle Notizen','Deine Notizen erscheinen hier','Sende Audio oder eine Sprachnachricht an @slovech_bot. Deine Notizen erscheinen hier.','Neueste Notizen','Kernaussagen','Notizen','Transkript','Notizen kopieren','Transkript kopieren','Transkript durchsuchen...','Bibliothek','Meine Notizen','Verlauf durchsuchen...'],
  it: ['Appunti intelligenti','Tutti gli appunti','I tuoi appunti appariranno qui','Invia un audio o un messaggio vocale a @slovech_bot. Gli appunti appariranno qui.','Ultimi appunti','Punti chiave','Appunti','Trascrizione','Copia appunti','Copia trascrizione','Cerca nella trascrizione...','Raccolta','I miei appunti','Cerca nella cronologia...'],
  pt: ['Notas inteligentes','Todas as notas','Suas notas aparecerão aqui','Envie um áudio ou mensagem de voz para @slovech_bot. Suas notas aparecerão aqui.','Notas recentes','Pontos principais','Notas','Transcrição','Copiar notas','Copiar transcrição','Pesquisar transcrição...','Biblioteca','Minhas notas','Pesquisar histórico...'],
  tr: ['Akıllı notlar','Tüm notlar','Notlarınız burada görünecek','@slovech_bot hesabına ses dosyası veya sesli mesaj gönderin. Notlarınız burada görünecek.','Son notlar','Önemli noktalar','Notlar','Döküm','Notları kopyala','Dökümü kopyala','Dökümde ara...','Kitaplık','Notlarım','Geçmişte ara...'],
  ar: ['ملاحظات ذكية','كل الملخصات','ستظهر ملخصاتك هنا','أرسل ملفاً صوتياً أو رسالة صوتية إلى @slovech_bot. ستظهر الملخصات هنا.','أحدث الملخصات','النقاط الرئيسية','الملخص','التفريغ','نسخ الملخص','نسخ التفريغ','البحث في التفريغ...','المكتبة','ملخصاتي','البحث في السجل...'],
  hi: ['स्मार्ट नोट्स','सभी नोट्स','आपके नोट्स यहाँ दिखेंगे','@slovech_bot को ऑडियो या वॉइस मैसेज भेजें। नोट्स यहाँ दिखेंगे।','नए नोट्स','मुख्य बातें','नोट्स','प्रतिलेख','नोट्स कॉपी करें','प्रतिलेख कॉपी करें','प्रतिलेख में खोजें...','लाइब्रेरी','मेरे नोट्स','इतिहास में खोजें...'],
  tk: ['Akylly bellikler','Ähli bellikler','Bellikleriňiz şu ýerde peýda bolar','@slovech_bot-a audio ýa-da ses habaryny iberiň. Bellikler şu ýerde peýda bolar.','Soňky bellikler','Esasy pikirler','Bellikler','Ýazgy','Bellikleri göçür','Ýazgyny göçür','Ýazgydan gözle...','Kitaphana','Belliklerim','Taryhda gözle...'],
};

let uiLanguage = 'ru';
const ui = (index) => (UI_TEXT[uiLanguage] || UI_TEXT.en)[index];

const SWAP_COPY = {
  ru: ['Показать оригинал', 'Читать перевод'],
  en: ['Show original', 'Read translation'],
  es: ['Ver original', 'Leer traducción'],
  fr: ['Voir l’original', 'Lire la traduction'],
  de: ['Original anzeigen', 'Übersetzung lesen'],
  it: ['Mostra originale', 'Leggi traduzione'],
  pt: ['Ver original', 'Ler tradução'],
  tr: ['Orijinali göster', 'Çeviriyi oku'],
  ar: ['عرض الأصل', 'قراءة الترجمة'],
  hi: ['मूल दिखाएँ', 'अनुवाद पढ़ें'],
  tk: ['Asyl nusgany görkez', 'Terjimäni oka'],
};

const TRANSLATE_COPY = {
  ru: ['Перевести конспект', 'Переводим конспект…', 'Не удалось перевести. Нажмите ещё раз.', 'Ждём очередь на перевод…'],
  en: ['Translate notes', 'Translating notes…', 'Translation failed. Try again.', 'Waiting to translate…'],
  es: ['Traducir notas', 'Traduciendo notas…', 'No se pudo traducir. Inténtalo de nuevo.', 'Esperando turno para traducir…'],
  fr: ['Traduire les notes', 'Traduction en cours…', 'Échec de la traduction. Réessayez.', 'En attente de traduction…'],
  de: ['Notizen übersetzen', 'Notizen werden übersetzt…', 'Übersetzung fehlgeschlagen. Erneut versuchen.', 'Warten auf die Übersetzung…'],
  it: ['Traduci appunti', 'Traduzione in corso…', 'Traduzione non riuscita. Riprova.', 'In attesa della traduzione…'],
  pt: ['Traduzir notas', 'Traduzindo notas…', 'Falha na tradução. Tente novamente.', 'A aguardar tradução…'],
  tr: ['Notları çevir', 'Notlar çevriliyor…', 'Çeviri başarısız. Tekrar deneyin.', 'Çeviri sırası bekleniyor…'],
  ar: ['ترجمة الملخص', 'جارٍ ترجمة الملخص…', 'تعذرت الترجمة. حاول مرة أخرى.', 'في انتظار الترجمة…'],
  hi: ['नोट्स का अनुवाद करें', 'नोट्स का अनुवाद हो रहा है…', 'अनुवाद नहीं हुआ। फिर कोशिश करें।', 'अनुवाद की प्रतीक्षा हो रही है…'],
  tk: ['Bellikleri terjime et', 'Bellikler terjime edilýär…', 'Terjime başartmady. Gaýtadan synanyşyň.', 'Terjime nobatyna garaşylýar…'],
};
const translateCopy = (index) => (TRANSLATE_COPY[uiLanguage] || TRANSLATE_COPY.en)[index];
const TRANSCRIPT_TRANSLATE_COPY = {
  ru: ['Ждём перевод расшифровки…', 'Переводим расшифровку…', 'Не удалось перевести расшифровку.', 'Повторить перевод'],
  en: ['Waiting to translate transcript…', 'Translating transcript…', 'Transcript translation failed.', 'Try again'],
  es: ['Esperando para traducir la transcripción…', 'Traduciendo la transcripción…', 'No se pudo traducir la transcripción.', 'Reintentar'],
  fr: ['En attente de traduction de la transcription…', 'Traduction de la transcription…', 'Échec de la traduction de la transcription.', 'Réessayer'],
  de: ['Warten auf die Transkriptübersetzung…', 'Transkript wird übersetzt…', 'Transkriptübersetzung fehlgeschlagen.', 'Erneut versuchen'],
  it: ['In attesa di tradurre la trascrizione…', 'Traduzione della trascrizione…', 'Traduzione della trascrizione non riuscita.', 'Riprova'],
  pt: ['A aguardar tradução da transcrição…', 'A traduzir a transcrição…', 'Falha na tradução da transcrição.', 'Tentar novamente'],
  tr: ['Döküm çevirisi bekleniyor…', 'Döküm çevriliyor…', 'Döküm çevirisi başarısız.', 'Tekrar dene'],
  ar: ['في انتظار ترجمة التفريغ…', 'جارٍ ترجمة التفريغ…', 'تعذرت ترجمة التفريغ.', 'حاول مرة أخرى'],
  hi: ['प्रतिलेख अनुवाद की प्रतीक्षा हो रही है…', 'प्रतिलेख का अनुवाद हो रहा है…', 'प्रतिलेख का अनुवाद नहीं हुआ।', 'फिर कोशिश करें'],
  tk: ['Ýazgynyň terjimesine garaşylýar…', 'Ýazgy terjime edilýär…', 'Ýazgynyň terjimesi başartmady.', 'Gaýtadan synanyş'],
};
const transcriptTranslateCopy = (index) =>
  (TRANSCRIPT_TRANSLATE_COPY[uiLanguage] || TRANSCRIPT_TRANSLATE_COPY.en)[index];
const SEARCH_ERROR = {
  ru: 'Не удалось выполнить поиск.', en: 'Search is unavailable.',
  es: 'No se pudo buscar.', fr: 'Recherche indisponible.',
  de: 'Suche nicht verfügbar.', it: 'Ricerca non disponibile.',
  pt: 'Pesquisa indisponível.', tr: 'Arama kullanılamıyor.',
  ar: 'البحث غير متاح.', hi: 'खोज उपलब्ध नहीं है।',
  tk: 'Gözleg elýeterli däl.',
};
const searchError = () => SEARCH_ERROR[uiLanguage] || SEARCH_ERROR.en;

function languageSwapLabel(showOriginal, languageCode) {
  const label = (SWAP_COPY[uiLanguage] || SWAP_COPY.en)[showOriginal ? 0 : 1];
  if (!languageCode || languageCode === 'auto') return label;
  let languageName = languageCode.toUpperCase();
  try { languageName = new Intl.DisplayNames([uiLanguage], {type: 'language'}).of(languageCode); } catch (_) {}
  return `${label} (${languageName})`;
}

function applyLanguage(code) {
  uiLanguage = UI_TEXT[code] ? code : 'en';
  document.documentElement.lang = uiLanguage;
  document.documentElement.dir = uiLanguage === 'ar' ? 'rtl' : 'ltr';
  document.querySelectorAll('[data-i18n]').forEach((element) => {
    element.textContent = ui(Number(element.dataset.i18n));
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach((element) => {
    element.placeholder = ui(Number(element.dataset.i18nPlaceholder));
  });
}

async function loadInterfaceLanguage() {
  try {
    const response = await apiFetch('/api/preferences');
    if (response.ok) applyLanguage((await response.json()).interface_language);
  } catch (_) { /* Keep the Russian default when authentication is unavailable. */ }
}
