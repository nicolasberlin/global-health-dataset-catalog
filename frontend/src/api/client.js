import { apiAuthMode, apiUrl } from './config.js';

export function isAbortError(error) {
    return error?.name === 'AbortError';
}

export function requestJson(path, options) {
    return requestApi(path, options);
}

// Bootstrap has a deliberately empty response; other successful endpoints must return JSON.
export function requestSession() {
    return requestApi('/session', { method: 'POST' }, true);
}

async function requestApi(path, { session, signal, ...options } = {}, empty = false) {
    const mode = session?.mode ?? apiAuthMode();
    if (session && !session.isCurrent()) throw new DOMException('Session ended', 'AbortError');
    if (session && mode === 'public' && !session.ready) {
        throw new Error('Visitor access is not ready yet.');
    }
    if (session && mode !== 'public' && !session.local && !session.token) {
        throw new Error('An API token is required for this operation.');
    }
    const url = apiUrl(path, mode);
    const key = `${options.method ?? 'GET'} ${url}`;
    const cooldown = session?.cooldowns?.get(key);
    if (cooldown?.retryAt > Date.now()) throw cooldown;
    session?.cooldowns?.delete(key);

    const controller = new AbortController();
    const signals = [signal, session?.signal].filter(Boolean);
    const abort = () => controller.abort();
    for (const source of signals) {
        source.addEventListener('abort', abort, { once: true });
        if (source.aborted) abort();
    }
    try {
        const headers = new Headers(options.headers);
        if (mode === 'public') headers.delete('Authorization');
        else if (session && !session.local) headers.delete('Authorization');
        const response = await fetch(url, {
            ...options,
            credentials: mode === 'public' ? 'same-origin' : options.credentials,
            signal: controller.signal,
            headers: {
                ...Object.fromEntries(headers),
                ...(session && mode !== 'public' && !session.local
                    ? { Authorization: `Bearer ${session.token}` } : {}),
            },
        });
        const payload = response.status === 204 ? null : await response.json().catch(() => null);
        // Abort can race with response parsing (or be ignored by a transport).
        if (controller.signal.aborted || (session && !session.isCurrent())) {
            throw new DOMException('Request cancelled', 'AbortError');
        }
        if (!response.ok) {
            const error = new Error(
                typeof payload?.detail === 'string' ? payload.detail : 'API request failed.',
            );
            error.status = response.status;
            if (response.status === 429) {
                const value = response.headers?.get('Retry-After');
                const seconds = value && /^\d+$/.test(value) ? Number(value) :
                    Math.ceil((Date.parse(value) - Date.now()) / 1000);
                error.retryAt = Date.now() + Math.max(1, Number.isFinite(seconds) ? seconds : 5) * 1000;
                error.message += ` Please wait ${Math.ceil((error.retryAt - Date.now()) / 1000)} seconds before trying again.`;
                session?.cooldowns?.set(key, error);
            }
            if (response.status === 401 && mode === 'public') session?.expire();
            throw error;
        }
        if (empty) {
            if (response.status !== 204) throw new Error('The session response is incomplete.');
            return;
        }
        if (payload === null) throw new Error('The API response is incomplete.');
        return payload;
    } finally {
        for (const source of signals) source.removeEventListener('abort', abort);
    }
}
