import { cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useLinkedDatasets } from './useLinkedDatasets.js';
const reply = items => ({ ok: true, status: 200, json: async () => ({ items }) });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it('batches explicit IDs by 100 and keeps all retrieved records', async () => {
    vi.stubGlobal('fetch', vi.fn(async url => reply(new URL(url).searchParams.getAll('ids').map(id => ({ id: Number(id) })))));
    const { result } = renderHook(() => useLinkedDatasets([], Array.from({ length: 205 }, (_, i) => 205 - i)));
    await waitFor(() => expect(Object.keys(result.current.datasets)).toHaveLength(205));
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(new URL(fetch.mock.calls[0][0]).searchParams.getAll('ids')[0]).toBe('205');
    expect(result.current.loading).toBe(false);
});
it('reports missing records while retaining the available partial records', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => reply([{ id: 2 }])));
    const { result } = renderHook(() => useLinkedDatasets([], [1, 2]));
    await waitFor(() => expect(result.current.error).toMatch(/no longer available/));
    expect(result.current.datasets[2]).toEqual({ id: 2 });
});
it('ignores a delayed response after the selected IDs change', async () => {
    let finish;
    vi.stubGlobal('fetch', vi.fn().mockImplementationOnce(() => new Promise(resolve => { finish = resolve; })).mockResolvedValue(reply([{ id: 2 }])));
    const { result, rerender } = renderHook(({ ids }) => useLinkedDatasets([], ids), { initialProps: { ids: [1] } });
    rerender({ ids: [2] });
    await waitFor(() => expect(result.current.datasets[2]).toBeTruthy());
    finish(reply([{ id: 1 }]));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.datasets[1]).toBeUndefined();
    expect(fetch.mock.calls[0][1].signal.aborted).toBe(true);
});
