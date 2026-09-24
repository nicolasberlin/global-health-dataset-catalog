import { defineConfig } from '@playwright/test';

export default defineConfig({
    testDir: './tests/browser',
    testMatch: '**/*.browser.js',
    forbidOnly: !!process.env.CI,
    use: {
        baseURL: 'https://localhost:9443',
        // The isolated harness generates a temporary self-signed certificate.
        ignoreHTTPSErrors: true,
    },
    projects: ['chromium', 'firefox', 'webkit'].map(browserName => ({
        name: browserName,
        use: { browserName },
    })),
    webServer: {
        command: 'PYTHONPATH=../backend:.. ../.venv/bin/python ../tests/browser/session_server.py',
        url: 'https://localhost:9443',
        ignoreHTTPSErrors: true,
        reuseExistingServer: false,
    },
});
