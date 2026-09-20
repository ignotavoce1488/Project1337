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
  await page.locator('#historySearchInput').fill('Lecture 0');
  await expect(page.locator('.history-card')).toHaveCount(1);
  await page.locator('.history-card').focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('#lectureTitle')).toHaveText('Лекция 0');
  await expect(page).toHaveURL(/id=lecture0/);
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
});
