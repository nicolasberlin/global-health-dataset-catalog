import { act, cleanup, renderHook } from '@testing-library/react';
import { StrictMode } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useSearchProgress } from './useSearchProgress.js';
const item = (search = 'a', id = 'one') => ({ search_id: search, candidate_id: id, classification_status: 'queued' });
const done = value => ({ ...value, classification_status: 'rejected', classification: { accepted: false } });
const reply = (items, polling_required = true) => ({ ok: true, status: 200,
    json: async () => ({ search_id: items[0]?.search_id ?? 'a', items, polling_required }) });
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { resolve, promise }; };
const tick = async (ms = 0) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
function session() {
    const controller = new AbortController();
    return { local: true, mode: 'local', ready: true, signal: controller.signal,
        isCurrent: () => !controller.signal.aborted, cooldowns: new Map() };
}
function setup() {
    const owner = session(), update = vi.fn(), saved = vi.fn();
    return { ...renderHook(({ current }) => useSearchProgress(current, update, saved), {
        initialProps: { current: owner }, wrapper: StrictMode,
    }), owner, update, saved };
}
beforeEach(() => { vi.useFakeTimers(); global.fetch = vi.fn(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });
it('polls ten candidates once per search and stops after completion', async () => {
    const { result, owner } = setup();
    const items = Array.from({ length: 10 }, (_, i) => item('a', String(i)));
    fetch.mockResolvedValueOnce(reply(items)).mockResolvedValueOnce(reply(items.map(done), false));
    act(() => result.current.followSearch('a', items, owner));
    await tick(1999); expect(fetch).not.toHaveBeenCalled();
    await tick(1); expect(fetch).toHaveBeenCalledTimes(1);
    await tick(2000); expect(fetch).toHaveBeenCalledTimes(2);
    await tick(20000); expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch.mock.calls.every(([url]) => url.endsWith('/searches/a/progress'))).toBe(true);
});
it('does not overlap slow requests or publish into a replacement session', async () => {
    const late = deferred(); fetch.mockReturnValue(late.promise);
    const { result, owner, update, rerender } = setup();
    act(() => result.current.followSearch('a', [item()], owner));
    await tick(2000); await tick(20000); expect(fetch).toHaveBeenCalledTimes(1);
    const signal = fetch.mock.calls[0][1].signal;
    rerender({ current: session() }); expect(signal.aborted).toBe(true);
    update.mockClear();
    await act(async () => late.resolve(reply([done(item())], false)));
    expect(update).not.toHaveBeenCalled();
});
it('tracks two searches and accepts vote updates with unchanged timestamps', async () => {
    const { result, owner, update } = setup();
    fetch.mockImplementation(url => reply([{ ...item(url.includes('/a/') ? 'a' : 'b'),
        updated_at: 'same', classification_progress: { succeeded: 2 } }]));
    act(() => { result.current.followSearch('a', [item()], owner); result.current.followSearch('b', [item('b')], owner); });
    await tick(2000); expect(fetch).toHaveBeenCalledTimes(2);
    expect(update.mock.calls.at(-1)[1][0].classification_progress.succeeded).toBe(2);
});
it.each(['10', 'date'])('honors Retry-After %s and retains existing results', async header => {
    const value = header === 'date' ? new Date(Date.now() + 12000).toUTCString() : header;
    fetch.mockResolvedValueOnce({ ok: false, status: 429, headers: new Headers({ 'Retry-After': value }),
        json: async () => ({ detail: 'Slow down' }) }).mockResolvedValue(reply([done(item())], false));
    const { result, owner, update } = setup();
    act(() => result.current.followSearch('a', [item()], owner));
    await tick(2000); expect(update.mock.calls.at(-1)[1][0].classification_status).toBe('queued');
    await tick(8500); expect(fetch).toHaveBeenCalledTimes(1);
    await tick(2000); expect(fetch).toHaveBeenCalledTimes(2);
});
it.each([401, 403, 404])('stops on HTTP %s', async status => {
    fetch.mockResolvedValue({ ok: false, status, json: async () => ({ detail: 'Unavailable' }) });
    const { result, owner } = setup();
    act(() => result.current.followSearch('a', [item()], owner));
    await tick(2000); await tick(60000); expect(fetch).toHaveBeenCalledTimes(1);
});
it('rejects missing candidates and backs off before recovering', async () => {
    fetch.mockResolvedValueOnce(reply([], false)).mockResolvedValue(reply([done(item())], false));
    const { result, owner, update } = setup();
    act(() => result.current.followSearch('a', [item()], owner));
    await tick(2000); expect(update.mock.calls.at(-1)[3]).toMatch(/incomplete/);
    await tick(3999); expect(fetch).toHaveBeenCalledTimes(1);
    await tick(1); expect(fetch).toHaveBeenCalledTimes(2);
});
it('restarts shared jobs after a lost retry acknowledgement without replaying the POST', async () => {
    const failed = search => ({ ...item(search), classification_status: 'accepted', classification: { accepted: true },
        automatic_collection: { state: 'error', job: { id: 42, status: 'error', saved_count: 0 } } });
    const { result, owner, update } = setup();
    act(() => { result.current.followSearch('a', [failed('a')], owner); result.current.followSearch('b', [failed('b')], owner); });
    fetch.mockImplementation((url, options) => options.method === 'POST' ? Promise.reject(new TypeError('Lost acknowledgement')) :
        Promise.resolve(reply([{ ...failed(url.includes('/a/') ? 'a' : 'b'), automatic_collection: {
            state: 'pending', job: { id: 42, status: 'pending', saved_count: 0 },
        } }])));
    await act(async () => result.current.retryCollection(failed('a'), owner));
    await tick();
    expect(fetch.mock.calls.filter(([, options]) => options.method === 'POST')).toHaveLength(1);
    for (const id of ['a', 'b']) expect(update.mock.calls.filter(call => call[0] === id).at(-1)[1][0].automatic_collection.state).toBe('pending');
});

