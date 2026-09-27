let lectureRequestNumber = 0;
// === Application State and Core UI Logic ===

// State
let currentLecture = null;
let currentTab = 'summary';

function formatLectureDate(value) {
  if (!value) return 'Сегодня';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(uiLanguage, {
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
const takeawaysMoreBtn = document.getElementById('takeawaysMoreBtn');
const visibleTakeawaysCount = 3;
let takeawaysExpanded = false;
const summaryBox = document.getElementById('summaryBox');
const transcriptBox = document.getElementById('transcriptBox');
const copyBtn = document.getElementById('copyBtn');
const transcriptSearch = document.getElementById('transcriptSearch');
const clearSearchBtn = document.getElementById('clearSearchBtn');
const currentTranscriptText = () => {
  if (!currentLecture) return '';
  if (translatedContent(currentLecture) &&
      currentLecture.transcription_translation_language === uiLanguage &&
      currentLecture.transcription_translated) return currentLecture.transcription_translated;
  return currentLecture.formatted_transcription || currentLecture.transcription || '';
};

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

function transcriptParagraphs(text) {
  const maxLength = 360;
  const minLength = 170;
  const paragraphs = [];
  for (const block of text.trim().split(/\n\s*\n/)) {
    const words = block.trim().split(/\s+/).filter(Boolean);
    let start = 0;
    while (start < words.length) {
      let end = start;
      let length = 0;
      let sentenceEnd = -1;
      while (end < words.length && (length + words[end].length + 1 <= maxLength || end === start)) {
        length += words[end].length + 1;
        if (length >= minLength && /[.!?…]["»”’)]*$/.test(words[end])) sentenceEnd = end + 1;
        end += 1;
      }
      if (end < words.length && sentenceEnd > start) end = sentenceEnd;
      paragraphs.push(words.slice(start, end).join(' '));
      start = end;
    }
  }
  return paragraphs;
}

function renderTranscript(rawText, searchQuery = '') {
  if (!rawText || !rawText.trim()) {
    transcriptBox.innerHTML = '<p style="text-align:center; padding: 24px; color: var(--text-dim);">Расшифровка текста отсутствует.</p>';
    return;
  }

  let cleaned = rawText
    .replace(/^Вот (точная|дословная|полная)[^\n]*:\s*/i, '')
    .trim();

  const paragraphs = transcriptParagraphs(cleaned);

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
  paragraphs.forEach((p) => {
    // Clean source text before escaping; highlighting must never edit HTML or entities.
    const displayText = p.replace(/(?:^|\s)[\[\(]?(\d{1,2}:\d{2}(?::\d{2})?)[\]\)]?\s*[:\-—]?\s*/g, ' ').trim();
    if (displayText) html += `<p class="transcript-block">${highlight(displayText)}</p>`;
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
const translateBtn = document.getElementById('translateBtn');
const translateProgress = document.getElementById('translateProgress');
const translateStatus = document.getElementById('translateStatus');
const translateElapsed = document.getElementById('translateElapsed');
const translateTrack = document.getElementById('translateTrack');
const transcriptTranslationProgress = document.getElementById('transcriptTranslationProgress');
const transcriptTranslationStatus = document.getElementById('transcriptTranslationStatus');
const transcriptTranslationCount = document.getElementById('transcriptTranslationCount');
const transcriptTranslationTrack = document.getElementById('transcriptTranslationTrack');
const transcriptTranslationFill = document.getElementById('transcriptTranslationFill');
const retryTranscriptTranslation = document.getElementById('retryTranscriptTranslation');
let currentAppLang = 'ru';
let translationTask = null;
let translationTimer = null;
let translationStatusRequest = 0;
let transcriptTranslationTask = null;

function transcriptNeedsTranslation(data) {
  return Boolean(data?.transcription && translatedContent(data) &&
    (data.transcription_translation_language !== uiLanguage || !data.transcription_translated));
}

function renderTranscriptTranslationProgress() {
  if (!transcriptTranslationProgress) return;
  const task = transcriptTranslationTask;
  const visible = currentTab === 'transcript' && transcriptNeedsTranslation(currentLecture) &&
    task?.lectureId === currentLecture?.id;
  transcriptTranslationProgress.hidden = !visible;
  if (!visible) return;
  transcriptTranslationProgress.dataset.state = task.state;
  const message = task.state === 'failed' ? transcriptTranslateCopy(2)
    : task.state === 'pending' ? transcriptTranslateCopy(0) : transcriptTranslateCopy(1);
  transcriptTranslationStatus.textContent = message;
  retryTranscriptTranslation.hidden = task.state !== 'failed';
  retryTranscriptTranslation.textContent = transcriptTranslateCopy(3);
  const completed = Math.min(task.completed || 0, task.total || 0);
  const percent = task.total ? Math.round(completed / task.total * 100) : 0;
  transcriptTranslationCount.textContent = task.total && task.state !== 'failed'
    ? `${completed}/${task.total} · ${percent}%` : '';
  transcriptTranslationTrack.setAttribute('aria-valuetext', message);
  if (completed && task.total) {
    transcriptTranslationTrack.setAttribute('aria-valuenow', String(percent));
    if (transcriptTranslationFill.dataset.determinate !== 'true') {
      transcriptTranslationFill.dataset.determinate = 'true';
      transcriptTranslationFill.style.width = '0%';
      transcriptTranslationFill.getBoundingClientRect();
      requestAnimationFrame(() => {
        if (transcriptTranslationTask === task) transcriptTranslationFill.style.width = `${percent}%`;
      });
    } else {
      transcriptTranslationFill.style.width = `${percent}%`;
    }
  } else {
    transcriptTranslationTrack.removeAttribute('aria-valuenow');
    transcriptTranslationFill.dataset.determinate = 'false';
    transcriptTranslationFill.style.width = '';
  }
}

async function pollTranscriptTranslation(task) {
  if (task.polling) return;
  task.polling = true;
  try {
    for (let attempt = 0; attempt < 3600; attempt++) {
      await new Promise(resolve => setTimeout(resolve, 2000));
      if (transcriptTranslationTask !== task) return;
      const response = await apiFetch(`/api/lecture/${encodeURIComponent(task.lectureId)}/transcript-translation`);
      if (!response.ok) throw new Error('STATUS_FAILED');
      if (transcriptTranslationTask !== task) return;
      const status = await response.json();
      if (status.state === 'ready' || status.state === 'done') {
        transcriptTranslationTask = null;
        if (currentLecture?.id === task.lectureId) await loadLecture(task.lectureId, true);
        return;
      }
      if (status.state === 'failed' || status.state === 'missing') throw new Error('TRANSLATION_FAILED');
      Object.assign(task, status);
      renderTranscriptTranslationProgress();
    }
    throw new Error('TRANSLATION_TIMEOUT');
  } catch (_) {
    if (transcriptTranslationTask === task) {
      task.state = 'failed';
      renderTranscriptTranslationProgress();
    }
  } finally {
    task.polling = false;
  }
}

async function ensureTranscriptTranslation() {
  if (!transcriptNeedsTranslation(currentLecture) || currentTab !== 'transcript') return;
  const lectureId = currentLecture.id;
  if (transcriptTranslationTask?.lectureId === lectureId &&
      ['pending', 'running'].includes(transcriptTranslationTask.state)) return;
  const task = {lectureId, state: 'pending', completed: 0, total: 0, polling: false};
  transcriptTranslationTask = task;
  renderTranscriptTranslationProgress();
  try {
    const response = await apiFetch(`/api/lecture/${encodeURIComponent(lectureId)}/transcript-translation`, {method: 'POST'});
    if (!response.ok) throw new Error('QUEUE_FAILED');
    if (transcriptTranslationTask !== task) return;
    const {state} = await response.json();
    if (state === 'ready') {
      transcriptTranslationTask = null;
      await loadLecture(lectureId, true);
    } else if (state === 'pending' || state === 'running') {
      task.state = state;
      renderTranscriptTranslationProgress();
      pollTranscriptTranslation(task);
    } else {
      throw new Error('TRANSLATION_FAILED');
    }
  } catch (_) {
    if (transcriptTranslationTask === task) {
      task.state = 'failed';
      renderTranscriptTranslationProgress();
    }
  }
}

if (retryTranscriptTranslation) {
  retryTranscriptTranslation.addEventListener('click', ensureTranscriptTranslation);
}

function stopTranslationTask() {
  translationTask = null;
  if (translationTimer) clearInterval(translationTimer);
  translationTimer = null;
}

function renderTranslationProgress(data) {
  if (!translateProgress) return;
  const task = translationTask?.lectureId === data.id ? translationTask : null;
  const visible = task && data.language !== uiLanguage && translatedLanguage(data) !== uiLanguage;
  translateProgress.hidden = !visible;
  if (!visible) return;
  translateProgress.dataset.state = task.state;
  const message = task.state === 'failed' ? translateCopy(2)
    : task.state === 'pending' ? translateCopy(3) : translateCopy(1);
  translateStatus.textContent = message;
  translateTrack.setAttribute('aria-valuetext', message);
  const seconds = Math.floor((Date.now() - task.startedAt) / 1000);
  translateElapsed.textContent = task.state === 'failed' ? ''
    : `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}

function setTranslationTask(lectureId, state) {
  if (translationTask?.lectureId !== lectureId || translationTask.state === 'failed') {
    stopTranslationTask();
    translationTask = {lectureId, state, startedAt: Date.now(), polling: false};
  } else {
    translationTask.state = state;
  }
  if (state !== 'failed' && !translationTimer) {
    translationTimer = setInterval(() => {
      if (currentLecture) renderTranslationProgress(currentLecture);
    }, 1000);
  }
  if (state === 'failed' && translationTimer) {
    clearInterval(translationTimer);
    translationTimer = null;
  }
  if (currentLecture) updateLanguageSwap(currentLecture);
  return translationTask;
}

async function pollTranslation(task) {
  if (task.polling) return;
  task.polling = true;
  try {
    for (let attempt = 0; attempt < 300; attempt++) {
      await new Promise(resolve => setTimeout(resolve, 2000));
      if (translationTask !== task) return;
      const response = await apiFetch(`/api/lecture/${encodeURIComponent(task.lectureId)}/translation`);
      if (!response.ok) throw new Error('STATUS_FAILED');
      if (translationTask !== task) return;
      const state = (await response.json()).state;
      if (state === 'ready' || state === 'done') {
        stopTranslationTask();
        if (currentLecture?.id === task.lectureId) await loadLecture(task.lectureId);
        return;
      }
      if (state === 'failed' || state === 'missing') throw new Error('TRANSLATION_FAILED');
      setTranslationTask(task.lectureId, state);
    }
    throw new Error('TRANSLATION_TIMEOUT');
  } catch (_) {
    if (translationTask === task) setTranslationTask(task.lectureId, 'failed');
  } finally {
    task.polling = false;
  }
}

async function restoreTranslationStatus(data) {
  if (data.language === uiLanguage || translatedLanguage(data) === uiLanguage) return;
  if (translationTask?.lectureId === data.id) return;
  const request = ++translationStatusRequest;
  try {
    const response = await apiFetch(`/api/lecture/${encodeURIComponent(data.id)}/translation`);
    if (!response.ok) return;
    const {state} = await response.json();
    if (request !== translationStatusRequest || currentLecture?.id !== data.id || translationTask) return;
    if (state === 'pending' || state === 'running') {
      pollTranslation(setTranslationTask(data.id, state));
    } else if (state === 'failed') {
      setTranslationTask(data.id, 'failed');
    }
  } catch (_) { /* The translate button remains available when status cannot be loaded. */ }
}

function translatedLanguage(data) {
  if (data.translation_language && data.summary_translated) return data.translation_language;
  if (data.language === 'en' && data.summary_ru) return 'ru';
  return null;
}

function translatedContent(data) {
  return Boolean(translatedLanguage(data) && currentAppLang === translatedLanguage(data));
}

function updateLanguageSwap(data) {
  const wrapper = document.getElementById('langToggleWrapper');
  const translation = translatedLanguage(data);
  if (!wrapper) return;
  const canSwap = Boolean(translation && translation === uiLanguage && translation !== data.language);
  const canTranslate = data.language !== uiLanguage && !canSwap;
  wrapper.style.display = canSwap || canTranslate ? 'flex' : 'none';
  if (langToggleBtn) langToggleBtn.style.display = canSwap ? '' : 'none';
  if (translateBtn) {
    translateBtn.style.display = canTranslate ? '' : 'none';
    translateBtn.textContent = translateCopy(0);
    translateBtn.disabled = Boolean(translationTask?.lectureId === data.id &&
      ['pending', 'running'].includes(translationTask.state));
  }
  if (langToggleText && canSwap) {
    const showingTranslation = translatedContent(data);
    langToggleText.textContent = languageSwapLabel(showingTranslation, showingTranslation ? data.language : translation);
  }
  renderTranslationProgress(data);
}

if (translateBtn) {
  translateBtn.addEventListener('click', async () => {
    if (!currentLecture || translateBtn.disabled) return;
    const lectureId = currentLecture.id;
    const task = setTranslationTask(lectureId, 'pending');
    try {
      const queued = await apiFetch(`/api/lecture/${encodeURIComponent(lectureId)}/translation`, {method: 'POST'});
      if (!queued.ok) throw new Error('QUEUE_FAILED');
      if (translationTask !== task) return;
      const {state} = await queued.json();
      if (state === 'ready' || state === 'done') {
        stopTranslationTask();
        if (currentLecture?.id === lectureId) await loadLecture(lectureId);
      } else if (state === 'pending' || state === 'running') {
        setTranslationTask(lectureId, state);
        pollTranslation(task);
      } else {
        throw new Error('TRANSLATION_FAILED');
      }
    } catch (_) {
      if (translationTask === task) setTranslationTask(lectureId, 'failed');
    }
  });
}

function renderLectureContent(data, lang) {
  const translated = translatedContent(data);

  // Title
  lectureTitleEl.textContent = translated
    ? (data.title_translated || data.title_ru || data.title)
    : (data.title || 'Summary');

  // Takeaways
  const keyPoints = translated
    ? (data.key_points_translated || data.key_points_ru || data.key_points)
    : data.key_points;
  if (keyPoints && keyPoints.length > 0) {
    takeawaysSection.style.display = 'block';
    const visiblePoints = takeawaysExpanded ? keyPoints : keyPoints.slice(0, visibleTakeawaysCount);
    takeawaysList.innerHTML = visiblePoints.map((pt, index) => {
      const cleanPt = pt.replace(/^[\s*\-]+/g, '').replace(/[*_`#]/g, '');
      return `
      <div class="takeaway-card">
        <span class="takeaway-marker" aria-hidden="true">${String(index + 1).padStart(2, '0')}</span>
        <span>${escapeHtml(cleanPt)}</span>
      </div>
    `;
    }).join('');
    const hiddenCount = keyPoints.length - visibleTakeawaysCount;
    takeawaysMoreBtn.style.display = hiddenCount > 0 ? 'block' : 'none';
    takeawaysMoreBtn.setAttribute('aria-expanded', String(takeawaysExpanded && hiddenCount > 0));
    takeawaysMoreBtn.textContent = takeawaysExpanded ? 'Свернуть' : `Показать ещё ${hiddenCount}`;
  } else {
    takeawaysSection.style.display = 'none';
    takeawaysMoreBtn.style.display = 'none';
  }

  // Summary
  const summaryText = translated ? (data.summary_translated || data.summary_ru || data.summary) : data.summary;
  summaryBox.innerHTML = parseMarkdown(summaryText);
  applyIOSSelectionFix(summaryBox);
}

takeawaysMoreBtn.addEventListener('click', () => {
  if (!currentLecture) return;
  takeawaysExpanded = !takeawaysExpanded;
  renderLectureContent(currentLecture, currentAppLang);
});

// === Load Lecture Data ===
async function loadLecture(id = null, preserveLanguage = false) {
  const urlParams = new URLSearchParams(window.location.search);
  const targetId = id || urlParams.get('id');
  const requestNumber = ++lectureRequestNumber;

  let endpoint = targetId ? `/api/lecture/${encodeURIComponent(targetId)}` : `/api/lecture/latest`;

  try {
    const res = await apiFetch(endpoint);
    if (!res.ok) {
      if (res.status === 401) throw new Error('AUTH_REQUIRED');
      if (res.status === 403) throw new Error('Сначала примите условия в чате с ботом через /start.');
      throw new Error('Конспект не найден');
    }
    const data = await res.json();
    if (requestNumber !== lectureRequestNumber) return;

    if (data.empty) {
      translationStatusRequest += 1;
      stopTranslationTask();
      transcriptTranslationTask = null;
      currentLecture = null;
      emptyStateEl.style.display = 'block';
      const emptyIcon = emptyStateEl.querySelector('.empty-icon');
      if (emptyIcon) emptyIcon.textContent = '🎙';
      emptyStateEl.querySelector('h2').textContent = ui(2);
      emptyStateEl.querySelector('p').textContent = ui(3);
      lectureViewEl.style.display = 'none';
      if (historyBadge) historyBadge.style.display = 'none';
      return;
    }

    const keepOriginal = preserveLanguage && currentLecture?.id === data.id &&
      currentAppLang === currentLecture.language;
    translationStatusRequest += 1;
    if (translationTask && (translationTask.lectureId !== data.id ||
      data.language === uiLanguage || translatedLanguage(data) === uiLanguage)) stopTranslationTask();
    if (transcriptTranslationTask && (transcriptTranslationTask.lectureId !== data.id ||
      data.transcription_translation_language === uiLanguage && data.transcription_translated)) {
      transcriptTranslationTask = null;
    }
    currentLecture = data;
    takeawaysExpanded = false;
    emptyStateEl.style.display = 'none';
    lectureViewEl.style.display = 'block';

    // Populate metadata
    dateBadgeEl.textContent = formatLectureDate(data.created_at);
    statusPillEl.textContent = targetId ? ui(12) : ui(4);

    // Language Toggle Setup
    currentAppLang = keepOriginal ? data.language
      : translatedLanguage(data) === uiLanguage ? uiLanguage : (data.language || 'auto');
    updateLanguageSwap(data);
    restoreTranslationStatus(data);

    renderLectureContent(data, currentAppLang);
    if (transcriptSearch) transcriptSearch.value = '';
    if (clearSearchBtn) clearSearchBtn.style.display = 'none';
    renderTranscript(currentTranscriptText());
    renderTranscriptTranslationProgress();
    if (currentTab === 'transcript') ensureTranscriptTranslation();

    // Setup Audio Player
    if (currentLecture && currentLecture.transcription) {
      // no audio logic
    }

    // Update history badge count in background
    loadHistoryCount();

  } catch (err) {
    if (requestNumber !== lectureRequestNumber) return;
    translationStatusRequest += 1;
    stopTranslationTask();
    transcriptTranslationTask = null;
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
let historySearchRequest = 0;
let historySearchTimer = null;

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
    const query = e.target.value.trim();
    const request = ++historySearchRequest;
    if (historySearchTimer) clearTimeout(historySearchTimer);
    if (!query) {
      renderHistoryList(allHistoryItems);
      return;
    }
    historySearchTimer = setTimeout(async () => {
      try {
        const response = await apiFetch(`/api/lectures/search?q=${encodeURIComponent(query)}`);
        if (!response.ok) throw new Error('Search unavailable');
        const found = await response.json();
        if (request === historySearchRequest) renderHistoryList(found);
      } catch (_) {
        if (request === historySearchRequest) historyList.textContent = searchError();
      }
    }, 250);
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
  historySearchRequest += 1;
  if (historySearchTimer) clearTimeout(historySearchTimer);
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
    renderTranscriptTranslationProgress();
    if (target === 'transcript') ensureTranscriptTranslation();
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
  const translated = translatedContent(currentLecture);
  const title = translated ? (currentLecture.title_translated || currentLecture.title_ru || currentLecture.title) : currentLecture.title;
  const summary = translated ? (currentLecture.summary_translated || currentLecture.summary_ru || currentLecture.summary) : currentLecture.summary;
  return `${title || ''}\n\n${summary || ''}`;
}

if (copyBtn) {
  copyBtn.addEventListener('click', () => {
    copyText(currentTab === 'summary' ? currentSummaryText() : currentTranscriptText());
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
    const text = currentTranscriptText();
    copyText(text, 'Расшифровка скопирована');
  });
}

// === Transcript Search ===
if (transcriptSearch && clearSearchBtn) {
  transcriptSearch.addEventListener('input', (e) => {
    const query = e.target.value.trim();
    clearSearchBtn.style.display = query ? 'block' : 'none';
    if (!currentTranscriptText()) return;
    renderTranscript(currentTranscriptText(), query);
  });

  clearSearchBtn.addEventListener('click', () => {
    transcriptSearch.value = '';
    clearSearchBtn.style.display = 'none';
    if (currentTranscriptText()) {
      renderTranscript(currentTranscriptText());
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

  loadInterfaceLanguage().finally(() => loadLecture());
});

if (langToggleBtn) {
  langToggleBtn.addEventListener('click', () => {
    if (typeof triggerHaptic !== 'undefined') triggerHaptic('impact', 'light');
    if (!currentLecture) return;
    currentAppLang = translatedContent(currentLecture)
      ? currentLecture.language : translatedLanguage(currentLecture);
    updateLanguageSwap(currentLecture);
    renderLectureContent(currentLecture, currentAppLang);
    renderTranscript(currentTranscriptText(), transcriptSearch?.value.trim() || '');
    renderTranscriptTranslationProgress();
    if (currentTab === 'transcript') ensureTranscriptTranslation();
  });
}

window.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeHistory(); });
