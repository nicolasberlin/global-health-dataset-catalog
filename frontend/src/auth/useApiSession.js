import { useEffect, useRef, useState } from 'react';

import { apiAuthMode, apiUrl } from '../api/config.js';
import { requestSession } from '../api/client.js';

const STORAGE_KEY = 'global-health-api-token';

// Share only an in-flight bootstrap, not an identity. In StrictMode, aborting the
// first effect must not start competing Set-Cookie responses. Consumers detach
// on unmount, while this short request finishes independently.
const bootstraps = new Map();
const bootstrapCooldowns = new Map();
function bootstrap() {
    const url = apiUrl('/session', 'public');
    const cooldown = bootstrapCooldowns.get(url);
    if (cooldown?.retryAt > Date.now()) return Promise.reject(cooldown);
    bootstrapCooldowns.delete(url);
    if (!bootstraps.has(url)) {
        bootstraps.set(url, requestSession().catch(error => {
            if (error.status === 429) bootstrapCooldowns.set(url, error);
            throw error;
        }).finally(() => bootstraps.delete(url)));
    }
    return bootstraps.get(url);
}

function storedToken() {
    try {
        return window.sessionStorage.getItem(STORAGE_KEY) ?? '';
    } catch {
        return '';
    }
}

export function useApiSession() {
    const mode = apiAuthMode();
    const current = useRef(null);
    const [status, setStatus] = useState(mode === 'public' ? 'preparing' : 'ready');
    const [error, setError] = useState('');
    function createSession(token) {
        const controller = new AbortController();
        const session = {
            token,
            mode,
            local: mode === 'local',
            ready: mode !== 'public',
            cooldowns: new Map(),
            signal: controller.signal,
            abort: () => controller.abort(),
            isCurrent: () => current.current === session && !controller.signal.aborted,
            expire: () => {
                if (!session.isCurrent()) return;
                session.ready = false;
                controller.abort();
                setStatus('expired');
                setError('Your access has expired. Continue to start a new session. Previous searches may no longer be accessible.');
            },
        };
        return session;
    }
    const [session, setSession] = useState(() => {
        current.current = createSession(mode === 'public' ? '' : storedToken());
        return current.current;
    });

    useEffect(() => {
        // React StrictMode runs setup again after cleanup on the initial mount.
        if (session.signal.aborted) {
            current.current = createSession(session.token);
            setSession(current.current);
            return;
        }
        let mounted = true;
        if (mode === 'public') {
            setStatus('preparing');
            setError('');
            Promise.resolve().then(bootstrap).then(() => {
                if (!mounted || !session.isCurrent()) return;
                session.ready = true;
                setStatus('ready');
            }).catch(exception => {
                if (!mounted || !session.isCurrent()) return;
                setStatus('error');
                setError(exception.message || 'Unable to prepare visitor access.');
            });
        }
        return () => { mounted = false; session.abort(); };
    }, [session]);

    function reconnect() {
        if (status === 'preparing') return;
        current.current.abort();
        current.current = createSession('');
        setStatus('preparing');
        setError('');
        setSession(current.current);
    }

    function changeToken(token) {
        if (mode === 'public') return false;
        if (token === current.current.token) return false;
        // Storage failure must not prevent logout or invalidation of old requests.
        try {
            if (token) window.sessionStorage.setItem(STORAGE_KEY, token);
            else window.sessionStorage.removeItem(STORAGE_KEY);
        } catch { /* The token remains usable for this mounted app. */ }
        current.current.abort();
        current.current = createSession(token);
        setSession(current.current);
        return true;
    }

    return { session, status, error, reconnect, changeToken };
}
