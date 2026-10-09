// Build the asynchronous admission + snapshot + by-ID responses from each
// scenario's dataset/candidate fixtures. All calls still use the real API client.
export function snapshot(data) {
    const items = data.origin === 'database' ? [] : (data.items ?? []);
    const polling = data.polling_required ?? items.some(item =>
        ['queued', 'classifying'].includes(item.classification_status) ||
        ['pending', 'running'].includes(item.automatic_collection?.state));
    return { query: 'mortality', origin: 'online', errors: [], warnings: [],
        local_dataset_ids: [], dataset_ids: [], attempt: 1,
        execution_status: polling ? 'running' : 'finished',
        outcome: polling ? null : items.length ? 'results' : 'empty',
        ...data, items, polling_required: polling,
        ...(data.origin === 'database' ? { local_dataset_ids: (data.items ?? []).map(item => item.id) } : {}),
    };
}
const reply = (data, status = 200) => ({ ok: true, status, json: async () => data });
export function searchApi(handler) {
    const initial = new Map(), datasets = new Map(), contexts = new Map();
    return async (input, options = {}) => {
        const url = String(input);
        if (url.includes('/collected-datasets/by-id?')) {
            const ids = new URL(url, 'http://test').searchParams.getAll('ids').map(Number);
            return reply({ items: ids.map(id => datasets.get(id)).filter(Boolean) });
        }
        const match = url.match(/\/searches\/([^/]+)\/progress$/);
        if (match && initial.has(match[1])) {
            const data = initial.get(match[1]); initial.delete(match[1]);
            return reply(data);
        }
        const response = await handler(input, options);
        if (!response?.ok || !(url.endsWith('/searches') || url.endsWith('/searches/latest') || match)) return response;
        const data = await response.json();
        if (url.endsWith('/searches')) {
            for (const item of data.origin === 'database' ? data.items : []) datasets.set(item.id, item);
            initial.set(data.search_id, snapshot(data));
            contexts.set(data.search_id, { origin: data.origin, query: data.query ?? JSON.parse(options.body).query });
            return reply({ search_id: data.search_id, execution_status: 'queued', attempt: 1,
                progress_url: `/collector/searches/${data.search_id}/progress` }, 202);
        }
        return reply(snapshot({ ...contexts.get(data.search_id), ...data }));
    };
}
