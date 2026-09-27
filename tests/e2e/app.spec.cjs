const { test, expect } = require('@playwright/test');
const crypto = require('node:crypto');

function signed() {
  const values = { auth_date: String(Math.floor(Date.now()/1000)), user: JSON.stringify({id:123}) };
  const secret = crypto.createHmac('sha256', 'WebAppData').update('123456789:abcdefghijklmnopqrstuvwxyz123456789').digest();
  values.hash = crypto.createHmac('sha256', secret).update(Object.keys(values).sort().map(key => `${key}=${values[key]}`).join('\n')).digest('hex');
  return new URLSearchParams(values).toString();
}

async function prepare(page, authenticated = true) {
  await page.route('https://telegram.org/**', route => route.fulfill({contentType:'application/javascript', body:''}));
  await page.route('https://fonts.googleapis.com/**', route => route.fulfill({contentType:'text/css', body:''}));
  await page.addInitScript(({initData}) => {
    window.Telegram = {WebApp: {initData, ready(){}, expand(){}, disableVerticalSwipes(){}, onEvent(){},
      colorScheme:'dark', themeParams:{}, HapticFeedback:{impactOccurred(){},notificationOccurred(){}},
      setHeaderColor(){}, setBackgroundColor(){}}};
  }, {initData: authenticated ? signed() : ''});
}

test('Mini App follows the language selected in the bot', async ({page}) => {
  await prepare(page);
  await page.route('**/api/preferences', async route => {
    await route.fulfill({json: {interface_language: 'ar'}});
  });
  await page.goto('/app');
  await expect(page.locator('html')).toHaveAttribute('lang', 'ar');
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
  await expect(page.locator('[data-i18n="1"]')).toHaveText('كل الملخصات');
  await expect(page.locator('[data-i18n="7"]')).toHaveText('التفريغ');
});

test('selected language is primary and swap shows the original', async ({page}) => {
  await prepare(page);
  await page.route('**/api/preferences', route => route.fulfill({json: {interface_language: 'es'}}));
  await page.route('**/api/lecture/latest', async route => {
    const response = await route.fetch();
    const lecture = await response.json();
    Object.assign(lecture, {
      language: 'en', title: 'Original title', summary: '## Original notes', key_points: ['Original point'],
      translation_language: 'es', title_translated: 'Título traducido',
      summary_translated: '## Notas traducidas', key_points_translated: ['Punto traducido'],
    });
    await route.fulfill({response, json: lecture});
  });
  await page.goto('/app');
  await expect(page.locator('#lectureTitle')).toHaveText('Título traducido');
  await expect(page.locator('#summaryBox')).toContainText('Notas traducidas');
  await page.locator('#langToggleBtn').click();
  await expect(page.locator('#lectureTitle')).toHaveText('Original title');
  await expect(page.locator('#summaryBox')).toContainText('Original notes');
  await page.locator('#langToggleBtn').click();
  await expect(page.locator('#lectureTitle')).toHaveText('Título traducido');
});

test('old recording can be translated from the Mini App', async ({page}) => {
  await prepare(page);
  await page.route('**/api/preferences', route => route.fulfill({json: {interface_language: 'es'}}));
  await page.route('**/api/lecture/lecture100/translation', route => route.fulfill({
    json: {state: route.request().method() === 'POST' ? 'pending' : 'ready', language: 'es'}
  }));
  await page.route('**/api/lecture/lecture100', async route => {
    const response = await route.fetch();
    const lecture = await response.json();
    Object.assign(lecture, {translation_language: 'es', title_translated: 'Clase cien',
      summary_translated: '## Resumen en español', key_points_translated: ['Idea principal']});
    await route.fulfill({response, json: lecture});
  });
  await page.goto('/app');
  await expect(page.locator('#translateBtn')).toBeVisible();
  await page.locator('#translateBtn').click();
  await expect(page.locator('#lectureTitle')).toHaveText('Clase cien');
  await expect(page.locator('#langToggleBtn')).toBeVisible();
});

