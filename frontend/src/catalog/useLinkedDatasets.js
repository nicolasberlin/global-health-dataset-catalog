import { useEffect, useState } from 'react';

import { isAbortError, requestJson } from '../api/client.js';

export function useLinkedDatasets(candidates, localIds = []) {
    const [datasets, setDatasets] = useState({});
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const [retry, setRetry] = useState(0);
    const ids = [...new Set([...localIds, ...candidates.flatMap(candidate =>
        candidate.item.automatic_collection?.dataset_ids ?? [],
    )])];
    const signature = JSON.stringify({
        ids,
        revisions: candidates.map(candidate => candidate.item.automatic_collection?.job?.finished_at ?? ''),
    });

    useEffect(() => {
        const controller = new AbortController();
        const requested = JSON.parse(signature).ids;
        setError('');
        setLoading(requested.length > 0);
        if (!requested.length) {
            setDatasets({});
            return () => controller.abort();
        }
        async function load() {
            try {
                const result = {};
                for (let offset = 0; offset < requested.length; offset += 100) {
                    const params = new URLSearchParams();
                    requested.slice(offset, offset + 100).forEach(id => params.append('ids', id));
                    const data = await requestJson(`/collector/collected-datasets/by-id?${params}`, {
                        signal: controller.signal,
                    });
                    if (!Array.isArray(data.items)) throw new Error('The dataset response is incomplete.');
                    for (const item of data.items) {
                        if (!requested.includes(item.id)) throw new Error('Unexpected dataset identity.');
                        result[item.id] = item;
                    }
                }
                if (!controller.signal.aborted) {
                    setDatasets(result);
                    if (requested.some(id => !result[id])) setError('Some saved datasets are no longer available.');
                }
            } catch (exception) {
                if (!controller.signal.aborted && !isAbortError(exception)) {
                    setError(exception.message || 'Unable to load saved dataset details.');
                }
            } finally {
                if (!controller.signal.aborted) setLoading(false);
            }
        }
        load();
        return () => controller.abort();
    }, [signature, retry]);

    return { datasets, error, loading, retry: () => setRetry(value => value + 1) };
}
