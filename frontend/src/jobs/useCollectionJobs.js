import { useCallback, useEffect, useRef, useState } from 'react';

import { isAbortError, requestJson } from '../api/client.js';

const terminal = (job) => ['done', 'error'].includes(job.status);

export function useCollectionJobs(session, onSaved) {
    const [jobs, setJobs] = useState({});
    const manager = useRef(null);

    useEffect(() => {
        const state = { session, jobs: new Map(), trackers: new Map(), notified: new Set(), retries: new Map() };
        manager.current = state;
        setJobs({});
        return () => {
            manager.current = null;
            for (const controller of state.retries.values()) controller.abort();
            for (const tracker of state.trackers.values()) {
                window.clearTimeout(tracker.timer);
                tracker.controller?.abort();
            }
        };
    }, [session]);

    const registerJob = useCallback((job, requestSession) => {
        const state = manager.current;
        if (!job?.id || !state || state.session !== requestSession || !requestSession.isCurrent()) {
            return;
        }
        const alive = () => manager.current === state && requestSession.isCurrent();
        function publish(nextJob, tracking = 'current', trackingError = '') {
            if (!alive()) return;
            state.jobs.set(nextJob.id, { job: nextJob, tracking, trackingError });
            setJobs(Object.fromEntries(state.jobs));
            if (nextJob.status === 'done' && nextJob.saved_count > 0 && !state.notified.has(nextJob.id)) {
                state.notified.add(nextJob.id);
                onSaved({ silent: true });
            }
        }
        const previous = state.jobs.get(job.id);
        if (previous && Date.parse(previous.job.updated_at) > Date.parse(job.updated_at)) return;
        // Registration can arrive late or repeatedly from candidates sharing a job.
        // Polling owns updates once a job is registered; terminal responses can finish it.
        if (previous && (terminal(previous.job) || !terminal(job))) return;
        publish(job);
        if (terminal(job)) {
            const tracker = state.trackers.get(job.id);
            if (tracker) {
                window.clearTimeout(tracker.timer);
                tracker.controller?.abort();
                state.trackers.delete(job.id);
            }
            return;
        }

        const tracker = { timer: null, controller: null, failures: 0 };
        state.trackers.set(job.id, tracker);
        async function poll() {
            if (!alive() || state.trackers.get(job.id) !== tracker) return;
            tracker.controller = new AbortController();
            try {
                const data = await requestJson(`/collector/collection-jobs/${job.id}`, {
                    session: requestSession,
                    signal: tracker.controller.signal,
                });
                if (!alive() || state.trackers.get(job.id) !== tracker) return;
                if (data.job?.id !== job.id || !['pending', 'running', 'done', 'error'].includes(data.job.status)) {
                    throw new Error('The collection status response is incomplete.');
                }
                publish(data.job);
                tracker.failures = 0;
                if (terminal(data.job)) {
                    state.trackers.delete(job.id);
                    return;
                }
            } catch (error) {
                if (!alive() || isAbortError(error) || state.trackers.get(job.id) !== tracker) return;
                tracker.failures += 1;
                const unavailable = [401, 403, 404].includes(error.status);
                publish(state.jobs.get(job.id).job, unavailable ? 'unavailable' : 'retrying', error.message);
                if (unavailable) {
                    state.trackers.delete(job.id);
                    return;
                }
            }
            tracker.controller = null;
            if (alive()) {
                const delay = Math.min(1500 * 2 ** Math.min(tracker.failures, 5), 30000);
                tracker.timer = window.setTimeout(poll, delay);
            }
        }
        tracker.timer = window.setTimeout(poll, 700);
    }, [onSaved]);

    const retryJob = useCallback(async (jobId, requestSession) => {
        const state = manager.current;
        const entry = state?.jobs.get(jobId);
        if (!entry || entry.job.status !== 'error' || state.session !== requestSession ||
            !requestSession.isCurrent() || state.retries.has(jobId)) return;
        const controller = new AbortController();
        state.retries.set(jobId, controller);
        state.jobs.set(jobId, { ...entry, retrying: true, trackingError: '' });
        setJobs(Object.fromEntries(state.jobs));
        const alive = () => manager.current === state && requestSession.isCurrent();
        try {
            const data = await requestJson(`/collector/collection-jobs/${jobId}/retry`, {
                method: 'POST', session: requestSession, signal: controller.signal,
            });
            if (!alive()) return;
            if (data.job?.id !== jobId || !['pending', 'running', 'done', 'error'].includes(data.job.status)) {
                throw new Error('The collection retry response is incomplete.');
            }
            state.jobs.delete(jobId);
            registerJob(data.job, requestSession);
        } catch (error) {
            if (!alive() || isAbortError(error)) return;
            state.jobs.set(jobId, { ...entry, retrying: false, trackingError: error.message });
            setJobs(Object.fromEntries(state.jobs));
        } finally {
            state.retries.delete(jobId);
        }
    }, [registerJob]);

    const resolveCollection = useCallback((collection) => {
        if (!collection?.jobId) return collection;
        const entry = jobs[collection.jobId];
        if (!entry || !session.isCurrent()) return null;
        const { job, tracking, trackingError, retrying } = entry;
        return {
            job,
            dataset_ids: job.dataset_ids ?? [],
            state: job.status === 'done' ? (job.saved_count > 0 ? 'saved' : 'empty') : job.status,
            tracking,
            trackingError,
            retrying,
        };
    }, [jobs, session]);

    return { registerJob, resolveCollection, retryJob };
}