test('translation progress remains visible after reopening the notes', async ({page}) => {
  await prepare(page);
  let progressState = 'pending';
  let requested = false;
  await page.route('**/api/preferences', route => route.fulfill({json: {interface_language: 'es'}}));
  await page.route('**/api/lecture/lecture100/translation', route => {
    if (route.request().method() === 'POST') requested = true;
    return route.fulfill({json: {state: !requested ? 'missing' : progressState, language: 'es'}});
  });
  await page.route('**/api/lecture/lecture100', async route => {
    const response = await route.fetch();
    const lecture = await response.json();
    if (progressState === 'ready') Object.assign(lecture, {translation_language: 'es', title_translated: 'Clase cien',
      summary_translated: '## Resumen en español', key_points_translated: ['Idea principal']});
    await route.fulfill({response, json: lecture});
  });
  await page.goto('/app');
  await page.locator('#translateBtn').click();
  await expect(page.locator('#translateProgress')).toBeVisible();
  await expect(page.locator('#translateStatus')).toContainText('Esperando');
  await expect(page.locator('#translateTrack')).toHaveAttribute('role', 'progressbar');
  await expect(page.locator('#translateBtn')).toBeDisabled();
  await page.screenshot({path: 'test-results/translation-progress.png', fullPage: true});
  await page.reload();
  await expect(page.locator('#translateProgress')).toBeVisible();
  await expect(page.locator('#translateBtn')).toBeDisabled();
  progressState = 'running';
  await expect(page.locator('#translateStatus')).toContainText('Traduciendo', {timeout: 7000});
  await expect(page.locator('#translateElapsed')).not.toHaveText('');
  progressState = 'ready';
  await expect(page.locator('#lectureTitle')).toHaveText('Clase cien', {timeout: 7000});
  await expect(page.locator('#translateProgress')).toBeHidden();
  await expect(page.locator('#langToggleBtn')).toBeVisible();
});

test('progress sweep follows RTL and reduced motion stops animation', async ({page}) => {
  await prepare(page);
  let requested = false;
  await page.route('**/api/preferences', route => route.fulfill({json: {interface_language: 'ar'}}));
  await page.route('**/api/lecture/lecture100/translation', route => {
    if (route.request().method() === 'POST') requested = true;
    return route.fulfill({json: {state: requested ? 'pending' : 'missing', language: 'ar'}});
  });
  await page.goto('/app');
  await page.locator('#translateBtn').click();
  await expect(page.locator('#translateTrack')).toBeVisible();
  await expect(page.locator('#translateTrack .translation-track-fill')).toHaveCSS('animation-name', 'translation-sweep-rtl');
  const sweep = await page.evaluate(() => {
    const fill = document.querySelector('#translateTrack .translation-track-fill');
    const track = document.getElementById('translateTrack').getBoundingClientRect();
    const animation = fill.getAnimations()[0];
    animation.pause();
    const positions = [100, 400, 800, 1200, 1600, 2000].map(time => {
      animation.currentTime = time;
      return fill.getBoundingClientRect().left;
    });
    animation.currentTime = 0;
    const start = fill.getBoundingClientRect();
    animation.currentTime = 2199;
    const end = fill.getBoundingClientRect();
    return {positions, startsOffscreen: start.left >= track.right,
      endsOffscreen: end.right <= track.left};
  });
  expect(sweep.positions.every((position, index) =>
    index === 0 || position < sweep.positions[index - 1])).toBe(true);
  expect(sweep.startsOffscreen).toBe(true);
  expect(sweep.endsOffscreen).toBe(true);
  await page.emulateMedia({reducedMotion: 'reduce'});
  await expect(page.locator('#translateTrack .translation-track-fill')).toHaveCSS('animation-name', 'none');
  const reducedProgress = await page.evaluate(() => {
    const fill = document.getElementById('transcriptTranslationFill');
    window.resetTranscriptProgressSpring();
    fill.dataset.determinate = 'true';
    window.moveTranscriptProgressTo(.6);
    return new DOMMatrixReadOnly(fill.style.transform).a;
  });
  expect(reducedProgress).toBeCloseTo(.6, 3);
});

test('failed translation shows a retry state', async ({page}) => {
  await prepare(page);
  let failed = false;
  let requested = false;
  await page.route('**/api/preferences', route => route.fulfill({json: {interface_language: 'es'}}));
  await page.route('**/api/lecture/lecture100/translation', route => {
    if (route.request().method() === 'POST') requested = true;
    return route.fulfill({json: {state: !requested ? 'missing' : failed ? 'failed' : 'pending', language: 'es'}});
  });
  await page.goto('/app');
  await page.locator('#translateBtn').click();
  failed = true;
  await expect(page.locator('#translateStatus')).toContainText('Inténtalo de nuevo', {timeout: 7000});
  await expect(page.locator('#translateBtn')).toBeEnabled();
  await expect(page.locator('#translateTrack')).toBeHidden();
});

