// Telegram WebApp SDK Integration
const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
  if (typeof tg.disableVerticalSwipes === 'function') {
    tg.disableVerticalSwipes();
  }
  if (typeof tg.isVerticalSwipesEnabled !== 'undefined') {
    tg.isVerticalSwipesEnabled = false;
  }
}

function triggerHaptic(type = 'impact', style = 'light') {
  if (tg && tg.HapticFeedback) {
    if (type === 'impact') tg.HapticFeedback.impactOccurred(style);
    else if (type === 'notification') tg.HapticFeedback.notificationOccurred(style);
  }
}

// Cryptographic Telegram Auth Helpers
function getAuthHeaders() {
  const headers = {};
  let initData = window.Telegram?.WebApp?.initData || '';
  if (!initData && window.location.hash) {
    const match = window.location.hash.match(/tgWebAppData=([^&]+)/);
    if (match) {
      try {
        initData = decodeURIComponent(match[1]);
      } catch(e) {}
    }
  }
  if (initData) {
    headers['X-Telegram-Init-Data'] = initData;
  }
  return headers;
}

// Requests stay on this origin; credentials never enter URLs or persistent storage.
async function apiFetch(url, options = {}) {
  const target = new URL(url, window.location.origin);
  if (target.origin !== window.location.origin) throw new Error('Недопустимый адрес запроса');
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    return await fetch(target, {
      ...options, cache: 'no-store', redirect: 'error', signal: options.signal || controller.signal,
      headers: { ...(options.headers || {}), ...getAuthHeaders() }
    });
  } finally { clearTimeout(timeout); }
}

async function fetchHistory() {
  const result = [];
  for (let offset = 0; ; offset += 100) {
    const response = await apiFetch(`/api/lectures?limit=100&offset=${offset}`);
    if (!response.ok) throw new Error(response.status === 401
      ? 'Откройте приложение заново через Telegram' : 'Не удалось загрузить историю');
    const page = await response.json();
    result.push(...page);
    if (page.length < 100) return result;
  }
}
