export function client(token = '') {
    return async (path, options = {}) => {
        const response = await fetch(`/lab${path}`, {
            ...options, credentials: 'omit', headers: {
                ...(token ? { Authorization: `Bearer ${token}` } : {}),
                ...(options.body ? { 'Content-Type': 'application/json' } : {}),
            },
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || `Request failed (HTTP ${response.status})`);
        return data;
    };
}

export function date(value) {
    if (!value) return 'Unknown';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return 'Unknown';
    return parsed.toLocaleString('en-GB', { timeZone: 'Europe/Zurich' });
}

export function download(document) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(document, null, 2)], { type: 'application/json' }));
    const anchor = window.document.createElement('a');
    anchor.href = url; anchor.download = `search-lab-${document.id}.json`;
    anchor.click(); URL.revokeObjectURL(url);
}