test('translated notes also translate the transcript and keep the original', async ({page}) => {
  await prepare(page);
  let ready = false;
  await page.route('**/api/preferences', route => route.fulfill({json: {interface_language: 'de'}}));
  await page.route('**/api/lecture/lecture100/transcript-translation', route => route.fulfill({
    json: {state: route.request().method() === 'POST' ? 'pending' : ready ? 'ready' : 'running',
      completed: ready ? 2 : 1, total: 2, language: 'de'}
  }));
  const translatedLecture = async route => {
    const response = await route.fetch();
    const lecture = await response.json();
    Object.assign(lecture, {language: 'ru', title: 'Квантовая физика',
      summary: 'Русский конспект', transcription: 'Русская расшифровка о квантовой физике.',
      formatted_transcription: null, translation_language: 'de',
      title_translated: 'Quantenphysik', summary_translated: 'Deutsche Notizen',
      key_points_translated: ['Deutscher Punkt']});
    if (ready) Object.assign(lecture, {transcription_translation_language: 'de',
      transcription_translated: 'Deutsches Transkript über Quantenphysik.'});
    await route.fulfill({response, json: lecture});
  };
  await page.route('**/api/lecture/latest', translatedLecture);
  await page.route('**/api/lecture/lecture100', translatedLecture);
  await page.goto('/app');
  await expect(page.locator('#summaryBox')).toContainText('Deutsche Notizen');
  await page.locator('[data-tab="transcript"]').click();
  await expect(page.locator('#transcriptTranslationProgress')).toBeVisible();
  await expect(page.locator('#transcriptBox')).toContainText('Русская расшифровка');
  await expect(page.locator('#transcriptTranslationFill')).toHaveCSS('animation-name', 'translation-sweep');
  const sweep = await page.evaluate(() => {
    const fill = document.getElementById('transcriptTranslationFill');
    const track = document.getElementById('transcriptTranslationTrack').getBoundingClientRect();
    const animation = fill.getAnimations()[0];
    animation.pause();
    const positions = [100, 400, 800, 1200, 1600, 2000].map(time => {
      animation.currentTime = time;
      return fill.getBoundingClientRect().left;
    });
    animation.currentTime = 0;
    const start = fill.getBoundingClientRect();
    animation.currentTime = 2199;
    const end = fill.getBoundingClientRect();
    return {positions, startsOffscreen: start.right <= track.left,
      endsOffscreen: end.left >= track.right};
  });
  expect(sweep.positions.every((position, index) =>
    index === 0 || position > sweep.positions[index - 1])).toBe(true);
  expect(sweep.startsOffscreen).toBe(true);
  expect(sweep.endsOffscreen).toBe(true);
  await expect(page.locator('#transcriptTranslationCount')).toHaveText('1/2 · 50%', {timeout: 7000});
  const springSamples = await page.evaluate(async () => {
    const fill = document.getElementById('transcriptTranslationFill');
    window.resetTranscriptProgressSpring();
    fill.dataset.determinate = 'true';
    window.moveTranscriptProgressTo(.5);
    const samples = [];
    for (let index = 0; index < 7; index++) {
      await new Promise(resolve => setTimeout(resolve, 100));
      samples.push(new DOMMatrixReadOnly(getComputedStyle(fill).transform).a);
    }
    return samples;
  });
  expect(springSamples.every((position, index) =>
    index === 0 || position >= springSamples[index - 1])).toBe(true);
  expect(springSamples.at(-1)).toBeGreaterThan(.48);
  expect(springSamples.every(position => position <= .501)).toBe(true);
  await page.screenshot({path: 'test-results/transcript-progress-motion.png', fullPage: true});
  const nextChunkSamples = await page.evaluate(async () => {
    const fill = document.getElementById('transcriptTranslationFill');
    window.moveTranscriptProgressTo(.8);
    const samples = [];
    for (let index = 0; index < 7; index++) {
      await new Promise(resolve => setTimeout(resolve, 100));
      samples.push(new DOMMatrixReadOnly(getComputedStyle(fill).transform).a);
    }
    return samples;
  });
  expect(nextChunkSamples.every((position, index) =>
    index === 0 || position >= nextChunkSamples[index - 1])).toBe(true);
  expect(nextChunkSamples.at(-1)).toBeGreaterThan(.78);
  expect(nextChunkSamples.every(position => position <= .801)).toBe(true);
  ready = true;
  await expect(page.locator('#transcriptBox')).toContainText('Deutsches Transkript', {timeout: 7000});
  await expect(page.locator('#transcriptTranslationProgress')).toBeHidden();
  await page.locator('#langToggleBtn').click();
  await expect(page.locator('#transcriptBox')).toContainText('Русская расшифровка');
  await page.locator('#langToggleBtn').click();
  await expect(page.locator('#transcriptBox')).toContainText('Deutsches Transkript');
});

