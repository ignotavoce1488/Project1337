const { defineConfig } = require('@playwright/test');
const { existsSync } = require('node:fs');
const python = process.env.E2E_PYTHON || (existsSync('.venv312/bin/python') ? '.venv312/bin/python' : '.venv/bin/python');
module.exports = defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  use: { baseURL: 'http://127.0.0.1:8765', viewport: { width: 390, height: 844 }, trace: 'retain-on-failure' },
  webServer: {
    command: `"${python}" -m tests.serve_e2e`,
    url: 'http://127.0.0.1:8765/ready',
    reuseExistingServer: false,
    timeout: 30000
  }
});
