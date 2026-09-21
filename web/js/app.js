let lectureRequestNumber = 0;
// === Application State and Core UI Logic ===

// State
let currentLecture = null;
let currentTab = 'summary';

function formatLectureDate(value) {
  if (!value) return 'Сегодня';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric', month: 'long', year: date.getFullYear() === new Date().getFullYear() ? undefined : 'numeric'
  }).format(date);
}

// Elements
const emptyStateEl = document.getElementById('emptyState');
const lectureViewEl = document.getElementById('lectureView');
const lectureTitleEl = document.getElementById('lectureTitle');
const dateBadgeEl = document.getElementById('dateBadge');
const statusPillEl = document.getElementById('statusPill');
const takeawaysSection = document.getElementById('takeawaysSection');
const takeawaysList = document.getElementById('takeawaysList');
const summaryBox = document.getElementById('summaryBox');
const transcriptBox = document.getElementById('transcriptBox');
const copyBtn = document.getElementById('copyBtn');
const transcriptSearch = document.getElementById('transcriptSearch');
const clearSearchBtn = document.getElementById('clearSearchBtn');

// History Drawer Elements
const openHistoryBtn = document.getElementById('openHistoryBtn');
const historyBadge = document.getElementById('historyBadge');
const historyOverlay = document.getElementById('historyOverlay');
const closeHistoryBtn = document.getElementById('historyCloseBtn');
const historyList = document.getElementById('historyList');
const appContainer = document.querySelector('.app-container');
let historyScrollY = 0;
let backdropPointer = null;
let cardPointer = null;
let suppressCardClick = false;

