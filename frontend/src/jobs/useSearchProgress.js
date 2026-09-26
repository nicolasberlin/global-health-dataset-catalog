import { useCallback, useEffect, useRef } from 'react';

import { isAbortError, requestJson } from '../api/client.js';

const active = item => ['queued', 'classifying'].includes(item.classification_status) ||
    ['pending', 'running'].includes(item.automatic_collection?.state);

function validate(data, id, expectedIds) {
    if (data?.search_id !== id || typeof data.polling_required !== 'boolean' ||
        !Array.isArray(data.items)) throw new Error('The search progress response is incomplete.');
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
        const state = { session, searches: new Map(), notified: new Set(), commands: new Map() };
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

    const followSearch = useCallback((id, items, requestSession) => {
        const state = manager.current;
        if (!state || state.session !== requestSession || !requestSession.isCurrent()) return;
        const previous = state.searches.get(id);
        if (previous) {
            previous.publish();
            // Restoring a stopped search must discover a retry made elsewhere.
            if (!previous.timer) previous.schedule(0);
            return;
        }
        const entry = { items, failures: 0, retryAt: 0, generation: 0, timer: null,
            controller: null, busy: 0, unavailable: false, error: '' };
        state.searches.set(id, entry);
        const alive = () => manager.current === state && requestSession.isCurrent();
        entry.invalidate = () => {
            entry.generation += 1;
            window.clearTimeout(entry.timer);
            entry.timer = null;
            entry.controller?.abort();
            entry.controller = null;
        };
        entry.publish = () => {
            if (!alive()) return;
            callbacks.current.onUpdate(id, entry.items.map(item => item.automatic_collection ? {
                ...item, automatic_collection: { ...item.automatic_collection,
                    tracking: entry.error ? (entry.unavailable ? 'unavailable' : 'retrying') : 'current',
                    trackingError: item.automatic_collection.trackingError || entry.error,
                },
            } : item), requestSession, entry.error);
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
            if (!alive() || entry.busy || entry.unavailable || entry.controller) return;
            entry.timer = window.setTimeout(poll, Math.max(delay, entry.retryAt - Date.now()));
        };
        async function poll() {
            entry.timer = null;
            if (!alive() || entry.busy || entry.unavailable || entry.controller) return;
            const generation = entry.generation;
            const controller = new AbortController();
            entry.controller = controller;
            const current = () => alive() && generation === entry.generation;
            let next = false;
            try {
                const data = validate(await requestJson(`/collector/searches/${id}/progress`, {
                    session: requestSession, signal: controller.signal,
                }), id, new Set(entry.items.map(item => item.candidate_id)));
                if (!current()) return;
                entry.items = data.items;
                entry.error = '';
                entry.failures = 0;
                entry.retryAt = 0;
                entry.publish();
                next = data.polling_required;
            } catch (error) {
                if (!current() || isAbortError(error)) return;
                entry.failures = Math.min(entry.failures + 1, 4);
                entry.retryAt = error.retryAt ?? 0;
                entry.error = error.message;
                entry.unavailable = [401, 403, 404].includes(error.status);
                entry.publish();
                next = !entry.unavailable;
            } finally {
                if (current()) {
                    entry.controller = null;
                    if (next) entry.schedule(Math.min(2000 * 2 ** entry.failures, 30000));
                }
            }
        }
        entry.publish();
        if (items.some(active)) entry.schedule();
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
        const mark = (entry, requesting, error = '') => {
            entry.items = entry.items.map(candidate => matches(candidate) ? {
                ...candidate,
                ...(collection ? { automatic_collection: { ...candidate.automatic_collection,
                    retrying: requesting, trackingError: error } } : { requesting, trackingError: error }),
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
        try {
            const path = collection ? `/collector/collection-jobs/${jobId}/retry` :
                `/collector/repository-candidates/${item.candidate_id}/classify${item.classification_status === 'error' ? '?retry=true' : ''}`;
            await requestJson(path, { method: 'POST', session: requestSession, signal: controller.signal });
        } catch (error) {
            if (alive() && !isAbortError(error)) errorMessage = error.message;
        } finally {
            state.commands.delete(key);
            if (alive()) for (const [, entry] of entries) {
                entry.busy -= 1;
                mark(entry, false, errorMessage);
                // A lost POST acknowledgement is ambiguous: read, never repost.
                entry.schedule(0);
            }
        }
    }, []);

    return { followSearch, analyze: command,
        retryCollection: (item, requestSession) => command(item, requestSession, true) };
}
