import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import App from './App.jsx';

const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => data });
const candidate = (id, status = 'queued') => ({
    candidate_id: id, search_id: 'search-a', title: `Dataset ${id}`,
    url: 'https://example.org/data', source: 'DataCite', classification_status: status,
    classification_error: status === 'error' ? 'Candidate classification failed.' : '',
});
const accepted = item => ({
    ...item, classification_status: 'accepted', classification: { accepted: true, ensemble: {} },
    automatic_collection: { state: 'saved', job: { id: 42, status: 'done', saved_count: 1 } },
});
const analysis = items => ({ search_id: 'search-a', query: 'mortality', origin: 'online', items });
const advance = async (ms = 0) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
const calls = part => global.fetch.mock.calls.filter(([url]) => String(url).includes(part));
function api(handler) {
    global.fetch = vi.fn(async (input, options) => {
        const url = String(input);
        if (url.endsWith('/collected-datasets')) return response({ items: [] });
        return handler(url, options);
    });
}
function deferred() {
    let resolve;
    const promise = new Promise(done => { resolve = done; });
    return { promise, resolve };
}

beforeEach(() => {
    vi.useFakeTimers();
    window.sessionStorage.setItem('global-health-api-token', 'test-token');
});
afterEach(() => {
    cleanup();
    window.sessionStorage.clear();
    vi.restoreAllMocks();
    vi.useRealTimers();
});

it('restores queued work after reload without submitting discovered candidates', async () => {
    const queued = candidate('requested');
    const discovered = candidate('discovered', 'pending');
    let polls = 0;
    api(url => {
        if (url.endsWith('/repository-analyses/latest')) return response(analysis([queued, discovered]));
        if (url.endsWith('/repository-candidates/requested')) {
            return response(++polls === 1 ? { ...queued, classification_status: 'classifying' } : accepted(queued));
        }
        throw new Error(`Unexpected request ${url}`);
    });
    render(<App />);
    await advance(50);
    expect(screen.getByText('Waiting')).toBeVisible();
    expect(screen.getByText('Not requested')).toBeVisible();
    await advance(700);
    expect(screen.getByText('AI analysis…')).toBeVisible();
    await advance(750);
    expect(screen.getByText('Dataset saved to the local catalog')).toBeVisible();
    expect(screen.getByText('Not requested')).toBeVisible();
    expect(calls('/classify')).toHaveLength(0);
    expect(calls('/collected-datasets')).toHaveLength(2);
    expect(calls('/repository-analyses/latest')[0][1].headers.Authorization).toBe('Bearer test-token');
});

it('reads persisted state after a lost POST acknowledgement without reposting', async () => {
    const item = candidate('requested', 'pending');
    api(url => {
        if (url.endsWith('/repository-analyses/latest')) return response({ detail: 'None' }, 404);
        if (url.endsWith('/search-datasets')) return response(analysis([item]));
        if (url.endsWith('/classify')) throw new TypeError('Connection lost');
        if (url.endsWith('/repository-candidates/requested')) return response(accepted(item));
        throw new Error(`Unexpected request ${url}`);
    });
    render(<App />);
    await advance();
    fireEvent.change(screen.getByLabelText('Search for a health dataset'), { target: { value: 'mortality' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    await advance();
    fireEvent.click(screen.getByRole('button', { name: 'Analyze' }));
    await advance();
    expect(screen.getByText(/Analysis tracking unavailable/)).toBeVisible();
    await advance(700);
    expect(screen.getByText('Dataset saved to the local catalog')).toBeVisible();
    expect(calls('/classify')).toHaveLength(1);
    expect(calls('/repository-candidates/requested').filter(([, options]) => options.method !== 'POST')).toHaveLength(1);
});

it('only retries an interrupted classification after an explicit click', async () => {
    const item = candidate('interrupted', 'error');
    api(url => {
        if (url.endsWith('/repository-analyses/latest')) return response(analysis([item]));
        if (url.endsWith('/classify?retry=true')) return response({ ...item, classification_status: 'queued', classification_error: '' }, 202);
        if (url.endsWith('/repository-candidates/interrupted')) return response(accepted(item));
        throw new Error(`Unexpected request ${url}`);
    });
    render(<App />);
    await advance();
    expect(calls('/classify')).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: 'Retry analysis' }));
    await advance();
    expect(screen.getByText('Waiting')).toBeVisible();
    await advance(700);
    expect(screen.getByText('Dataset saved to the local catalog')).toBeVisible();
    expect(calls('/classify?retry=true')).toHaveLength(1);
});

