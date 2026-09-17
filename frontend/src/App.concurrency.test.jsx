import { StrictMode } from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import App from './App.jsx';

const response = (payload) => ({ ok: true, status: 200, json: async () => payload });
const dataset = { id: 1, title: 'Saved malaria data', dataset_url: 'https://example.org/data', distributions: [] };
const candidate = (id = 'candidate-a') => ({
    candidate_id: id, search_id: 'search-a', title: `Malaria ${id}`,
    url: 'https://example.org/data', source: 'DataCite', classification_status: 'pending',
});
const accepted = (item, job = { id: 42, status: 'pending', saved_count: 0 }) => ({
    ...item, classification: { accepted: true, ensemble: {} },
    automatic_collection: { state: job.status, job },
});
function deferred() {
    let resolve;
    const promise = new Promise((done) => { resolve = done; });
    return { promise, resolve };
}
const advance = async (ms = 0) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
async function search(query) {
    fireEvent.change(screen.getByLabelText('Search for a health dataset'), { target: { value: query } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    await advance();
}
function installApi({ items = [candidate()], classify, poll, catalog } = {}) {
    global.fetch = vi.fn(async (input, options = {}) => {
        const url = String(input);
        if (url.endsWith('/collected-datasets')) return catalog?.() ?? response({ items: [] });
        if (url.endsWith('/search-datasets')) {
            const query = JSON.parse(options.body).query;
            return response(query === 'malaria'
                ? { search_id: 'search-a', origin: 'online', items }
                : { search_id: 'search-b', origin: 'database', items: [{ ...dataset, dataset_url: 'https://example.org/vaccination', title: 'Vaccination data' }] });
        }
        if (url.endsWith('/classify')) {
            const item = items.find((entry) => url.includes(`/${entry.candidate_id}/`));
            return classify?.(item, options) ?? response(accepted(item));
        }
        if (url.endsWith('/collection-jobs/42')) {
            return poll?.(options) ?? response({ job: { id: 42, status: 'done', saved_count: 1 } });
        }
        throw new Error(`Unexpected request ${url}`);
    });
}
const callsTo = (path) => global.fetch.mock.calls.filter(([url]) => String(url).endsWith(path));

beforeEach(() => {
    vi.useFakeTimers();
    window.sessionStorage.setItem('global-health-api-token', 'first-token');
});
afterEach(() => {
    cleanup();
    window.sessionStorage.clear();
    vi.restoreAllMocks();
    vi.useRealTimers();
});

it('tracks a shared job once across a new search and navigation, then refreshes the catalog', async () => {
    let saved = false;
    installApi({
        items: [candidate(), candidate('candidate-b')],
        poll: () => {
            saved = true;
            return response({ job: { id: 42, status: 'done', saved_count: 1 } });
        },
        catalog: () => response({ items: saved ? [dataset] : [] }),
    });
    render(<StrictMode><App /></StrictMode>);
    await advance(50);
    await search('malaria');
    expect(screen.getAllByText('Automatic collection pending')).toHaveLength(2);
    await search('vaccination');
    expect(screen.getByRole('heading', { name: 'Vaccination data' })).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Catalog' }));
    await advance(750);
    expect(callsTo('/collection-jobs/42')).toHaveLength(1);
    expect(callsTo('/collected-datasets')).toHaveLength(2);
    expect(screen.getByRole('heading', { name: dataset.title })).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Search datasets' }));
    expect(screen.getByRole('heading', { name: 'Vaccination data' })).toBeVisible();
    expect(screen.queryByText('Malaria candidate-a')).not.toBeInTheDocument();
});

it('registers a job from a late classification in the same session without replacing search B', async () => {
    const late = deferred();
    installApi({ classify: () => late.promise });
    render(<App />);
    await advance(50);
    await search('malaria');
    await search('vaccination');
    await act(async () => late.resolve(response(accepted(candidate()))));
    await advance(750);
    expect(callsTo('/collection-jobs/42')).toHaveLength(1);
    expect(callsTo('/collected-datasets')).toHaveLength(2);
    expect(screen.getByRole('heading', { name: 'Vaccination data' })).toBeVisible();
    expect(screen.queryByText('Malaria candidate-a')).not.toBeInTheDocument();
});

it('aborts a previous token session even during JSON parsing and ignores its job response', async () => {
    const lateBody = deferred();
    let classificationSignal;
    installApi({ classify: (_, options) => {
        classificationSignal = options.signal;
        return { ok: true, json: () => lateBody.promise };
    } });
    render(<App />);
    await advance(50);
    await search('malaria');
    fireEvent.change(screen.getByLabelText('API token'), { target: { value: 'second-token' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(classificationSignal.aborted).toBe(true);
    await search('vaccination');
    await act(async () => lateBody.resolve(accepted(candidate())));
    await advance(2000);
    expect(callsTo('/collection-jobs/42')).toHaveLength(0);
    expect(callsTo('/collected-datasets')).toHaveLength(1);
    expect(screen.getByRole('heading', { name: 'Vaccination data' })).toBeVisible();
    expect(callsTo('/search-datasets').at(-1)[1].headers.Authorization).toBe('Bearer second-token');
});

it('clears loading on logout and rejects a late search response', async () => {
    const late = deferred();
    global.fetch = vi.fn((url) => String(url).endsWith('/collected-datasets')
        ? Promise.resolve(response({ items: [] })) : late.promise);
    render(<App />);
    await search('malaria');
    const signal = callsTo('/search-datasets')[0][1].signal;
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
    expect(signal.aborted).toBe(true);
    expect(screen.getByRole('button', { name: 'Search' })).toBeEnabled();
    await act(async () => late.resolve(response({ search_id: 'search-a', origin: 'online', items: [candidate()] })));
    expect(screen.queryByText('Malaria candidate-a')).not.toBeInTheDocument();
    expect(callsTo('/classify')).toHaveLength(0);
});

it('aborts polling on logout and ignores its late completion', async () => {
    const late = deferred();
    let pollSignal;
    installApi({ poll: (options) => { pollSignal = options.signal; return late.promise; } });
    render(<App />);
    await advance(50);
    await search('malaria');
    await advance(700);
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
    expect(pollSignal.aborted).toBe(true);
    await act(async () => late.resolve(response({ job: { id: 42, status: 'done', saved_count: 1 } })));
    await advance(4000);
    expect(callsTo('/collection-jobs/42')).toHaveLength(1);
    expect(callsTo('/collected-datasets')).toHaveLength(1);
    expect(screen.queryByText('Malaria candidate-a')).not.toBeInTheDocument();
});

it('keeps the server status on tracking failure and recovers automatically', async () => {
    let polls = 0;
    installApi({ poll: () => {
        if (++polls === 1) throw new TypeError('Network offline');
        return response({ job: { id: 42, status: 'done', saved_count: 1 } });
    } });
    render(<App />);
    await search('malaria');
    await advance(700);
    expect(screen.getByText('Collection tracking temporarily unavailable')).toBeVisible();
    expect(screen.queryByText('Automatic collection failed')).not.toBeInTheDocument();
    await advance(3000);
    expect(screen.getByText('Dataset saved to the local catalog')).toBeVisible();
});

it('keeps catalog cards visible when refreshing fails', async () => {
    let reads = 0;
    installApi({ catalog: () => {
        if (++reads > 1) throw new TypeError('Network offline');
        return response({ items: [dataset] });
    } });
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: 'Catalog' }));
    await advance(50);
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    await advance(50);
    expect(screen.getByRole('heading', { name: dataset.title })).toBeVisible();
    expect(screen.getByRole('alert')).toHaveTextContent('Unable to load the catalog');
});