it('invalidates a stale completion when a retry starts and deduplicates double clicks', async () => {
    const { result, owner, update } = setup();
    const failed = { ...item(), classification_status: 'accepted', classification: { accepted: true },
        automatic_collection: { state: 'error', job: { id: 42, status: 'error', saved_count: 0 } } };
    const pending = { ...failed, automatic_collection: { state: 'pending', job: { id: 42, status: 'pending' } } };
    act(() => result.current.followSearch('a', [failed], owner));
    const old = deferred(), post = deferred();
    fetch.mockReturnValueOnce(old.promise);
    act(() => document.dispatchEvent(new Event('visibilitychange')));
    await tick();
    const oldSignal = fetch.mock.calls[0][1].signal;
    fetch.mockImplementation((url, options) => options.method === 'POST' ? post.promise : reply([pending]));
    let first;
    act(() => {
        first = result.current.retryCollection(failed, owner);
        void result.current.retryCollection(failed, owner);
    });
    expect(oldSignal.aborted).toBe(true);
    await act(async () => old.resolve(reply([failed], false)));
    await act(async () => { post.resolve({ ok: true, status: 202, json: async () => ({ job: pending.automatic_collection.job }) }); await first; });
    await tick();
    expect(update.mock.calls.at(-1)[1][0].automatic_collection.state).toBe('pending');
    expect(fetch.mock.calls.filter(([, options]) => options.method === 'POST')).toHaveLength(1);
    await tick(2000);
    expect(fetch.mock.calls.filter(([, options]) => options.method !== 'POST')).toHaveLength(3);
});

it('notifies once when two searches share a saved job and restores stopped searches', async () => {
    const { result, owner, saved } = setup();
    const completed = search => ({ ...item(search), classification_status: 'accepted', classification: { accepted: true },
        automatic_collection: { state: 'saved', job: { id: 42, status: 'done', saved_count: 1 } } });
    act(() => {
        result.current.followSearch('a', [completed('a')], owner);
        result.current.followSearch('b', [completed('b')], owner);
    });
    expect(saved).toHaveBeenCalledTimes(1);
    await tick(10000); expect(fetch).not.toHaveBeenCalled();
    fetch.mockResolvedValue(reply([completed('a')], false));
    act(() => result.current.followSearch('a', [completed('a')], owner));
    await tick(); expect(fetch).toHaveBeenCalledTimes(1);
    await tick(10000); expect(fetch).toHaveBeenCalledTimes(1);
});
