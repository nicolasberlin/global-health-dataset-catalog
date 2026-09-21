import { useCallback, useEffect, useRef, useState } from 'react';

import { isAbortError, requestJson } from '../api/client.js';

const mergeById = (previous, items) => [...new Map(
    [...previous, ...items].map(item => [item.id ?? item.dataset_url, item]),
).values()];

export function useDatasetCatalog() {
    const [collectedDatasets, setCollectedDatasets] = useState([]);
    const [collectedLoading, setCollectedLoading] = useState(true);
    const [collectedLoadingMore, setCollectedLoadingMore] = useState(false);
    const [collectedError, setCollectedError] = useState('');
    const [nextCursor, setNextCursor] = useState(null);
    const [catalogFilters, setCatalogFilters] = useState({ query: '', country: '', format: '' });
    const worker = useRef(null);

    const loadCollectedDatasets = useCallback(({ silent = false } = {}) => {
        const state = worker.current;
        if (!state) return;
        state.dirty = true;
        state.append = false;
        state.nextCursor = null;
        setNextCursor(null);
        if (!silent) setCollectedLoading(true);
        // A refresh supersedes any in-flight append; completion bursts coalesce.
        if (!state.controller && !state.timer) state.timer = window.setTimeout(state.run, 50);
    }, []);

    const loadMoreCollectedDatasets = useCallback(() => {
        const state = worker.current;
        if (!state || state.dirty || state.controller || state.timer || state.nextCursor == null) return;
        state.append = true;
        setCollectedLoadingMore(true);
        state.timer = window.setTimeout(state.run, 0);
    }, []);

    useEffect(() => {
        const state = { dirty: false, append: false, nextCursor: null, controller: null, timer: null };
        worker.current = state;
        setCollectedDatasets([]);
        setCollectedLoadingMore(false);
        state.run = async () => {
            state.timer = null;
            const append = state.append && !state.dirty;
            state.append = false;
            state.dirty = false;
            const controller = new AbortController();
            state.controller = controller;
            setCollectedError('');
            const params = new URLSearchParams();
            if (append) params.set('cursor', String(state.nextCursor));
            for (const [key, value] of Object.entries(catalogFilters)) {
                if (value.trim()) params.set(key, value.trim());
            }
            const suffix = params.size ? `?${params}` : '';
            try {
                const data = await requestJson(`/collector/collected-datasets${suffix}`, {
                    signal: controller.signal,
                });
                if (!Array.isArray(data.items) || (data.next_cursor != null &&
                    (!Number.isSafeInteger(data.next_cursor) || data.next_cursor < 1))) {
                    throw new Error('The catalog response is incomplete.');
                }
                if (worker.current === state && !state.dirty) {
                    setCollectedDatasets(previous => mergeById(append ? previous : [], data.items));
                    state.nextCursor = data.next_cursor ?? null;
                    setNextCursor(state.nextCursor);
                }
            } catch (error) {
                if (worker.current === state && !state.dirty && !isAbortError(error)) {
                    setCollectedError(error.message || 'Unable to load catalog datasets.');
                }
            } finally {
                state.controller = null;
                if (worker.current === state) {
                    if (state.dirty) state.timer = window.setTimeout(state.run, 0);
                    else {
                        setCollectedLoading(false);
                        setCollectedLoadingMore(false);
                    }
                }
            }
        };
        loadCollectedDatasets();
        return () => {
            worker.current = null;
            window.clearTimeout(state.timer);
            state.controller?.abort();
        };
    }, [catalogFilters, loadCollectedDatasets]);

    return {
        collectedDatasets, collectedLoading, collectedLoadingMore, collectedError,
        loadCollectedDatasets, loadMoreCollectedDatasets, nextCursor,
        catalogFilters, setCatalogFilters,
    };
}
