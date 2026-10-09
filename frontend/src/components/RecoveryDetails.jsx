import { useEffect, useState } from 'react';
import { canRetry, diagnosticText, retryDate } from '../jobs/recovery.js';

export function RetryAction({ errors = [], busy, onRetry, label, retryAt = 0 }) {
    const due = Math.max(retryAt, retryDate(errors));
    const [now, setNow] = useState(Date.now());
    useEffect(() => {
        setNow(Date.now());
        if (due <= Date.now()) return;
        const timer = setTimeout(() => setNow(Date.now()), Math.min(due - Date.now() + 50, 2147483647));
        return () => clearTimeout(timer);
    }, [due]);
    if (!onRetry || !canRetry(errors)) return null;
    return <button type="button" disabled={busy || due > now} onClick={onRetry}>
        {busy ? 'Requesting retry…' : due > now ? `Retry after ${new Date(due).toLocaleTimeString()}` : label}
    </button>;
}

export default function RecoveryDetails({ errors = [] }) {
    const automatic = errors.some(error => error.recovery === 'automatic');
    const message = diagnosticText(errors);
    return <>
        {automatic && <p role="status">Waiting for an automatic retry{retryDate(errors)
            ? ` after ${new Date(retryDate(errors)).toLocaleTimeString()}` : ''}.</p>}
        {message && <p>{message}</p>}
        {errors.some(error => error.recovery === 'configuration_required') &&
            <p>The service configuration needs attention. Retrying from this page will not fix it.</p>}
    </>;
}
