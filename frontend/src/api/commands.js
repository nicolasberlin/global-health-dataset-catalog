import { requestJson } from './client.js';

// Only uncertain commands survive a failed request, scoped to the live owner.
// No access token or model credential is persisted in browser storage.
const pending = new WeakMap();
export function forgetCommand(session, path, body) {
    pending.get(session)?.delete(JSON.stringify([path, body ?? null]));
}
export async function sendCommand(path, { session, body, signal, validate } = {}) {
    let commands = pending.get(session);
    if (!commands) { commands = new Map(); pending.set(session, commands); }
    const identity = JSON.stringify([path, body ?? null]);
    const existing = commands.get(identity);
    const key = existing ?? (crypto.randomUUID?.() ??
        [...crypto.getRandomValues(new Uint8Array(16))]
            .map(value => value.toString(16).padStart(2, '0')).join(''));
    commands.set(identity, key);
    try {
        const result = await requestJson(path, {
            method: 'POST', session, signal,
            headers: { 'Idempotency-Key': key, ...(body ? { 'Content-Type': 'application/json' } : {}) },
            ...(body ? { body: JSON.stringify(body) } : {}),
        });
        validate?.(result);
        commands.delete(identity);
        return result;
    } catch (error) {
        // Network/5xx failures may follow a successful commit. An explicit retry
        // must replay the original key, even if a later replay is rate limited.
        // A first definitive rejection has no admitted command to recover.
        if (!existing && error.status >= 400 && error.status < 500) commands.delete(identity);
        throw error;
    }
}