test('history search includes transcript text', async ({page}) => {
  await prepare(page);
  await page.goto('/app');
  await page.locator('#openHistoryBtn').click();
  await page.locator('#historySearchInput').fill('world');
  await expect(page.locator('.history-card')).toHaveCount(50);
  await expect(page.locator('.history-card-preview').first()).toContainText('Hello world');
});

test('authorization, translated lecture, history pagination, keyboard navigation', async ({page}) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await prepare(page);
  await page.goto('/app');
  await expect(page.locator('#lectureTitle')).toHaveText('Лекция 100');
  await expect(page.locator('#summaryBox')).toContainText('Русский текст');
  await expect(page.locator('.takeaway-marker')).toHaveText('01');
  await expect(page.locator('.takeaway-card svg')).toHaveCount(0);
  await expect(page.locator('.takeaway-card')).toHaveCSS('align-items', 'center');
  await page.locator('#langToggleBtn').click();
  await expect(page.locator('#lectureTitle')).toHaveText('Lecture 100');
  await page.locator('#openHistoryBtn').click();
  await expect(page.locator('.history-card')).toHaveCount(101);
  await page.waitForTimeout(300);
  await page.screenshot({path:'test-results/mini-app-history.png', fullPage:true});
  await page.locator('#historySearchInput').fill('Lecture 0');
  await expect(page.locator('.history-card')).toHaveCount(1);
  await page.locator('.history-card').focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('#lectureTitle')).toHaveText('Лекция 0');
  await expect(page).toHaveURL(/id=lecture0/);
  await page.waitForTimeout(300);
  await page.screenshot({path:'test-results/mini-app-mobile.png', fullPage:true});
  expect(errors).toEqual([]);
});

test('long takeaway lists stay compact until expanded and reset for another lecture', async ({page}) => {
  await prepare(page);
  await page.route('**/api/lecture/latest', async route => {
    const response = await route.fetch();
    const lecture = await response.json();
    lecture.key_points_ru = Array.from({length: 8}, (_, index) => `Подробный тезис ${index + 1}`);
    lecture.key_points = Array.from({length: 8}, (_, index) => `Detailed point ${index + 1}`);
    await route.fulfill({response, json: lecture});
  });
  await page.goto('/app');
  await expect(page.locator('.takeaway-card')).toHaveCount(3);
  await expect(page.locator('#takeawaysMoreBtn')).toHaveText('Показать ещё 5');
  await expect(page.locator('#takeawaysMoreBtn')).toHaveAttribute('aria-expanded', 'false');
  await expect(page.locator('#summaryBox')).toContainText('Русский текст');

  await page.locator('#takeawaysMoreBtn').click();
  await expect(page.locator('.takeaway-card')).toHaveCount(8);
  await expect(page.locator('#takeawaysMoreBtn')).toHaveText('Свернуть');
  await expect(page.locator('#takeawaysMoreBtn')).toHaveAttribute('aria-expanded', 'true');
  await page.locator('#langToggleBtn').click();
  await expect(page.locator('.takeaway-card')).toHaveCount(8);
  await expect(page.locator('.takeaway-card').first()).toContainText('Detailed point 1');
  await page.locator('#takeawaysMoreBtn').click();
  await expect(page.locator('.takeaway-card')).toHaveCount(3);

  await page.locator('#openHistoryBtn').click();
  await page.locator('.history-card[data-id="lecture0"]').click();
  await expect(page.locator('#takeawaysMoreBtn')).toBeHidden();
  await expect(page.locator('.takeaway-card')).toHaveCount(1);
});

