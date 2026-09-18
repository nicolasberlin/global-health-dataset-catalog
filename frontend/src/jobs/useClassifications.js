import { useCallback, useEffect, useRef } from 'react';

import { isAbortError, requestJson } from '../api/client.js';

const active = item => ['queued', 'classifying'].includes(item.classification_status);

function validate(item, expected) {
    if (item?.candidate_id !== expected.candidate_id || item.search_id !== expected.search_id) {
        throw new Error('The classification response no longer matches this search.');
    }
    if (!['pending', 'queued', 'classifying', 'accepted', 'rejected', 'error'].includes(item.classification_status)) {
        throw new Error('The classification response is incomplete.');
    }
    if (['accepted', 'rejected'].includes(item.classification_status) &&
        typeof item.classification?.accepted !== 'boolean') {
        throw new Error('The classification response is incomplete.');
    }
    if (item.classification_status === 'accepted' && !item.automatic_collection) {
        throw new Error('The automatic collection response is incomplete.');
    }
    return item;
}

// Tracking belongs to the authenticated session, independently of the visible search.
export function useClassifications(session, onUpdate) {
    const callback = useRef(onUpdate);
    callback.current = onUpdate;
    const manager = useRef(null);
    useEffect(() => {
        const state = { session, trackers: new Map() };
        manager.current = state;
        return () => {
            manager.current = null;
            for (const tracker of state.trackers.values()) {
                window.clearTimeout(tracker.timer);
                tracker.controller.abort();
            }
        };
    }, [session]);

    const follow = useCallback(async (item, requestSession, { submit = false, retry = false } = {}) => {
        const state = manager.current;
        if (!state || state.session !== requestSession || !requestSession.isCurrent()) return;
        const id = item.candidate_id;
        // At most one request/poll loop per candidate. An explicit retry follows a terminal error.
        if (state.trackers.has(id)) return;
        const tracker = { controller: new AbortController(), timer: null, failures: 0 };
        state.trackers.set(id, tracker);
        const alive = () => manager.current === state && requestSession.isCurrent() &&
            state.trackers.get(id) === tracker;
        const options = { session: requestSession, signal: tracker.controller.signal };
        const publish = (next, trackingError = '', requesting = false) => {
            if (!alive()) return;
            item = next;
            callback.current(next, requestSession, trackingError, requesting);
        };
        const finish = () => state.trackers.delete(id);
        const schedule = () => {
            if (alive()) tracker.timer = window.setTimeout(poll, Math.min(700 * 2 ** tracker.failures, 15000));
        };
        async function poll() {
            if (!alive()) return;
            try {
                const result = validate(await requestJson(`/collector/repository-candidates/${id}`, options), item);
                publish(result);
                tracker.failures = 0;
                if (!active(result)) { finish(); return; }
            } catch (error) {
                if (!alive() || isAbortError(error)) return;
                tracker.failures = Math.min(tracker.failures + 1, 5);
                publish(item, error.message);
                if ([401, 403, 404].includes(error.status)) { finish(); return; }
            }
            schedule();
        }
        if (!submit) {
            publish(item);
            if (active(item)) schedule();
            else finish();
            return;
        }
        publish(item, '', true);
        try {
            const result = validate(await requestJson(
                `/collector/repository-candidates/${id}/classify${retry ? '?retry=true' : ''}`,
                { ...options, method: 'POST' },
            ), item);
            publish(result);
            if (active(result)) schedule();
            else finish();
        } catch (error) {
            if (!alive() || isAbortError(error)) return;
            publish(item, error.message);
            // A lost acknowledgement is ambiguous. Read the persisted state; never repost automatically.
            if ([401, 403, 404, 422, 429].includes(error.status)) finish();
            else schedule();
        }
    }, []);
    return { follow };
}
