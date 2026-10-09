import { useCallback, useEffect, useRef } from 'react';

import { sendCommand, forgetCommand } from '../api/commands.js';
import { isAbortError, requestJson } from '../api/client.js';

const active = item => ['queued', 'classifying'].includes(item.classification_status) ||
    ['pending', 'running'].includes(item.automatic_collection?.state);
const MAX_TRACKING_FAILURES = 3;
const TRACKING_TIMEOUT_MS = 15000;

export function validateSearchProgress(data, id, expectedIds = new Set()) {
    if (data?.search_id !== id || typeof data.polling_required !== 'boolean' ||
        !Array.isArray(data.items) || typeof data.query !== 'string' ||
        !['queued', 'running', 'waiting_retry', 'finished', 'failed'].includes(data.execution_status) ||
        ![null, 'results', 'empty', 'incomplete'].includes(data.outcome) ||
        ![null, 'database', 'online'].includes(data.origin) ||
        !Array.isArray(data.local_dataset_ids) || !Array.isArray(data.dataset_ids) ||
        ![...data.local_dataset_ids, ...data.dataset_ids].every(Number.isInteger) ||
        !Array.isArray(data.errors) || !Array.isArray(data.warnings)) throw new Error('The search progress response is incomplete.');
    if (data.polling_required !== ['queued', 'running', 'waiting_retry'].includes(data.execution_status) ||
        (data.polling_required && data.outcome !== null)) {
        throw new Error('The search lifecycle response is inconsistent.');
    }
    const ids = new Set();
    for (const item of data.items) {
        if (item.search_id !== id || typeof item.candidate_id !== 'string' || ids.has(item.candidate_id) ||
            !['pending', 'queued', 'classifying', 'accepted', 'rejected', 'error'].includes(item.classification_status) ||
            (['accepted', 'rejected'].includes(item.classification_status) &&
                typeof item.classification?.accepted !== 'boolean') ||
            (item.classification_status === 'accepted' && !item.automatic_collection)) {
            throw new Error('The search progress response is incomplete.');
        }
        const collection = item.automatic_collection;
        if (collection && (!['pending', 'running', 'saved', 'empty', 'error'].includes(collection.state) ||
            (collection.job && (!collection.job.id ||
                !['pending', 'running', 'done', 'error'].includes(collection.job.status))))) {
            throw new Error('The collection progress response is incomplete.');
        }
        ids.add(item.candidate_id);
    }
    if ([...expectedIds].some(value => !ids.has(value)) ||
        (!data.polling_required && data.items.some(active))) {
        throw new Error('The search progress response is incomplete.');
    }
    return data;
}

