// Trusted local/isolated service. One disposable child context, no DB/model credentials.
const http = require('node:http');
const crypto = require('node:crypto');
const { spawn } = require('node:child_process');
const path = require('node:path');
const os = require('node:os');
const { serviceFailure } = require('./failures.cjs');
const token = process.env.COLLECTION_BROWSER_TOKEN;
const proxy = process.env.BROWSER_PROXY_URL;
if (!token || token.length < 32 || !proxy) throw Error('Browser token/proxy configuration required');
const allowedHosts = (process.env.COLLECTION_BROWSER_HOSTS || 'dataverse.harvard.edu').split(',').map(x => x.trim());
let session;
function killSession(id) {
  if (!session || (id && session.id !== id)) return;
  clearTimeout(session.timer);
  try { process.kill(-session.child.pid, 'SIGKILL'); } catch {}
  session = null;
}
function launchChild() {
  const worker = path.join(__dirname, 'worker.cjs');
  const env = { DEBUG: process.env.BROWSER_DEBUG === '1' ? 'pw:browser' : '', PATH: process.env.PATH, BROWSER_PROXY_URL: proxy,
    PLAYWRIGHT_BROWSERS_PATH: process.env.PLAYWRIGHT_BROWSERS_PATH || path.join(os.homedir(), 'Library/Caches/ms-playwright'),
    NODE_PATH: process.env.NODE_PATH || path.join(__dirname, 'node_modules') };
  let command = process.execPath, args = [worker];
  if (process.platform === 'darwin') {
    const port = Number(new URL(proxy).port);
    if (new URL(proxy).hostname !== '127.0.0.1' || !port) throw Error('Local proxy required');
    const esc = p => p.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
    const profile = `(version 1)(allow default)(deny network-outbound)(allow network-outbound (remote tcp "localhost:${port}"))(deny file-read* file-write* (subpath "${esc(os.homedir())}"))(allow file-read-metadata)(allow file-read* (subpath "${esc(__dirname)}") (subpath "${esc(env.NODE_PATH)}") (subpath "${esc(env.PLAYWRIGHT_BROWSERS_PATH)}") (literal "${esc(process.execPath)}"))`;

    command = '/usr/bin/sandbox-exec'; args = ['-p', profile, process.execPath, worker];
  } else if (process.env.BROWSER_NETWORK_ISOLATED !== '1') {
    throw Error('Production browser requires the supplied isolated container');
  }
  const child = spawn(command, args, { env, detached: true, stdio: ['ignore', 'ignore', 'pipe', 'ipc'] });
  child.stderr.on('data', data => { if (process.env.BROWSER_DEBUG === '1') process.stderr.write(data.toString().slice(0,1800)); });
  return child;
}
function invoke(child, action, payload, timeout) {
  return new Promise((resolve, reject) => {
    const id = crypto.randomUUID();
    const timer = setTimeout(() => { cleanup(); if (session?.child === child) killSession(session.id); reject(Error('timeout')); }, timeout);
    const cleanup = () => { clearTimeout(timer); child.off('message', receive); child.off('exit', exited); };
    const receive = message => {
      if (message.request_id !== id) return;
      cleanup(); if (message.error) { if (process.env.BROWSER_DEBUG === '1') console.error(message.detail); reject(Error(message.error)); } else resolve(message.result);
    };
    const exited = () => { cleanup(); reject(Error('worker_exited')); };
    child.on('message', receive); child.once('exit', exited);
    child.send({ request_id: id, action, payload }, error => { if (error) { cleanup(); reject(error); } });
  });
}
const server = http.createServer(async (request, response) => {
  const send = (status, body) => { response.writeHead(status, { 'Content-Type': 'application/json' }); response.end(JSON.stringify(body)); };
  if (request.url === '/health' && request.method === 'GET') return send(200, { status: 'ok' });
  const auth = Buffer.from(request.headers.authorization || '');
  const expected = Buffer.from(`Bearer ${token}`);
  if (auth.length !== expected.length || !crypto.timingSafeEqual(auth, expected)) return send(401, { error: 'unauthorized' });
  if (request.method !== 'POST') return send(405, { error: 'method_not_allowed' });
  let size = 0, chunks = [], ownerSessionId;
  try {
    for await (const chunk of request) {
      size += chunk.length; if (size > 8192) return send(413, { error: 'request_too_large' }); chunks.push(chunk);
    }
    const payload = JSON.parse(Buffer.concat(chunks));
    if (request.url === '/render') {
      if (session) return send(429, { error: 'browser_busy' });
      const url = new URL(payload.url);
      if (url.protocol !== 'https:' || !allowedHosts.includes(url.hostname) || url.username || url.password || (url.port && url.port !== '443')) return send(400, { error: 'host_not_allowed' });
      const budget = Math.min(Number(payload.budget_ms), 300000);
      if (!Number.isFinite(budget) || budget < 1) return send(400, { error: 'invalid_budget' });
      const id = crypto.randomUUID(), child = launchChild();
      session = { id, child, busy: true, deadline: Date.now() + budget, timer: setTimeout(() => killSession(id), budget) };
      ownerSessionId = id;
      const result = await invoke(child, 'render', { ...payload, timeout_ms: Math.min(30000, budget) }, Math.min(30000, budget));
      if (!session || session.id !== id) throw Error('expired');
      session.busy = false;
      return send(200, { session_id: id, ...result });
    }
    if (!session || payload.session_id !== session.id) return send(404, { error: 'session_expired' });
    ownerSessionId = session.id;
    if (request.url === '/close') { killSession(ownerSessionId); return send(200, { closed: true }); }
    if (request.url !== '/probe' || session.busy) return send(409, { error: 'invalid_operation' });
    session.busy = true;
    try {
      const result = await invoke(session.child, 'probe', { ...payload, timeout_ms: Math.min(10000, session.deadline - Date.now()) }, Math.max(1, Math.min(10000, session.deadline - Date.now())));
      return send(200, result);
    } finally { if (session) session.busy = false; }
  } catch (error) { if (ownerSessionId) killSession(ownerSessionId); send(503, { error: serviceFailure(error) }); }
});
server.headersTimeout = 10000;
server.requestTimeout = 35000;
server.listen(Number(process.env.BROWSER_PORT || 8002), process.env.BROWSER_BIND || '127.0.0.1');
process.on('SIGTERM', () => { killSession(); server.close(); });
