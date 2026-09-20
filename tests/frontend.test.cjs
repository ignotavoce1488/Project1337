const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('HTML and markdown escape user content', () => {
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync('web/js/ui.js', 'utf8'), context);
  assert.equal(context.escapeHtml('<img src=x onerror="alert(1)">'), '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;');
  const result = context.parseMarkdown('## Heading\n<script>alert(1)</script>');
  assert.ok(result.includes('md-h2'));
  assert.ok(!result.includes('<script>'));
});

test('Credentials stay in headers and cannot be sent to another origin', async () => {
  const requests = [];
  const context = vm.createContext({ URL, AbortController, setTimeout, clearTimeout,
    window: {location: {origin: 'https://app.test', hash: ''}, Telegram: {WebApp: {initData: 'signed', ready() {}, expand() {}}}},
    fetch: async (...args) => { requests.push(args); return {ok:true}; }
  });
  vm.runInContext(fs.readFileSync('web/js/api.js', 'utf8'), context);
  await context.apiFetch('/api/lectures');
  assert.equal(requests[0][1].headers['X-Telegram-Init-Data'], 'signed');
  assert.ok(!requests[0][0].href.includes('signed'));
  await assert.rejects(context.apiFetch('https://evil.test/'));
  assert.equal(requests.length, 1);
});