test('unauthenticated session receives usable error state', async ({page}) => {
  await prepare(page, false);
  await page.goto('/app');
  await expect(page.locator('#emptyState')).toBeVisible();
  await expect(page.locator('#emptyState h2')).toHaveText('Вход только через Telegram');
  await expect(page.locator('#lectureView')).toBeHidden();
});

test('blocked localStorage does not prevent loading', async ({page}) => {
  await prepare(page);
  await page.addInitScript(() => {
    Object.defineProperty(window, 'localStorage', {get(){throw new Error('Storage blocked');}});
  });
  await page.goto('/app');
  await expect(page.locator('#lectureTitle')).toHaveText('Лекция 100');
  await page.locator('#themeToggleBtn').click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await page.waitForTimeout(300);
  await page.screenshot({path:'test-results/mini-app-light.png', fullPage:true});
});

test('transcript search treats special characters as text and resets on lecture change', async ({page}) => {
  await prepare(page);
  await page.route('**/api/lecture/latest', async route => {
    const response = await route.fetch();
    const lecture = await response.json();
    lecture.transcription = 'A & B <test> 12:34 end';
    await route.fulfill({response, json: lecture});
  });
  await page.goto('/app');
  await page.locator('[data-tab="transcript"]').click();
  await page.locator('#transcriptSearch').fill('amp');
  await expect(page.locator('#transcriptBox .word-highlight')).toHaveCount(0);
  await page.locator('#transcriptSearch').fill('&');
  await expect(page.locator('#transcriptBox .word-highlight')).toHaveText('&');
  await page.locator('#transcriptSearch').fill('<test>');
  await expect(page.locator('#transcriptBox .word-highlight')).toHaveText('<test>');
  await expect(page.locator('#transcriptBox')).not.toContainText('12:34');

  await page.locator('#openHistoryBtn').click();
  await page.locator('.history-card[data-id="lecture0"]').click();
  await expect(page.locator('#lectureTitle')).toHaveText('Лекция 0');
  await expect(page.locator('#transcriptSearch')).toHaveValue('');
  await expect(page.locator('#clearSearchBtn')).toBeHidden();
});

test('mini app prefers formatted transcript and escapes its content', async ({page}) => {
  await prepare(page);
  await page.route('**/api/lecture/latest', async route => {
    const response = await route.fetch();
    const lecture = await response.json();
    lecture.transcription = 'Сырой текст без абзацев';
    lecture.formatted_transcription = 'Первый <абзац>.\n\nВторой абзац.';
    await route.fulfill({response, json: lecture});
  });
  await page.goto('/app');
  await page.locator('[data-tab="transcript"]').click();
  await expect(page.locator('#transcriptBox .transcript-block')).toHaveCount(2);
  await expect(page.locator('#transcriptBox')).toContainText('Первый <абзац>.');
  await expect(page.locator('#transcriptBox')).not.toContainText('Сырой текст');
  await expect(page.locator('#transcriptBox').locator('абзац')).toHaveCount(0);
  await page.locator('#transcriptSearch').fill('<абзац>');
  await expect(page.locator('#transcriptBox .word-highlight')).toHaveText('<абзац>');
});

test('unformatted long transcript is split into readable paragraphs without losing words', async ({page}) => {
  await prepare(page);
  const raw = Array.from({length: 160}, (_, index) => `слово${index}`).join(' ');
  await page.route('**/api/lecture/latest', async route => {
    const response = await route.fetch();
    const lecture = await response.json();
    lecture.transcription = raw;
    lecture.formatted_transcription = null;
    await route.fulfill({response, json: lecture});
  });
  await page.goto('/app');
  await page.locator('[data-tab="transcript"]').click();
  const paragraphs = page.locator('#transcriptBox .transcript-block');
  expect(await paragraphs.count()).toBeGreaterThan(1);
  const chunks = await paragraphs.allTextContents();
  expect(chunks.every(chunk => chunk.length <= 360)).toBe(true);
  expect(chunks.join(' ')).toBe(raw);
  await page.screenshot({path: 'test-results/mini-app-transcript-paragraphs.png', fullPage: true});
  await page.locator('#transcriptSearch').fill('слово80');
  await expect(page.locator('#transcriptBox .word-highlight')).toHaveText('слово80');
});

