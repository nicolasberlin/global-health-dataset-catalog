import { useEffect, useRef, useState } from 'react';

const STORAGE_KEY = 'global-health-api-token';

function storedToken() {
    try {
        return window.sessionStorage.getItem(STORAGE_KEY) ?? '';
    } catch {
        return '';
    }
}

export function useApiSession(local) {
    const current = useRef(null);
    function createSession(token) {
        const controller = new AbortController();
        const session = {
            token,
            local,
            signal: controller.signal,
            abort: () => controller.abort(),
            isCurrent: () => current.current === session && !controller.signal.aborted,
        };
        return session;
    }
    const [session, setSession] = useState(() => {
        current.current = createSession(storedToken());
        return current.current;
    });

    useEffect(() => {
        // React StrictMode runs setup again after cleanup on the initial mount.
        if (current.current.signal.aborted) {
            current.current = createSession(current.current.token);
            setSession(current.current);
        }
        return () => current.current.abort();
    }, []);

    function changeToken(token) {
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

    return { session, changeToken };
}
