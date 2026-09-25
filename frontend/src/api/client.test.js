import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { requestJson, requestSession } from './client.js';

const reply = (status, payload, headers = {}) => new Response(
    status === 204 ? null : JSON.stringify(payload), { status, headers },
);
const visitor = () => ({ mode: 'public', ready: true, isCurrent: () => true,
    signal: new AbortController().signal, cooldowns: new Map(), expire: vi.fn() });

beforeEach(() => {
    vi.stubEnv('VITE_API_AUTH_MODE', 'public');
    vi.stubEnv('VITE_API_BASE_URL', '/ai-commons/api');
    vi.stubGlobal('fetch', vi.fn());
});
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.useRealTimers(); });

it('accepts a 204 only for bootstrap and never sends a bearer in public mode', async () => {
    fetch.mockResolvedValueOnce(reply(204));
    await expect(requestSession()).resolves.toBeUndefined();
    expect(fetch.mock.calls[0][0]).toBe('/ai-commons/api/session');
    expect(fetch.mock.calls[0][1].credentials).toBe('same-origin');
    fetch.mockResolvedValueOnce(reply(200, { items: [] }));
    await requestJson('/search', { session: visitor(), headers: { authorization: 'Bearer stale' } });
    expect(new Headers(fetch.mock.calls[1][1].headers).has('authorization')).toBe(false);
    fetch.mockResolvedValueOnce(reply(204));
    await expect(requestJson('/search', { session: visitor() })).rejects.toThrow('incomplete');
});

it('rejects an unready session or a foreign API URL before sending a request', async () => {
    await expect(requestJson('/search', { session: { ...visitor(), ready: false } })).rejects.toThrow('not ready');
    vi.stubEnv('VITE_API_BASE_URL', 'http://foreign.example/api');
    await expect(requestSession()).rejects.toThrow('same origin');
    expect(fetch).not.toHaveBeenCalled();
});

it.each([401, 403, 503])('does not replay a POST after HTTP %s', async status => {
    const session = visitor();
    fetch.mockResolvedValue(reply(status, { detail: 'Rejected' }));
    await expect(requestJson('/search', { session, method: 'POST' })).rejects.toMatchObject({ status });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(session.expire).toHaveBeenCalledTimes(status === 401 ? 1 : 0);
});

it('respects Retry-After without retrying a costly request automatically', async () => {
    vi.useFakeTimers();
    const session = visitor();
    fetch.mockResolvedValueOnce(reply(429, { detail: 'Quota exceeded' }, { 'Retry-After': '10' }));
    const search = () => requestJson('/search', { session, method: 'POST' });
    await expect(search()).rejects.toMatchObject({ status: 429, retryAt: Date.now() + 10000 });
    await expect(search()).rejects.toMatchObject({ status: 429 });
    await vi.advanceTimersByTimeAsync(10000);
    expect(fetch).toHaveBeenCalledTimes(1);
    fetch.mockResolvedValueOnce(reply(200, { items: [] }));
    await expect(search()).resolves.toEqual({ items: [] });
});


it.each([{ 'Retry-After': '1' }, {}])('handles plain-text proxy throttling (%j)', async headers => {
    vi.useFakeTimers();
    const session = visitor();
    fetch.mockResolvedValueOnce(new Response('Too Many Requests', { status: 429, headers }));
    const poll = () => requestJson('/collector/repository-candidates/test', { session });
    await expect(poll()).rejects.toMatchObject({
        status: 429, retryAt: Date.now() + (headers['Retry-After'] ? 1000 : 5000),
    });
    await expect(poll()).rejects.toMatchObject({ status: 429 });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(session.expire).not.toHaveBeenCalled();
});
