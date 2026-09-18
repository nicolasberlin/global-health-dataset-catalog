import { useCallback, useEffect, useRef, useState } from 'react';

import { isAbortError, requestJson } from '../api/client.js';

export function useDatasetCatalog() {
    const [collectedDatasets, setCollectedDatasets] = useState([]);
    const [collectedLoading, setCollectedLoading] = useState(true);
    const [collectedError, setCollectedError] = useState('');
    const worker = useRef(null);

    const loadCollectedDatasets = useCallback(({ silent = false } = {}) => {
        const state = worker.current;
        if (!state) return;
        state.dirty = true;
        if (!silent) setCollectedLoading(true);
        // One request at a time; notifications during it require one follow-up.
        if (!state.controller && !state.timer) state.timer = window.setTimeout(state.run, 50);
    }, []);

    useEffect(() => {
        const state = { dirty: false, controller: null, timer: null };
        worker.current = state;
        state.run = async () => {
            state.timer = null;
            state.dirty = false;
            const controller = new AbortController();
            state.controller = controller;
            setCollectedError('');
            try {
                const data = await requestJson('/collector/collected-datasets', {
                    signal: controller.signal,
                });
                if (!Array.isArray(data.items)) throw new Error('The catalog response is incomplete.');
                if (worker.current === state && !state.dirty) setCollectedDatasets(data.items);
            } catch (error) {
                if (worker.current === state && !state.dirty && !isAbortError(error)) {
                    setCollectedError(error.message || 'Unable to load catalog datasets.');
                }
            } finally {
                state.controller = null;
                if (worker.current === state) {
                    if (state.dirty) state.timer = window.setTimeout(state.run, 0);
                    else setCollectedLoading(false);
                }
            }
        };
        loadCollectedDatasets();
        return () => {
            worker.current = null;
            window.clearTimeout(state.timer);
            state.controller?.abort();
        };
    }, [loadCollectedDatasets]);

    return { collectedDatasets, collectedLoading, collectedError, loadCollectedDatasets };
}