it('ignores a late restored analysis after the user starts a new search', async () => {
    const late = deferred();
    api(url => {
        if (url.endsWith('/repository-analyses/latest')) return late.promise;
        if (url.endsWith('/search-datasets')) return response({ search_id: 'search-b', origin: 'database', items: [] });
        throw new Error(`Unexpected request ${url}`);
    });
    render(<App />);
    fireEvent.change(screen.getByLabelText('Search for a health dataset'), { target: { value: 'vaccination' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    await advance();
    await act(async () => late.resolve(response(analysis([candidate('old')]))));
    await advance(1000);
    expect(screen.queryByText('Dataset old')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Search for a health dataset')).toHaveValue('vaccination');
    expect(calls('/repository-candidates/')).toHaveLength(0);
});

it('aborts classification polling on unmount and ignores its late accepted result', async () => {
    const late = deferred();
    let signal;
    const item = candidate('requested');
    api((url, options) => {
        if (url.endsWith('/repository-analyses/latest')) return response(analysis([item]));
        if (url.endsWith('/repository-candidates/requested')) { signal = options.signal; return late.promise; }
        throw new Error(`Unexpected request ${url}`);
    });
    const { unmount } = render(<App />);
    await advance(750);
    unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => late.resolve(response(accepted(item))));
    await advance(3000);
    expect(screen.queryByText('Dataset requested')).not.toBeInTheDocument();
    expect(calls('/collected-datasets')).toHaveLength(1);
});

it('keeps tracking a queued classification across a new search without replacing its results', async () => {
    const item = candidate('requested');
    api(url => {
        if (url.endsWith('/repository-analyses/latest')) return response(analysis([item]));
        if (url.endsWith('/repository-candidates/requested')) return response(accepted(item));
        if (url.endsWith('/search-datasets')) return response({ search_id: 'search-b', origin: 'database', items: [] });
        throw new Error(`Unexpected request ${url}`);
    });
    render(<App />);
    await advance(50);
    fireEvent.change(screen.getByLabelText('Search for a health dataset'), { target: { value: 'vaccination' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    await advance(750);
    expect(screen.queryByText('Dataset requested')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Search for a health dataset')).toHaveValue('vaccination');
    expect(calls('/collected-datasets')).toHaveLength(2);
});

it('leaves the interface usable when restoring interrupts a search and no analysis exists', async () => {
    const late = deferred();
    let searchSignal;
    api((url, options) => {
        if (url.endsWith('/repository-analyses/latest')) return response({ detail: 'No previous analysis.' }, 404);
        if (url.endsWith('/search-datasets')) { searchSignal = options.signal; return late.promise; }
        throw new Error(`Unexpected request ${url}`);
    });
    render(<App />);
    await advance();
    fireEvent.change(screen.getByLabelText('Search for a health dataset'), { target: { value: 'mortality' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    await advance();
    fireEvent.click(screen.getByRole('button', { name: 'Restore last analysis' }));
    await advance();
    expect(searchSignal.aborted).toBe(true);
    expect(screen.getByRole('button', { name: 'Search' })).toBeEnabled();
    expect(screen.getByText(/Unable to restore/)).toBeVisible();
    await act(async () => late.resolve(response(analysis([candidate('obsolete')]))));
    expect(screen.queryByText('Dataset obsolete')).not.toBeInTheDocument();
});
