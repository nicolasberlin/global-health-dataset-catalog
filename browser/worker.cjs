// Disposable browser context. IPC output excludes cookies and secret headers.
const { chromium } = require('playwright');
const { workerFailure } = require('./failures.cjs');
let browser, context, page;
let sourceOrigin;
let phase;
const limit = 1000000;
async function sampledFetch(url, method, maxBytes, timeout) {
  return page.evaluate(async ({ url, method, maxBytes, timeout }) => {
    const control = new AbortController();
    const timer = setTimeout(() => control.abort(), timeout);
    try {
      const response = await fetch(url, {
        method, credentials: 'same-origin', signal: control.signal,
        headers: method === 'GET' ? { Range: `bytes=0-${Math.max(maxBytes, 1) - 1}` } : {},
      });
      let bytes = new Uint8Array(0), truncated = false;
      if (method !== 'HEAD' && response.body) {
        const reader = response.body.getReader();
        const chunks = []; let total = 0;
        try {
          while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            const accepted = value.slice(0, Math.max(0, maxBytes + 1 - total));
            chunks.push(accepted); total += accepted.length;
            if (total > maxBytes) { truncated = true; break; }
          }
        } finally { await reader.cancel(); }
        bytes = new Uint8Array(Math.min(total, maxBytes));
        let offset = 0;
        for (const chunk of chunks) {
          const part = chunk.slice(0, bytes.length - offset);
          bytes.set(part, offset); offset += part.length;
        }
      }
      let binary = '';
      for (const byte of bytes) binary += String.fromCharCode(byte);
      const headers = {};
      for (const key of ['content-type', 'content-length', 'content-range', 'content-disposition', 'etag', 'last-modified', 'www-authenticate']) {
        const value = response.headers.get(key); if (value) headers[key] = value;
      }
      return { final_url: response.url, status_code: response.status, headers,
        body_base64: btoa(binary), sample_truncated: truncated };
    } finally { clearTimeout(timer); }
  }, { url, method, maxBytes, timeout });
}
async function handle(message) {
  const { action, payload } = message;
  if (action === 'render') {
    phase = 'launch';
    const url = new URL(payload.url);
    sourceOrigin = url.origin;
    browser = await chromium.launch({ headless: true, chromiumSandbox: process.platform !== 'darwin',
      proxy: { server: process.env.BROWSER_PROXY_URL },
      args: ['--proxy-bypass-list=<-loopback>', '--disable-quic'] });
    context = await browser.newContext({ acceptDownloads: false, serviceWorkers: 'block' });
    await context.route('**/*', route => {
      const scheme = new URL(route.request().url()).protocol;
      if (scheme !== 'https:' || ['image', 'media', 'font'].includes(route.request().resourceType())) return route.abort();
      return route.continue();
    });
    await context.routeWebSocket('**/*', socket => socket.close());
    page = await context.newPage();
    page.on('dialog', dialog => dialog.dismiss());
    const deadline = Date.now() + payload.timeout_ms;
    let finalStatus = null;
    page.on('response', response => { if (response.request().isNavigationRequest() && response.frame() === page.mainFrame()) finalStatus = response.status(); });
    phase = 'navigation';
    const response = await page.goto(payload.url, { waitUntil: 'domcontentloaded', timeout: Math.max(1, deadline - Date.now()) });
    phase = 'render';
    try {
      await page.waitForFunction(() => {
        const text = document.body?.innerText || '';
        if (/not a robot|checking your browser|javascript is disabled/i.test(text)) return false;
        return text.length > 100 || document.querySelector('a[href*="file.xhtml"],script[type="application/ld+json"]');
      }, null, { timeout: Math.max(1, deadline - Date.now()) });
    } catch {} // Preserve the barrier HTML for the shared access detector.
    let metadata = null, metadata_http_status = null, metadata_code = '';
    if (payload.metadata_url && new URL(payload.metadata_url).origin === sourceOrigin && Date.now() < deadline) {
      try {
        const result = await sampledFetch(payload.metadata_url, 'GET', limit, Math.max(1, deadline - Date.now()));
        metadata_http_status = result.status_code;
        if (result.status_code !== 200) metadata_code = 'repository_http_error';
        else if (result.sample_truncated) metadata_code = 'repository_response_too_large';
        else {
          try { metadata = JSON.parse(Buffer.from(result.body_base64, 'base64').toString('utf8')); }
          catch { metadata_code = 'repository_invalid_json'; }
        }
      } catch { metadata_code = 'repository_network_error'; }
    }
    const html = await page.content();
    if (Buffer.byteLength(html) > limit) throw Error('response_too_large');
    return { html, final_url: page.url(), http_status: finalStatus ?? response?.status() ?? null, metadata, metadata_http_status, metadata_code };
  }
  if (action === 'probe') {
    if (!page || new URL(payload.url).origin !== sourceOrigin) throw Error('cross_origin_probe_refused');
    if (!['HEAD', 'GET'].includes(payload.method) || payload.max_bytes < 0 || payload.max_bytes > 65536) throw Error('invalid_probe');
    return sampledFetch(payload.url, payload.method, payload.max_bytes, payload.timeout_ms);
  }
  throw Error('invalid_action');
}
process.on('message', async message => {
  phase = 'request';
  try { process.send({ request_id: message.request_id, result: await handle(message) }); }
  catch (error) { process.send({ request_id: message.request_id, error: workerFailure(error, phase), detail: String(error.message).slice(0,1800) }); }
});
process.on('disconnect', async () => { if (browser) await browser.close(); process.exit(0); });
