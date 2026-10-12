const { test } = require('node:test');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const net = require('node:net');
const path = require('node:path');

test('service authenticates, refuses private initial hosts and expires a session', async () => {
  const reservation = net.createServer();
  reservation.listen(0, '127.0.0.1'); await once(reservation, 'listening');
  const port = reservation.address().port;
  await new Promise(resolve => reservation.close(resolve));
  const token = 'test-browser-secret-token-with-32-characters';
  const service = spawn(process.execPath, [path.resolve(__dirname, '../service.cjs')], {
    env: { PATH: process.env.PATH, COLLECTION_BROWSER_TOKEN: token,
      BROWSER_PROXY_URL: 'http://127.0.0.1:8899', BROWSER_PORT: String(port) },
    stdio: 'ignore',
  });
  const base = `http://127.0.0.1:${port}`;
  const post = (payload, authorization = `Bearer ${token}`) => fetch(base + '/render', {
    method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: authorization },
    body: JSON.stringify(payload),
  });
  try {
    const deadline = Date.now() + 3000;
    while (true) {
      try { if ((await fetch(base + '/health')).ok) break; } catch {}
      assert.ok(Date.now() < deadline, 'service failed to start');
      await new Promise(resolve => setTimeout(resolve, 20));
    }
    assert.equal((await post({ url: 'https://dataverse.harvard.edu/', budget_ms: 1 }, '')).status, 401);
    for (const url of ['https://127.0.0.1/', 'https://169.254.169.254/',
      'https://user:password@dataverse.harvard.edu/', 'http://dataverse.harvard.edu/',
      'https://dataverse.harvard.edu:8001/']) {
      assert.equal((await post({ url, budget_ms: 1000 })).status, 400);
    }
    assert.equal((await post({ url: 'https://dataverse.harvard.edu/', budget_ms: 0 })).status, 400);
    assert.equal((await post({ url: 'https://dataverse.harvard.edu/', budget_ms: 1 })).status, 503);
    assert.equal((await fetch(base + '/health')).status, 200);
  } finally { service.kill('SIGTERM'); await once(service, 'exit'); }
});
