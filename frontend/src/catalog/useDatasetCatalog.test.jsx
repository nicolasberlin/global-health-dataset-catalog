import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import { useDatasetCatalog } from './useDatasetCatalog.js';

const response = (items) => ({ ok: true, json: async () => ({ items }) });
const advance = async (ms) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
beforeEach(() => vi.useFakeTimers());
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });

it('coalesces completion bursts and queues one fresh read for completions during a request', async () => {
    let finishFirst;
    global.fetch = vi.fn()
        .mockImplementationOnce(() => new Promise((resolve) => { finishFirst = resolve; }))
        .mockResolvedValue(response([{ id: 'latest' }]));
    const { result } = renderHook(useDatasetCatalog);
    act(() => {
        result.current.loadCollectedDatasets({ silent: true });
        result.current.loadCollectedDatasets({ silent: true });
    });
    await advance(50);
    expect(global.fetch).toHaveBeenCalledTimes(1);
    act(() => {
        result.current.loadCollectedDatasets({ silent: true });
        result.current.loadCollectedDatasets({ silent: true });
    });
    expect(global.fetch).toHaveBeenCalledTimes(1);
    await act(async () => finishFirst(response([{ id: 'stale' }])));
    expect(result.current.collectedDatasets).toEqual([]);
    await advance(1);
    expect(global.fetch).toHaveBeenCalledTimes(2);
    expect(result.current.collectedDatasets).toEqual([{ id: 'latest' }]);
    expect(result.current.collectedLoading).toBe(false);
});
