// Telegram webviews can deny persistent storage; theme still works in memory.
const themeMemory = new Map();
const themeStorage = {
  getItem(key) { try { return localStorage.getItem(key); } catch (_) { return themeMemory.get(key) || null; } },
  setItem(key, value) { themeMemory.set(key, value); try { localStorage.setItem(key, value); } catch (_) {} },
  removeItem(key) { themeMemory.delete(key); try { localStorage.removeItem(key); } catch (_) {} }
};
// === Adaptive Theme Management (Dynamic Telegram Sync + Manual Override) ===
function isColorLight(hexColor) {
  if (!hexColor || typeof hexColor !== 'string') return false;
  let hex = hexColor.replace('#', '').trim();
  if (hex.length === 3) hex = hex.split('').map(c => c + c).join('');
  if (hex.length !== 6) return false;
  const r = parseInt(hex.substring(0, 2), 16) || 0;
  const g = parseInt(hex.substring(2, 4), 16) || 0;
  const b = parseInt(hex.substring(4, 6), 16) || 0;
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) > 130;
}

function detectTelegramTheme() {
  if (window.Telegram?.WebApp?.colorScheme === 'light' || window.Telegram?.WebApp?.colorScheme === 'dark') {
    return window.Telegram.WebApp.colorScheme;
  }
  if (window.Telegram?.WebApp?.themeParams?.bg_color) {
    return isColorLight(window.Telegram.WebApp.themeParams.bg_color) ? 'light' : 'dark';
  }
  try {
    const hash = window.location.hash || '';
    const match = hash.match(/tgWebAppThemeParams=([^&]+)/) || hash.match(/tgThemeParams=([^&]+)/);
    if (match && match[1]) {
      const p = JSON.parse(decodeURIComponent(match[1]));
      if (p.bg_color) {
        return isColorLight(p.bg_color) ? 'light' : 'dark';
      }
    }
  } catch (e) { }
  try {
    const tgBg = getComputedStyle(document.documentElement).getPropertyValue('--tg-theme-bg-color').trim();
    if (tgBg && tgBg.startsWith('#')) {
      return isColorLight(tgBg) ? 'light' : 'dark';
    }
  } catch (e) { }
  if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
    return 'light';
  }
  return 'dark';
}

function getInitialTheme() {
  if (themeStorage.getItem('slovech_theme')) {
    themeStorage.removeItem('slovech_theme');
  }
  const manual = themeStorage.getItem('slovech_theme_override');
  if (manual === 'light' || manual === 'dark') {
    return manual;
  }
  return detectTelegramTheme();
}

function applyTheme(theme, notify = false, isUserAction = false) {
  const finalTheme = (theme === 'light') ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', finalTheme);
  document.body.setAttribute('data-theme', finalTheme);

  const sunIcon = document.querySelector('.sun-icon');
  const moonIcon = document.querySelector('.moon-icon');

  if (finalTheme === 'light') {
    if (sunIcon) sunIcon.style.display = 'none';
    if (moonIcon) moonIcon.style.display = 'block';
    if (window.Telegram?.WebApp?.setHeaderColor) window.Telegram.WebApp.setHeaderColor('#f4f5ee');
    if (window.Telegram?.WebApp?.setBackgroundColor) window.Telegram.WebApp.setBackgroundColor('#f4f5ee');
  } else {
    if (sunIcon) sunIcon.style.display = 'block';
    if (moonIcon) moonIcon.style.display = 'none';
    if (window.Telegram?.WebApp?.setHeaderColor) window.Telegram.WebApp.setHeaderColor('#10110f');
    if (window.Telegram?.WebApp?.setBackgroundColor) window.Telegram.WebApp.setBackgroundColor('#10110f');
  }

  if (notify && typeof triggerHaptic !== 'undefined') triggerHaptic('impact', 'medium');
}

function setupThemeToggle() {
  const themeToggleBtn = document.getElementById('themeToggleBtn');
  if (!themeToggleBtn) return;

  themeToggleBtn.addEventListener('click', () => {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    const hasOverride = !!themeStorage.getItem('slovech_theme_override');

    if (!hasOverride) {
      const next = current === 'dark' ? 'light' : 'dark';
      themeStorage.setItem('slovech_theme_override', next);
      applyTheme(next, true, true);
      if (typeof showToast !== 'undefined') showToast(next === 'light' ? '☀️ Светлая тема' : '🌙 Тёмная тема');
    } else {
      const override = themeStorage.getItem('slovech_theme_override');
      const autoTheme = detectTelegramTheme();
      if (override === autoTheme) {
        const next = override === 'dark' ? 'light' : 'dark';
        themeStorage.setItem('slovech_theme_override', next);
        applyTheme(next, true, true);
        if (typeof showToast !== 'undefined') showToast(next === 'light' ? '☀️ Светлая тема' : '🌙 Тёмная тема');
      } else {
        themeStorage.removeItem('slovech_theme_override');
        applyTheme(autoTheme, true, true);
        if (typeof showToast !== 'undefined') showToast('✨ Тема: как в Telegram');
      }
    }
  });

  if (window.Telegram?.WebApp) {
    window.Telegram.WebApp.onEvent('themeChanged', () => {
      const hasOverride = themeStorage.getItem('slovech_theme_override');
      if (!hasOverride) {
        applyTheme(detectTelegramTheme(), false, false);
      }
    });
  }

  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => {
      const hasOverride = themeStorage.getItem('slovech_theme_override');
      if (!hasOverride) {
        applyTheme(detectTelegramTheme(), false, false);
      }
    });
  }
}

// === Accent Color Management ===
function initAccentTheme() {
  const savedAccent = themeStorage.getItem('slovech_accent') || 'lavender';
  applyAccent(savedAccent, false);
}

function applyAccent(colorName, notify = true) {
  document.body.setAttribute('data-accent', colorName);
  themeStorage.setItem('slovech_accent', colorName);

  const colorDots = document.querySelectorAll('.color-dot');
  if (colorDots) {
    colorDots.forEach(d => {
      d.classList.toggle('active', d.getAttribute('data-color') === colorName);
    });
  }
  if (notify && typeof triggerHaptic !== 'undefined') triggerHaptic('impact', 'medium');
}

function setupAccentPalette() {
  const paletteBtn = document.getElementById('paletteBtn');
  const paletteDropdown = document.getElementById('paletteDropdown');
  const colorDots = document.querySelectorAll('.color-dot');

  if (!paletteBtn || !paletteDropdown) return;

  paletteBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (typeof triggerHaptic !== 'undefined') triggerHaptic('impact', 'light');
    paletteDropdown.classList.toggle('show');
  });

  colorDots.forEach(dot => {
    dot.addEventListener('click', (e) => {
      e.stopPropagation();
      const color = dot.getAttribute('data-color');
      applyAccent(color);
      paletteDropdown.classList.remove('show');
    });
  });

  document.addEventListener('click', (e) => {
    if (!paletteDropdown.contains(e.target) && e.target !== paletteBtn) {
      paletteDropdown.classList.remove('show');
    }
  });
}
