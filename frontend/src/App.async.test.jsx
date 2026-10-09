import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import App from './App.jsx';
import { snapshot } from './test/searchApi.js';

const reply = (data, status = 200, headers = {}) => ({ ok: status < 400, status, headers: new Headers(headers), json: async () => data });
const tick = async (ms = 0) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
const state = overrides => snapshot({ search_id: 'search', query: 'malaria', origin: null,
    execution_status: 'queued', outcome: null, polling_required: true, items: [], ...overrides });
const accepted = { candidate_id: 'candidate', search_id: 'search', title: 'Health data',
    source: 'Test', url: 'https://example.org/data', classification_status: 'accepted',
    classification: { accepted: true, ensemble: { accepted_votes: 2, successful_votes: 3, failed_votes: 0 } },
    automatic_collection: { state: 'empty', outcome: 'incomplete', execution_status: 'finished',
        errors: [{ code: 'collection_budget_exhausted', message: 'Collection time budget exhausted.', recovery: 'manual' }],
        dataset_ids: [9], job: { id: 42, status: 'done', outcome: 'incomplete', saved_count: 1 } } };
const calls = path => fetch.mock.calls.filter(([url]) => String(url).endsWith(path));
function api(handler) {
    global.fetch = vi.fn(async (url, options) => {
        if (url.endsWith('/collected-datasets')) return reply({ items: [] });
        return handler(url, options);
    });
}
async function submit() {
    fireEvent.change(screen.getByLabelText('Search for a health dataset'), { target: { value: 'malaria' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search', exact: true }));
    await tick();
}
beforeEach(() => { vi.useFakeTimers(); sessionStorage.setItem('global-health-api-token', 'test'); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); sessionStorage.clear(); });

it('follows empty discovery and automatic retry snapshots, then stops on a confirmed empty result', async () => {
    let reads = 0;
    api(url => {
        if (url.endsWith('/latest')) return reply({}, 404);
        if (url.endsWith('/searches')) return reply({ search_id: 'search', attempt: 1 }, 202);
        return reply(++reads === 1 ? state({ execution_status: 'running' }) : reads === 2 ?
            state({ execution_status: 'waiting_retry', errors: [{ recovery: 'automatic', message: 'Temporary provider failure.' }] }) :
            state({ execution_status: 'finished', origin: 'online', polling_required: false, outcome: 'empty' }));
    });
    render(<App />); await tick(); await submit();
    expect(screen.getByText('Search in progress')).toBeVisible();
    expect(screen.queryByText('No datasets found')).not.toBeInTheDocument();
    await tick(2000);
    expect(screen.getByText('Waiting for an automatic retry')).toBeVisible();
    await tick(2000); expect(screen.getByText('No datasets found')).toBeVisible();
    await tick(20000); expect(reads).toBe(3);
});

it('replays a lost admission with the original key instead of creating another search', async () => {
    let posts = 0;
    api((url, options) => {
        if (url.endsWith('/latest')) return reply({}, 404);
        if (url.endsWith('/searches')) {
            if (++posts === 1) throw new TypeError('Connection lost');
            return reply({ search_id: 'search', attempt: 1 });
        }
        return reply(state({ outcome: 'empty', execution_status: 'finished', polling_required: false }));
    });
    render(<App />); await tick(); await submit(); await submit();
    const requests = calls('/searches');
    expect(requests).toHaveLength(2);
    expect(requests[0][1].headers['idempotency-key']).toBe(requests[1][1].headers['idempotency-key']);
    expect(requests[0][1].headers['idempotency-key']).toBeTruthy();
});

it('restores local results in server order without submitting any work', async () => {
    api(url => url.endsWith('/latest') ? reply({ ...state({ origin: 'database', execution_status: 'finished',
        outcome: 'results', polling_required: false }), local_dataset_ids: [9, 2], dataset_ids: [9, 2] }) :
        reply({ items: [{ id: 2, title: 'Second dataset', dataset_url: 'https://example.org/2' },
            { id: 9, title: 'First dataset', dataset_url: 'https://example.org/9' }] }));
    render(<App />); await tick();
    const cards = screen.getAllByRole('heading', { level: 3 });
    expect(cards.map(card => card.textContent).slice(0, 2)).toEqual(['First dataset', 'Second dataset']);
    expect(fetch.mock.calls.some(([, options]) => options.method === 'POST')).toBe(false);
});

it('keeps partial datasets visible and retries the incomplete collection, never discovery', async () => {
    api((url, options) => {
        if (url.includes('/by-id?')) return reply({ items: [{ id: 9, title: 'Saved result', dataset_url: 'https://example.org/data' }] });
        if (options.method === 'POST') return reply({ job: { id: 42, status: 'pending' } }, 202);
        return reply(state({ origin: 'online', execution_status: 'finished', outcome: 'incomplete',
            polling_required: false, items: [accepted], dataset_ids: [9] }));
    });
    render(<App />); await tick();
    expect(screen.getByText('Search incomplete')).toBeVisible();
    expect(screen.getByText('Collection incomplete')).toBeVisible();
    expect(screen.getByRole('link', { name: 'Open saved dataset page' })).toBeVisible();
    expect(screen.queryByText('No dataset was accepted for this search.')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry search' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry collection' })); await tick();
    expect(calls('/collection-jobs/42/retry')).toHaveLength(1);
    expect(calls('/collection-jobs/42/retry')[0][1].headers['idempotency-key']).toBeTruthy();
});

