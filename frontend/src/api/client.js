const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8001';

export function isAbortError(error) {
    return error?.name === 'AbortError';
}

export async function requestJson(path, { session, signal, ...options } = {}) {
    if (session && !session.isCurrent()) throw new DOMException('Session ended', 'AbortError');
    if (session && !session.local && !session.token) {
        throw new Error('An API token is required for this operation.');
    }

    const controller = new AbortController();
    const signals = [signal, session?.signal].filter(Boolean);
    const abort = () => controller.abort();
    for (const source of signals) {
        source.addEventListener('abort', abort, { once: true });
        if (source.aborted) abort();
    }
    try {
        const response = await fetch(`${API_BASE_URL}${path}`, {
            ...options,
            signal: controller.signal,
            headers: {
                ...options.headers,
                ...(session && !session.local ? { Authorization: `Bearer ${session.token}` } : {}),
            },
        });
        const payload = await response.json().catch(() => null);
        // Abort can race with response parsing (or be ignored by a transport).
        if (controller.signal.aborted || (session && !session.isCurrent())) {
            throw new DOMException('Request cancelled', 'AbortError');
        }
        if (!response.ok) {
            const error = new Error(
                typeof payload?.detail === 'string' ? payload.detail : 'API request failed.',
            );
            error.status = response.status;
            throw error;
        }
        if (payload === null) throw new Error('The API response is incomplete.');
        return payload;
    } finally {
        for (const source of signals) source.removeEventListener('abort', abort);
    }
}