function renderTranscript(rawText, searchQuery = '') {
  if (!rawText || !rawText.trim()) {
    transcriptBox.innerHTML = '<p style="text-align:center; padding: 24px; color: var(--text-dim);">Расшифровка текста отсутствует.</p>';
    return;
  }

  let cleaned = rawText
    .replace(/^Вот (точная|дословная|полная)[^\n]*:\s*/i, '')
    .trim();

  const paragraphs = cleaned
    .split(/\n\s*\n/)
    .map(p => p.trim())
    .filter(p => p.length > 0);

  const highlight = (text) => {
    if (!searchQuery) return escapeHtml(text);
    const pattern = new RegExp(searchQuery.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
    let cursor = 0;
    let result = '';
    for (const match of text.matchAll(pattern)) {
      result += escapeHtml(text.slice(cursor, match.index));
      result += `<span class="word-highlight">${escapeHtml(match[0])}</span>`;
      cursor = match.index + match[0].length;
    }
    return result + escapeHtml(text.slice(cursor));
  };

  let html = '';
  paragraphs.forEach((p, idx) => {
    // Clean source text before escaping; highlighting must never edit HTML or entities.
    const displayText = p.replace(/(?:^|\s)[\[\(]?(\d{1,2}:\d{2}(?::\d{2})?)[\]\)]?\s*[:\-—]?\s*/g, ' ').trim();
    html += highlight(displayText);
    if (idx < paragraphs.length - 1) {
      html += '<br><br>';
    }
  });

  transcriptBox.innerHTML = html;
  applyIOSSelectionFix(transcriptBox);
}

// Native iOS WKWebView Selection Fix
function applyIOSSelectionFix(container) {
  // Find all text blocks that should be selectable
  const textBlocks = container.querySelectorAll('.transcript-block, p, li, h1, h2, h3, h4');
  textBlocks.forEach(el => {
    // This forces iOS WKWebView to enable the native selection magnifying glass and context menu
    el.setAttribute('contenteditable', 'true');
    // This prevents the virtual keyboard from popping up on mobile
    el.setAttribute('inputmode', 'none');
    el.setAttribute('spellcheck', 'false');

    // Prevent accidental edits if they somehow have a hardware keyboard
    el.addEventListener('beforeinput', (e) => e.preventDefault());
    el.addEventListener('cut', (e) => {
      e.preventDefault();
      // Emulate copy on cut
      const selection = window.getSelection();
      if (selection) navigator.clipboard.writeText(selection.toString());
    });
    el.addEventListener('paste', (e) => e.preventDefault());
    el.addEventListener('keydown', (e) => {
      if (!e.metaKey && !e.ctrlKey) e.preventDefault();
    });
  });
}

const langToggleBtn = document.getElementById('langToggleBtn');
const langToggleText = document.getElementById('langToggleText');
let currentAppLang = 'ru';

function renderLectureContent(data, lang) {
  const isEn = (lang === 'en');

  // Title
  lectureTitleEl.textContent = isEn ? (data.title || 'Summary') : (data.title_ru || data.title || 'Конспект аудиозаписи');

  // Takeaways
  const keyPoints = isEn ? data.key_points : (data.key_points_ru || data.key_points);
  if (keyPoints && keyPoints.length > 0) {
    takeawaysSection.style.display = 'block';
    takeawaysList.innerHTML = keyPoints.map(pt => {
      const cleanPt = pt.replace(/^[\s*\-]+/g, '').replace(/[*_`#]/g, '');
      return `
      <div class="takeaway-card">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
        <span>${escapeHtml(cleanPt)}</span>
      </div>
    `;
    }).join('');
  } else {
    takeawaysSection.style.display = 'none';
  }

  // Summary
  const summaryText = isEn ? data.summary : (data.summary_ru || data.summary);
  summaryBox.innerHTML = parseMarkdown(summaryText);
  applyIOSSelectionFix(summaryBox);
}

// === Load Lecture Data ===
async function loadLecture(id = null) {
  const urlParams = new URLSearchParams(window.location.search);
  const targetId = id || urlParams.get('id');
  const requestNumber = ++lectureRequestNumber;

  let endpoint = targetId ? `/api/lecture/${encodeURIComponent(targetId)}` : `/api/lecture/latest`;

  try {
    const res = await apiFetch(endpoint);
    if (!res.ok) {
      if (res.status === 401) throw new Error('AUTH_REQUIRED');
      if (res.status === 403) throw new Error('Этот конспект принадлежит другому пользователю.');
      throw new Error('Конспект не найден');
    }
    const data = await res.json();
    if (requestNumber !== lectureRequestNumber) return;

    if (data.empty) {
      currentLecture = null;
      emptyStateEl.style.display = 'block';
      const emptyIcon = emptyStateEl.querySelector('.empty-icon');
      if (emptyIcon) emptyIcon.textContent = '🎙';
      emptyStateEl.querySelector('h2').textContent = 'Здесь появятся ваши конспекты';
      emptyStateEl.querySelector('p').innerHTML = 'Отправьте любое аудио или голосовое сообщение боту <b>@slovech_bot</b>, и здесь появится конспект.';
      lectureViewEl.style.display = 'none';
      if (historyBadge) historyBadge.style.display = 'none';
      return;
    }

    currentLecture = data;
    emptyStateEl.style.display = 'none';
    lectureViewEl.style.display = 'block';

    // Populate metadata
    dateBadgeEl.textContent = formatLectureDate(data.created_at);
    statusPillEl.textContent = targetId ? 'Архивная запись' : 'Последний конспект';

    // Language Toggle Setup
    const langToggleWrapper = document.getElementById('langToggleWrapper');
    if (data.language === 'en' && data.summary_ru) {
      currentAppLang = 'ru'; // Default to Russian if available
      if (langToggleWrapper) langToggleWrapper.style.display = 'flex';
      if (langToggleText) langToggleText.textContent = 'Показать оригинал (EN)';
    } else {
      currentAppLang = data.language || 'ru';
      if (langToggleWrapper) langToggleWrapper.style.display = 'none';
    }

    renderLectureContent(data, currentAppLang);
    if (transcriptSearch) transcriptSearch.value = '';
    if (clearSearchBtn) clearSearchBtn.style.display = 'none';
    renderTranscript(data.transcription || '');

    // Setup Audio Player
    if (currentLecture && currentLecture.transcription) {
      // no audio logic
    }

    // Update history badge count in background
    loadHistoryCount();

  } catch (err) {
    if (requestNumber !== lectureRequestNumber) return;
    currentLecture = null;
    console.error(err);
    emptyStateEl.style.display = 'block';
    const emptyIcon = emptyStateEl.querySelector('.empty-icon');
    const titleEl = emptyStateEl.querySelector('h2');
    const descEl = emptyStateEl.querySelector('p');

    if (err.message === 'AUTH_REQUIRED') {
      if (emptyIcon) emptyIcon.textContent = '🔒';
      titleEl.textContent = 'Вход только через Telegram';
      descEl.innerHTML = 'Для доступа к конспектам нужна авторизация через Telegram.<br><br>Пожалуйста, откройте сервис через бота <b>@slovech_bot</b>.';
    } else {
      if (emptyIcon) emptyIcon.textContent = '📖';
      titleEl.textContent = 'Запись недоступна';
      descEl.textContent = err.message;
    }
    lectureViewEl.style.display = 'none';
  }
}

// === History Drawer ===
async function loadHistoryCount() {
  if (!historyBadge) return;
  try {
    const response = await apiFetch('/api/lectures/count');
    if (!response.ok) return;
    const { count } = await response.json();
    historyBadge.textContent = count;
    historyBadge.style.display = count > 0 ? 'inline-block' : 'none';
  } catch (_) { /* The lecture remains usable when the optional count is unavailable. */ }
}

let allHistoryItems = [];
const historySearchInput = document.getElementById('historySearchInput');

function renderHistoryList(items) {
  if (!items || items.length === 0) {
    const isSearch = historySearchInput && historySearchInput.value.trim() !== '';
    if (isSearch) {
      historyList.innerHTML = `<p style="text-align:center; padding: 30px 20px; color: var(--text-muted);">Ничего не найдено</p>`;
    } else {
      historyList.innerHTML = `<p style="text-align:center; padding: 30px 20px; color: var(--text-muted);">У вас пока нет сохраненных конспектов.<br>Отправьте аудио или голосовое в бота @slovech_bot</p>`;
    }
    return;
  }

  historyList.innerHTML = items.map(item => {
    const isActive = currentLecture && currentLecture.id === item.id;
    // Strip markdown bold/italic/headings for cleaner preview
    const cleanPreview = item.preview ? item.preview.replace(/[*_`#]/g, '') : '';
    const cleanTitle = item.title ? item.title.replace(/[*_`#]/g, '') : 'Без названия';
    return `
      <div role="button" tabindex="0" class="history-card ${isActive ? 'active' : ''}" data-id="${escapeHtml(item.id)}">
        <div class="history-card-top">
          <span class="history-card-date">${escapeHtml(formatLectureDate(item.created_at))}</span>
          ${isActive ? '<span class="history-card-active-tag">Открыт</span>' : ''}
        </div>
        <div class="history-card-title">${escapeHtml(cleanTitle)}</div>
        <div class="history-card-preview">${escapeHtml(cleanPreview)}</div>
      </div>
    `;
  }).join('');

  // Attach click handlers
  historyList.querySelectorAll('.history-card').forEach(card => {
    card.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); card.click(); }
    });
    card.addEventListener('click', () => {
      const id = card.getAttribute('data-id');
      if (typeof triggerHaptic !== 'undefined') triggerHaptic('impact', 'light');
      closeHistory();
      const nextUrl = new URL(window.location.href);
      nextUrl.searchParams.set('id', id);
      history.replaceState(null, '', nextUrl);
      loadLecture(id);
    });
  });
}

if (historySearchInput) {
  historySearchInput.addEventListener('input', (e) => {
    const query = e.target.value.trim().toLowerCase();
    if (!query) {
      renderHistoryList(allHistoryItems);
      return;
    }
    const filtered = allHistoryItems.filter(item =>
      (item.title && item.title.toLowerCase().includes(query)) ||
      (item.preview && item.preview.toLowerCase().includes(query))
    );
    renderHistoryList(filtered);
  });
}

if (historyList) {
  historyList.addEventListener('pointerdown', (event) => {
    if (!event.target.closest('.history-card')) return;
    cardPointer = { id: event.pointerId, x: event.clientX, y: event.clientY };
    suppressCardClick = false;
  });
  historyList.addEventListener('pointermove', (event) => {
    if (!cardPointer || cardPointer.id !== event.pointerId) return;
    if (Math.hypot(event.clientX - cardPointer.x, event.clientY - cardPointer.y) >= 8) {
      suppressCardClick = true;
    }
  });
  historyList.addEventListener('pointercancel', () => {
    cardPointer = null;
    suppressCardClick = false;
  });
  historyList.addEventListener('click', (event) => {
    if (!suppressCardClick || !event.target.closest('.history-card')) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    cardPointer = null;
    suppressCardClick = false;
  }, true);
}

async function openHistory() {
  if (historyOverlay.classList.contains('show')) return;
  if (typeof triggerHaptic !== 'undefined') triggerHaptic('impact', 'medium');
  historyScrollY = window.scrollY;
  document.body.style.position = 'fixed';
  document.body.style.top = `-${historyScrollY}px`;
  document.body.style.width = '100%';
  document.documentElement.classList.add('history-open');
  document.body.classList.add('history-open');
  if (appContainer) appContainer.inert = true;
  historyOverlay.setAttribute('aria-hidden', 'false');
  historyOverlay.classList.add('show');
  if (closeHistoryBtn) closeHistoryBtn.focus();

  // Reset search
  if (historySearchInput) historySearchInput.value = '';

  historyList.innerHTML = `
    <div class="loading-state">
      <div class="soft-spinner"></div>
      <p>Загрузка вашей истории...</p>
    </div>
  `;

  try {
    allHistoryItems = await fetchHistory();
    renderHistoryList(allHistoryItems);
  } catch (e) {
    historyList.innerHTML = `<p style="text-align:center; padding: 24px; color: #f87171;">${escapeHtml(e.message)}</p>`;
  }
}

function closeHistory() {
  if (!historyOverlay.classList.contains('show')) return;
  historyOverlay.classList.remove('show');
  historyOverlay.setAttribute('aria-hidden', 'true');
  if (appContainer) appContainer.inert = false;
  document.documentElement.classList.remove('history-open');
  document.body.classList.remove('history-open');
  document.body.style.position = '';
  document.body.style.top = '';
  document.body.style.width = '';
  window.scrollTo(0, historyScrollY);
  backdropPointer = null;
  if (openHistoryBtn) openHistoryBtn.focus();
}

if (openHistoryBtn) openHistoryBtn.addEventListener('click', openHistory);
if (closeHistoryBtn) closeHistoryBtn.addEventListener('click', closeHistory);
if (historyOverlay) {
  historyOverlay.addEventListener('pointerdown', (event) => {
    if (event.target !== historyOverlay) return;
    backdropPointer = { id: event.pointerId, x: event.clientX, y: event.clientY };
    historyOverlay.setPointerCapture?.(event.pointerId);
    event.preventDefault();
  });
  historyOverlay.addEventListener('pointermove', (event) => {
    if (backdropPointer?.id === event.pointerId) event.preventDefault();
  });
  historyOverlay.addEventListener('pointerup', (event) => {
    if (!backdropPointer || backdropPointer.id !== event.pointerId) return;
    const distance = Math.hypot(
      event.clientX - backdropPointer.x,
      event.clientY - backdropPointer.y
    );
    backdropPointer = null;
    event.preventDefault();
    if (event.target === historyOverlay && distance < 10) closeHistory();
  });
  historyOverlay.addEventListener('pointercancel', () => { backdropPointer = null; });
  historyOverlay.addEventListener('touchmove', (event) => {
    if (event.target === historyOverlay) event.preventDefault();
  }, { passive: false });
}

// === Tabs Navigation ===
document.querySelectorAll('.tab-item').forEach(btn => {
  btn.addEventListener('click', () => {
    const target = btn.getAttribute('data-tab');
    if (target === currentTab) return;

    if (typeof triggerHaptic !== 'undefined') triggerHaptic('impact', 'light');

    document.querySelectorAll('.tab-item').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(p => p.classList.remove('active'));

    btn.classList.add('active');
    document.getElementById(`pane-${target}`).classList.add('active');
    currentTab = target;
  });
});

// === Copy Action ===
async function copyText(text, label) {
  if (!text) return;
  try {
    if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.copyTextToClipboard) {
      window.Telegram.WebApp.copyTextToClipboard(text);
    } else {
      await navigator.clipboard.writeText(text);
    }
    if (typeof triggerHaptic !== 'undefined') triggerHaptic('notification', 'success');
    showToast('📋 ' + (label || 'Скопировано'));
  } catch (err) {
    showToast('⚠️ Не удалось скопировать');
    console.error('Copy failed:', err);
  }
}

function currentSummaryText() {
  if (!currentLecture) return '';
  const translated = currentAppLang === 'ru';
  const title = translated ? (currentLecture.title_ru || currentLecture.title) : currentLecture.title;
  const summary = translated ? (currentLecture.summary_ru || currentLecture.summary) : currentLecture.summary;
  return `${title || ''}\n\n${summary || ''}`;
}

if (copyBtn) {
  copyBtn.addEventListener('click', () => {
    copyText(currentTab === 'summary' ? currentSummaryText() : (currentLecture?.transcription || ''));
  });
}

const copySummaryBtn = document.getElementById('copySummaryBtn');
if (copySummaryBtn) {
  copySummaryBtn.addEventListener('click', () => {
    const text = currentSummaryText();
    copyText(text, 'Конспект скопирован');
  });
}

const copyTranscriptBtn = document.getElementById('copyTranscriptBtn');
if (copyTranscriptBtn) {
  copyTranscriptBtn.addEventListener('click', () => {
    const text = currentLecture?.transcription || '';
    copyText(text, 'Расшифровка скопирована');
  });
}

// === Transcript Search ===
if (transcriptSearch && clearSearchBtn) {
  transcriptSearch.addEventListener('input', (e) => {
    const query = e.target.value.trim();
    clearSearchBtn.style.display = query ? 'block' : 'none';
    if (!currentLecture || !currentLecture.transcription) return;
    renderTranscript(currentLecture.transcription, query);
  });

  clearSearchBtn.addEventListener('click', () => {
    transcriptSearch.value = '';
    clearSearchBtn.style.display = 'none';
    if (currentLecture && currentLecture.transcription) {
      renderTranscript(currentLecture.transcription);
    }
  });
}

// === App Initialization ===
window.addEventListener('DOMContentLoaded', () => {
  if (window.Telegram && window.Telegram.WebApp) {
    window.Telegram.WebApp.expand();
    // Disable vertical swipe (prevents Telegram from stealing touch events that break text selection)
    if (typeof window.Telegram.WebApp.disableVerticalSwipes === 'function') {
      window.Telegram.WebApp.disableVerticalSwipes();
    }
  }

  if (typeof setupThemeToggle === 'function') setupThemeToggle();
  if (typeof setupAccentPalette === 'function') setupAccentPalette();

  if (typeof applyTheme === 'function' && typeof getInitialTheme === 'function') {
    applyTheme(getInitialTheme(), false);
  }
  if (typeof initAccentTheme === 'function') initAccentTheme();

  loadLecture();
});

if (langToggleBtn) {
  langToggleBtn.addEventListener('click', () => {
    if (typeof triggerHaptic !== 'undefined') triggerHaptic('impact', 'light');
    currentAppLang = currentAppLang === 'ru' ? 'en' : 'ru';
    if (langToggleText) langToggleText.textContent = currentAppLang === 'ru' ? 'Показать оригинал (EN)' : 'Читать перевод (RU)';
    if (currentLecture) renderLectureContent(currentLecture, currentAppLang);
  });
}

window.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeHistory(); });
