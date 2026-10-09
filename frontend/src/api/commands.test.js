import { afterEach, expect, it, vi } from 'vitest';
import { sendCommand } from './commands.js';
const owner = () => ({ mode: 'local', local: true, ready: true, isCurrent: () => true });
const response = (status = 202, data = {}) => ({ ok: status < 400, status, json: async () => data });
const key = index => fetch.mock.calls[index][1].headers['idempotency-key'];
afterEach(() => vi.unstubAllGlobals());

it('reuses uncertain command keys, but allocates a new key after acknowledgement or a new payload', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValueOnce(new TypeError('Lost')).mockResolvedValue(response()));
    const session = owner();
    await expect(sendCommand('/search', { session, body: { query: 'a' } })).rejects.toThrow('Lost');
    await sendCommand('/search', { session, body: { query: 'a' } });
    await sendCommand('/search', { session, body: { query: 'a' } });
    await sendCommand('/search', { session, body: { query: 'b' } });
    expect(key(0)).toBe(key(1)); expect(key(1)).not.toBe(key(2)); expect(key(2)).not.toBe(key(3));
});
it('keeps a key when a successful response fails contract validation', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response()));
    const session = owner();
    await expect(sendCommand('/search', { session, validate: () => { throw new Error('Incomplete'); } })).rejects.toThrow('Incomplete');
    await sendCommand('/search', { session });
    expect(key(0)).toBe(key(1));
});
it('isolates uncertain keys across sessions and supports HTTP without randomUUID', async () => {
    const actual = crypto;
    vi.stubGlobal('crypto', { getRandomValues: actual.getRandomValues.bind(actual) });
    vi.stubGlobal('fetch', vi.fn().mockRejectedValueOnce(new TypeError('Lost')).mockResolvedValue(response()));
    await expect(sendCommand('/search', { session: owner() })).rejects.toThrow('Lost');
    await sendCommand('/search', { session: owner() });
    expect(key(0)).not.toBe(key(1)); expect(key(1)).toMatch(/^[a-f0-9]{32}$/);
});
it('does not reuse an admission key rejected by validation', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response(422)).mockResolvedValue(response()));
    const session = owner();
    await expect(sendCommand('/search', { session })).rejects.toThrow();
    await sendCommand('/search', { session }); expect(key(0)).not.toBe(key(1));
});
it('retains an uncertain key even when its replay is rate limited', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValueOnce(new TypeError('Lost'))
        .mockResolvedValueOnce(response(429)).mockResolvedValue(response()));
    const session = owner();
    await expect(sendCommand('/search', { session })).rejects.toThrow();
    await expect(sendCommand('/search', { session })).rejects.toThrow();
    await sendCommand('/search', { session });
    expect(key(0)).toBe(key(1)); expect(key(1)).toBe(key(2));
});