it('restores failed discovery and respects a server retry deadline before resubmission', async () => {
    const errors = [{ recovery: 'manual', message: 'Provider unavailable.' }];
    api((url, options) => options.method === 'POST' ? reply({ detail: 'Wait' }, 429, { 'Retry-After': '10' }) :
        reply(state({ execution_status: 'failed', outcome: 'incomplete', polling_required: false, errors })));
    render(<App />); await tick();
    fireEvent.click(screen.getByRole('button', { name: 'Retry search' })); await tick();
    expect(screen.getByText(/Wait Please wait/)).toBeVisible();
    expect(screen.getByRole('button', { name: /Retry after/ })).toBeDisabled();
    await tick(10050);
    expect(screen.getByRole('button', { name: 'Retry search' })).toBeEnabled();
    expect(calls('/searches/search/retry')).toHaveLength(1);
});


it('offers tracking resumption after three failures without resubmitting work', async () => {
    let failing = true;
    api(url => {
        if (url.endsWith('/latest')) return reply({}, 404);
        if (url.endsWith('/searches')) return reply({ search_id: 'search', attempt: 1 }, 202);
        if (failing) throw new TypeError('Load failed');
        return reply(state({ execution_status: 'finished', polling_required: false, outcome: 'empty' }));
    });
    render(<App />); await tick(); await submit();
    await tick(4000); await tick(8000);
    expect(screen.getByText('Tracking stopped — collection status unknown')).toBeVisible();
    await tick(60000);
    expect(calls('/searches/search/progress')).toHaveLength(3);
    failing = false;
    fireEvent.click(screen.getByRole('button', { name: 'Resume tracking' })); await tick();
    expect(screen.getByText('No datasets found')).toBeVisible();
    expect(calls('/searches')).toHaveLength(1);
    expect(calls('/searches/search/progress')).toHaveLength(4);
    expect(screen.queryByRole('button', { name: 'Resume tracking' })).not.toBeInTheDocument();
});

it('stops polling the previous search when submitting a new query', async () => {
    let posts = 0;
    api(url => {
        if (url.endsWith('/latest')) return reply({}, 404);
        if (url.endsWith('/searches')) return reply({ search_id: ++posts === 1 ? 'old' : 'new', attempt: 1 }, 202);
        return reply(state({ search_id: url.includes('/old/') ? 'old' : 'new', execution_status: 'running' }));
    });
    render(<App />); await tick(); await submit();
    const previousReads = calls('/searches/old/progress').length;
    fireEvent.change(screen.getByLabelText('Search for a health dataset'), { target: { value: 'HIV' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search', exact: true })); await tick();
    act(() => document.dispatchEvent(new Event('visibilitychange')));
    await tick(10000);
    expect(calls('/searches/old/progress')).toHaveLength(previousReads);
    expect(calls('/searches/new/progress').length).toBeGreaterThan(1);
});
