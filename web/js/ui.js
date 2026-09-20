// === Toast Feedback ===
function showToast(text) {
  let toast = document.getElementById('appToast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'appToast';
    toast.className = 'app-toast';
    document.body.appendChild(toast);
  }
  toast.textContent = text;
  toast.classList.add('show');
  clearTimeout(toast._timeout);
  toast._timeout = setTimeout(() => {
    toast.classList.remove('show');
  }, 1800);
}

// === Time, Text & Security Helpers ===
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function formatTime(sec) {
  if (isNaN(sec) || sec < 0) return '00:00';
  const totalSecs = Math.floor(sec);
  const h = Math.floor(totalSecs / 3600);
  const m = Math.floor((totalSecs % 3600) / 60);
  const s = totalSecs % 60;
  if (h > 0) {
    return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  }
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}


function parseMarkdown(md) {
  if (!md) return '';
  let html = escapeHtml(md);

  // 1. Headers (use span with classes instead of block heading tags)
  html = html.replace(/^### (.*$)/gim, '<br><span class="md-h3">$1</span><br>');
  html = html.replace(/^## (.*$)/gim, '<br><span class="md-h2">$1</span><br>');
  html = html.replace(/^# (.*$)/gim, '<br><span class="md-h1">$1</span><br>');

  // 2. Lists (use inline bullet instead of <li>)
  html = html.replace(/^\s*[-*]\s+(.*$)/gim, '<br>&bull; $1');

  // 3. Bold
  html = html.replace(/\*\*([^*]+)\*\*/gim, '<strong>$1</strong>');
  html = html.replace(/__([^_]+)__/gim, '<strong>$1</strong>');

  // 4. Italic
  html = html.replace(/\*([^*]+)\*/gim, '<em>$1</em>');
  html = html.replace(/_([^_]+)_/gim, '<em>$1</em>');

  // 5. Paragraphs (split by double newline, join with double <br>)
  let paragraphs = html.split(/\n\n+/);
  html = paragraphs.map(p => {
    p = p.trim();
    if (!p) return '';
    p = p.replace(/\n/g, '<br>'); // single newlines become single <br>
    return p;
  }).join('<br><br>');

  // Cleanup extra breaks at start/end or consecutive excessive breaks
  html = html.replace(/^(<br>)+/, '').replace(/(<br>)+$/, '');
  html = html.replace(/(<br>){3,}/g, '<br><br>');

  return html;
}
