export function apiAuthMode() {
    const mode = import.meta.env.VITE_API_AUTH_MODE ?? 'token';
    if (!['token', 'local', 'public'].includes(mode)) {
        throw new Error('Invalid API access configuration.');
    }
    // Local bypass remains restricted to the development build.
    return mode === 'local' && !import.meta.env.DEV ? 'token' : mode;
}

export function apiUrl(path, mode = apiAuthMode()) {
    const base = import.meta.env.VITE_API_BASE_URL ??
        (mode === 'public' ? '' : 'http://127.0.0.1:8001');
    const url = `${base.replace(/\/$/, '')}${path}`;
    if (mode === 'public' && new URL(url, window.location.href).origin !== window.location.origin) {
        throw new Error('Public access requires the website and API to use the same origin.');
    }
    return url;
}
