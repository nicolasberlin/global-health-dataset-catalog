import { useEffect, useRef, useState } from 'react';
import { isAbortError, requestJson } from '../api/client.js';

const mergeAttempts = (older, current, key) => {
    const seen = new Set();
    return [...older, ...current].filter(attempt => {
        const identity = key(attempt);
        if (seen.has(identity)) return false;
        seen.add(identity);
        return true;
    });
};

export default function useCollectionHistory(job, session, open) {
    const [trace, setTrace] = useState(null);
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const [paging, setPaging] = useState(false);
    const generation = useRef(0);
    const requests = useRef(new Set());

    useEffect(() => {
        const current = ++generation.current;
        setError('');
        setPaging(false);
        setLoading(false);
        setTrace(null);
        if (!open || !session?.isCurrent()) return;
        const controller = new AbortController();
        requests.current.add(controller);
        setLoading(true);
        requestJson(`/collector/collection-jobs/${job.id}/diagnostics`, {
            session, signal: controller.signal,
        }).then(data => {
            if (data.job_id !== job.id || !Array.isArray(data.method_attempts)) {
                throw new Error('Invalid collection diagnostic response.');
            }
            if (generation.current === current) setTrace(data);
        }).catch(failure => {
            if (generation.current === current && !isAbortError(failure)) setError(failure.message);
        }).finally(() => {
            requests.current.delete(controller);
            if (generation.current === current) setLoading(false);
        });
        return () => {
            generation.current++;
            for (const pending of requests.current) pending.abort();
            requests.current.clear();
        };
    }, [open, job.id, job.updated_at, session]);

    const loadEarlier = async kind => {
        const history = kind === 'methods' ? trace : trace?.classification_history;
        const offset = history?.next_offset;
        if (!open || paging || !session?.isCurrent() || !Number.isInteger(offset)) return;
        const current = generation.current;
        const controller = new AbortController();
        requests.current.add(controller);
        setPaging(true);
        setError('');
        const endpoint = kind === 'methods' ? 'diagnostics' : 'classification-history';
        try {
            const data = await requestJson(
                `/collector/collection-jobs/${job.id}/${endpoint}?offset=${offset}`,
                { session, signal: controller.signal },
            );
            if (kind === 'methods' ? data.job_id !== job.id || !Array.isArray(data.method_attempts)
                : !Array.isArray(data.attempts)) {
                throw new Error('Invalid collection history response.');
            }
            if (generation.current !== current) return;
            setTrace(previous => kind === 'methods' ? {
                ...previous,
                ...data,
                classification_history: previous.classification_history,
                checks_truncated: previous.checks_truncated || data.checks_truncated,
                method_attempts: mergeAttempts(data.method_attempts, previous.method_attempts,
                    attempt => attempt.id),
            } : {
                ...previous,
                classification_history: {
                    ...data,
                    attempts: mergeAttempts(data.attempts, previous.classification_history.attempts,
                        attempt => `${attempt.run_id}:${attempt.voter_id}:${attempt.attempt}`),
                },
            });
        } catch (failure) {
            if (generation.current === current && !isAbortError(failure)) setError(failure.message);
        } finally {
            requests.current.delete(controller);
            if (generation.current === current) setPaging(false);
        }
    };

    return { trace, error, loading, paging, loadEarlier };
}
