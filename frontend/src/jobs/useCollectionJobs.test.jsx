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