test('history navigation retains Telegram auth fallback and app version', async ({page}) => {
  await prepare(page, false);
  await page.goto(`/app?v=13#tgWebAppData=${encodeURIComponent(signed())}`);
  await expect(page.locator('#lectureTitle')).toHaveText('Лекция 100');
  await page.locator('#openHistoryBtn').click();
  await page.locator('.history-card[data-id="lecture0"]').click();
  await expect(page.locator('#lectureTitle')).toHaveText('Лекция 0');
  await expect(page).toHaveURL(/\?v=13&id=lecture0#tgWebAppData=/);
  await page.reload();
  await expect(page.locator('#lectureTitle')).toHaveText('Лекция 0');
});

test('long Russian title fits mobile card and logo letter is optically centered', async ({page}) => {
  await prepare(page);
  await page.route('**/api/lecture/latest', async route => {
    const response = await route.fetch();
    const lecture = await response.json();
    lecture.title_ru = 'Разбор конфликта Александра Фреймтеймера с творческим объединением «Хозяева»';
    await route.fulfill({response, json: lecture});
  });
  await page.goto('/app?v=13');
  await expect(page.locator('#lectureTitle')).toContainText('Разбор конфликта');
  const titleSize = await page.locator('#lectureTitle').evaluate(el => getComputedStyle(el).fontSize);
  expect(titleSize).toBe('26px');
  const letterTransform = await page.locator('.brand-letter').evaluate(el => getComputedStyle(el).transform);
  expect(letterTransform).toBe('matrix(1, 0, 0, 1, -1, 3)');
  const { titleRight, cardRight } = await page.evaluate(() => ({
    titleRight: document.querySelector('#lectureTitle').getBoundingClientRect().right,
    cardRight: document.querySelector('.lecture-hero').getBoundingClientRect().right
  }));
  expect(titleRight).toBeLessThan(cardRight);
  await page.screenshot({path: 'test-results/mini-app-long-title.png', fullPage: true});
});

test('history drawer contains backdrop gestures and restores the page after closing', async ({page}) => {
  await prepare(page);
  await page.goto('/app?v=13');
  await page.evaluate(() => window.scrollTo(0, 300));
  const initialScroll = await page.evaluate(() => window.scrollY);

  await page.locator('#openHistoryBtn').click();
  await expect(page.locator('#historyOverlay')).toHaveClass(/show/);
  await expect(page.locator('#historyOverlay')).toHaveAttribute('aria-hidden', 'false');
  await expect(page.locator('body')).toHaveCSS('position', 'fixed');
  await expect(page.locator('.app-container')).toHaveAttribute('inert', '');
  await expect(page.locator('.history-card')).toHaveCount(101);
  await expect(page.locator('.history-card-active-tag')).toHaveCount(1);
  await expect(page.locator('.history-card-active-tag')).toHaveText('Открыт');

  const firstCardTitle = page.locator('.history-card-title').first();
  await expect(firstCardTitle).toHaveCSS('user-select', 'none');
  const titleBox = await firstCardTitle.boundingBox();
  await page.mouse.move(titleBox.x + 8, titleBox.y + 8);
  await page.mouse.down();
  await page.mouse.move(titleBox.x + 8, titleBox.y - 45, {steps: 4});
  await page.mouse.up();
  expect(await page.evaluate(() => window.getSelection().toString())).toBe('');
  await expect(page).not.toHaveURL(/id=/);

  await page.mouse.move(10, 18);
  await page.mouse.down();
  await page.mouse.move(10, 60, {steps: 4});
  await page.mouse.up();
  await expect(page.locator('#historyOverlay')).toHaveClass(/show/);
  await expect(page.locator('body')).toHaveCSS('position', 'fixed');

  await page.mouse.click(10, 18);
  await expect(page.locator('#historyOverlay')).not.toHaveClass(/show/);
  await expect(page.locator('#historyOverlay')).toHaveAttribute('aria-hidden', 'true');
  await expect(page.locator('body')).not.toHaveCSS('position', 'fixed');
  await expect(page.locator('.app-container')).not.toHaveAttribute('inert', '');
  expect(await page.evaluate(() => window.scrollY)).toBe(initialScroll);
});