// Snapshots belong to searches, not to the currently visible screen. Shared jobs
// do not merge snapshots from independent requests into one mutable job object.
export function useSearchProgress(session, onUpdate, onSaved) {
    const callbacks = useRef({ onUpdate, onSaved });
    callbacks.current = { onUpdate, onSaved };
    const manager = useRef(null);

    useEffect(() => {
        const state = { session, searches: new Map(), notified: new Set(), commands: new Map(), uncertain: new Map() };
        manager.current = state;
        const refresh = () => {
            if (document.visibilityState !== 'visible') return;
            for (const entry of state.searches.values()) {
                if (!entry.unavailable && !entry.busy && !entry.controller) entry.schedule(0);
            }
        };
        document.addEventListener('visibilitychange', refresh);
        return () => {
            manager.current = null;
            document.removeEventListener('visibilitychange', refresh);
            for (const entry of state.searches.values()) entry.invalidate();
            for (const controller of state.commands.values()) controller.abort();
        };
    }, [session]);

    const followSearch = useCallback((id, items, requestSession, snapshot = null) => {
        const state = manager.current;
        if (!state || state.session !== requestSession || !requestSession.isCurrent()) return;
        const previous = state.searches.get(id);
        if (previous) {
            previous.stopped = false;
            previous.failures = 0;
            previous.publish();
            // Restoring a stopped search must discover a retry made elsewhere.
            if (!previous.timer) previous.schedule(0);
            return;
        }
        const entry = { items, snapshot, failures: 0, retryAt: 0, generation: 0, timer: null,
            controller: null, busy: 0, unavailable: false, stopped: false, error: '' };
        state.searches.set(id, entry);
        const alive = () => manager.current === state && requestSession.isCurrent();
        entry.invalidate = () => {
            entry.generation += 1;
            window.clearTimeout(entry.timer);
            window.clearTimeout(entry.timeout);
            entry.timer = null;
            entry.controller?.abort();
            entry.controller = null;
        };
        entry.publish = () => {
            if (!alive()) return;
            const tracking = entry.unavailable ? 'unavailable' : entry.stopped ? 'stopped' :
                entry.error ? 'retrying' : 'current';
            callbacks.current.onUpdate(id, entry.items.map(item => item.automatic_collection ? {
                ...item, automatic_collection: { ...item.automatic_collection,
                    tracking,
                    trackingError: item.automatic_collection.trackingError || entry.error,
                },
            } : item), requestSession, entry.error, entry.snapshot, tracking);
            let saved = false;
            for (const item of entry.items) {
                const job = item.automatic_collection?.job;
                if (job?.status === 'done' && job.saved_count > 0 && !state.notified.has(job.id)) {
                    state.notified.add(job.id);
                    saved = true;
                }
            }
            if (saved) callbacks.current.onSaved({ silent: true });
        };
        entry.schedule = (delay = 2000) => {
            window.clearTimeout(entry.timer);
            entry.timer = null;
            if (!alive() || entry.busy || entry.unavailable || entry.stopped || entry.controller) return;
            entry.timer = window.setTimeout(poll, Math.max(delay, entry.retryAt - Date.now()));
        };
        async function poll() {
            entry.timer = null;
            if (!alive() || entry.busy || entry.unavailable || entry.stopped || entry.controller) return;
            const generation = entry.generation;
            const controller = new AbortController();
            entry.controller = controller;
            const current = () => alive() && generation === entry.generation;
            let next = false;
            let timeout;
            try {
                const request = requestJson(`/collector/searches/${id}/progress`, {
                    session: requestSession, signal: controller.signal,
                });
                const deadline = new Promise((_, reject) => {
                    timeout = window.setTimeout(() => {
                        reject(new Error('Progress request timed out after 15 seconds.'));
                        controller.abort();
                    }, TRACKING_TIMEOUT_MS);
                    entry.timeout = timeout;
                });
                const data = validateSearchProgress(await Promise.race([request, deadline]),
                    id, new Set(entry.items.map(item => item.candidate_id)));
                if (!current()) return;
                if (entry.snapshot?.attempt && data.attempt > entry.snapshot.attempt) {
                    forgetCommand(requestSession, `/collector/searches/${id}/retry`);
                }
                for (const [path, record] of state.uncertain) {
                    if (record.searchId !== id) continue;
                    const item = data.items.find(value => value.candidate_id === record.candidateId);
                    const version = record.collection ? item?.automatic_collection?.job?.updated_at : item?.updated_at;
                    if (version && version !== record.version) {
                        forgetCommand(requestSession, path);
                        state.uncertain.delete(path);
                    }
                }
                entry.items = data.items;
                entry.snapshot = data;
                entry.error = '';
                entry.failures = 0;
                entry.retryAt = 0;
                entry.publish();
                next = data.polling_required;
            } catch (error) {
                if (!current() || isAbortError(error)) return;
                entry.failures += 1;
                entry.retryAt = error.retryAt ?? 0;
                entry.error = error.message;
                entry.unavailable = [401, 403, 404].includes(error.status);
                entry.stopped = entry.failures >= MAX_TRACKING_FAILURES;
                entry.publish();
                next = !entry.unavailable && !entry.stopped;
            } finally {
                window.clearTimeout(timeout);
                if (current()) {
                    entry.controller = null;
                    if (next) entry.schedule(Math.min(2000 * 2 ** entry.failures, 30000));
                }
            }
        }
        entry.publish();
        if (snapshot?.polling_required) entry.schedule(snapshot.origin == null ? 0 : 2000);
        else if (items.some(active)) entry.schedule();
    }, []);

    const command = useCallback(async (item, requestSession, collection = false) => {
        const state = manager.current;
        if (!state || state.session !== requestSession || !requestSession.isCurrent()) return;
        const jobId = item.automatic_collection?.job?.id;
        const key = collection ? `job:${jobId}` : `candidate:${item.candidate_id}`;
        if (state.commands.has(key) || (collection && !jobId)) return;
        const entries = [...state.searches.entries()].filter(([id, entry]) =>
            id === item.search_id || (collection && entry.items.some(candidate =>
                candidate.automatic_collection?.job?.id === jobId)));
        const controller = new AbortController();
        state.commands.set(key, controller);
        const matches = candidate => collection ? candidate.automatic_collection?.job?.id === jobId :
            candidate.candidate_id === item.candidate_id;
        const mark = (entry, requesting, error = '', retryAt = 0) => {
            entry.items = entry.items.map(candidate => matches(candidate) ? {
                ...candidate,
                ...(collection ? { automatic_collection: { ...candidate.automatic_collection,
                    retrying: requesting, trackingError: error, trackingRetryAt: retryAt } } : { requesting, trackingError: error, trackingRetryAt: retryAt }),
            } : candidate);
            entry.publish();
        };
        for (const [, entry] of entries) {
            entry.invalidate();
            entry.busy += 1;
            mark(entry, true);
        }
        const alive = () => manager.current === state && requestSession.isCurrent();
        let errorMessage = '';
        let commandRetryAt = 0;
        const path = collection ? `/collector/collection-jobs/${jobId}/retry` :
                `/collector/repository-candidates/${item.candidate_id}/classify${item.classification_status === 'error' ? '?retry=true' : ''}`;
        try {
            await sendCommand(path, { session: requestSession, signal: controller.signal });
        } catch (error) {
            if (alive() && !isAbortError(error)) {
                errorMessage = error.message;
                commandRetryAt = error.retryAt ?? 0;
                if (!error.status || error.status >= 500) state.uncertain.set(path, {
                    searchId: item.search_id, candidateId: item.candidate_id, collection,
                    version: collection ? item.automatic_collection?.job?.updated_at : item.updated_at,
                });
                if (error.retryAt) for (const [, entry] of entries) entry.retryAt = error.retryAt;
            }
        } finally {
            state.commands.delete(key);
            if (alive()) for (const [, entry] of entries) {
                entry.busy -= 1;
                mark(entry, false, errorMessage, commandRetryAt);
                // A lost POST acknowledgement is ambiguous: read, never repost.
                entry.schedule(0);
            }
        }
    }, []);

    const pauseSearch = useCallback(id => {
        const entry = manager.current?.searches.get(id);
        if (!entry) return () => {};
        entry.invalidate();
        entry.busy += 1;
        return () => { entry.busy -= 1; entry.schedule(0); };
    }, []);

    const stopTracking = useCallback(() => {
        for (const entry of manager.current?.searches.values() ?? []) {
            entry.stopped = true;
            entry.invalidate();
        }
    }, []);

    const resumeTracking = useCallback(id => {
        const entry = manager.current?.searches.get(id);
        if (!entry || entry.unavailable) return;
        entry.stopped = false;
        entry.failures = 0;
        entry.error = '';
        entry.publish();
        entry.schedule(0);
    }, []);

    return { followSearch, pauseSearch, stopTracking, resumeTracking, analyze: command,
        retryCollection: (item, requestSession) => command(item, requestSession, true) };
}
