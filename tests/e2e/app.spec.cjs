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

test('authorization, translated lecture, history pagination, keyboard navigation', async ({page}) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await prepare(page);
  await page.goto('/app');
  await expect(page.locator('#lectureTitle')).toHaveText('Лекция 100');
  await expect(page.locator('#summaryBox')).toContainText('Русский текст');
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

test('history navigation retains Telegram auth fallback and app version', async ({page}) => {
  await prepare(page, false);
  await page.goto(`/app?v=5#tgWebAppData=${encodeURIComponent(signed())}`);
  await expect(page.locator('#lectureTitle')).toHaveText('Лекция 100');
  await page.locator('#openHistoryBtn').click();
  await page.locator('.history-card[data-id="lecture0"]').click();
  await expect(page.locator('#lectureTitle')).toHaveText('Лекция 0');
  await expect(page).toHaveURL(/\?v=5&id=lecture0#tgWebAppData=/);
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
  await page.goto('/app?v=5');
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
