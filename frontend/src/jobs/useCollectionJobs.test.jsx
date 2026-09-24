import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

import { useCollectionJobs } from './useCollectionJobs.js';

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });

it('notifies completion once and cannot regress to a late pending registration', async () => {
    vi.useFakeTimers();
    const session = { token: 'test', isCurrent: () => true, signal: new AbortController().signal };
    const onSaved = vi.fn();
    global.fetch = vi.fn();
    const { result } = renderHook(() => useCollectionJobs(session, onSaved));
    const done = { id: 42, status: 'done', saved_count: 1 };
    act(() => {
        result.current.registerJob(done, session);
        result.current.registerJob(done, session);
        result.current.registerJob({ ...done, status: 'pending', saved_count: 0 }, session);
    });
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(global.fetch).not.toHaveBeenCalled();
    expect(result.current.resolveCollection({ jobId: 42 })).toMatchObject({ job: done, state: 'saved' });
});

it('explicitly retries a failed job once and resumes polling with saved vote progress', async () => {
    vi.useFakeTimers();
    const session = { token: 'test', isCurrent: () => true, signal: new AbortController().signal };
    const onSaved = vi.fn();
    const progress = { total: 3, succeeded: 2, failed: 1 };
    const failed = { id: 42, status: 'error', classification_progress: progress, updated_at: '2026-09-22T10:00:00Z' };
    const pending = { ...failed, status: 'pending', updated_at: '2026-09-22T10:01:00Z' };
    const done = { ...pending, status: 'done', saved_count: 1, classification_progress: { total: 3, succeeded: 3, failed: 0 } };
    global.fetch = vi.fn()
        .mockResolvedValueOnce({ ok: true, json: async () => ({ job: pending }) })
        .mockResolvedValueOnce({ ok: true, json: async () => ({ job: done }) });
    const { result } = renderHook(() => useCollectionJobs(session, onSaved));
    act(() => result.current.registerJob(failed, session));
    await act(async () => {
        await Promise.all([result.current.retryJob(42, session), result.current.retryJob(42, session)]);
    });
    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(global.fetch.mock.calls[0][0]).toContain('/collection-jobs/42/retry');
    expect(global.fetch.mock.calls[0][1].method).toBe('POST');
    act(() => result.current.registerJob(failed, session));
    expect(result.current.resolveCollection({ jobId: 42 })).toMatchObject({ state: 'pending', job: { classification_progress: progress } });
    await act(async () => vi.advanceTimersByTimeAsync(750));
    expect(result.current.resolveCollection({ jobId: 42 })).toMatchObject({ state: 'saved', job: { classification_progress: { succeeded: 3 } } });
    expect(onSaved).toHaveBeenCalledTimes(1);
});

it('keeps failed job retryable when a retry request fails', async () => {
    const session = { token: 'test', isCurrent: () => true, signal: new AbortController().signal };
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 429, json: async () => ({ detail: 'Quota exceeded.' }) });
    const { result } = renderHook(() => useCollectionJobs(session, vi.fn()));
    act(() => result.current.registerJob({ id: 42, status: 'error' }, session));
    await act(async () => result.current.retryJob(42, session));
    expect(result.current.resolveCollection({ jobId: 42 })).toMatchObject({
        state: 'error', retrying: false, trackingError: expect.stringContaining('Quota exceeded.'),
    });
});
