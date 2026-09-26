import { StrictMode } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import App from './App.jsx';

const reply = (status, payload) => new Response(status === 204 ? null : JSON.stringify(payload), { status });
const calls = path => fetch.mock.calls.filter(([url]) => String(url).endsWith(path));
function installApi(search = () => reply(200, { origin: 'database', search_id: 'search', items: [] })) {
    vi.stubGlobal('fetch', vi.fn(async url => {
        if (url.endsWith('/session')) return reply(204);
        if (url.endsWith('/repository-analyses/latest')) return reply(404, { detail: 'None' });
        if (url.endsWith('/collected-datasets')) return reply(200, { items: [] });
        if (url.endsWith('/search-datasets')) return search();
        throw new Error(`Unexpected request ${url}`);
    }));
}
beforeEach(() => {
    vi.stubEnv('VITE_API_AUTH_MODE', 'public');
    vi.stubEnv('VITE_API_BASE_URL', '/ai-commons/api');
    window.sessionStorage.setItem('global-health-api-token', 'stale-token');
});
afterEach(() => {
    cleanup(); vi.unstubAllEnvs(); vi.unstubAllGlobals(); window.sessionStorage.clear();
});

it('bootstraps once in StrictMode and searches without using a stored token', async () => {
    installApi();
    render(<StrictMode><App /></StrictMode>);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Search', exact: true })).toBeEnabled());
    expect(calls('/session')).toHaveLength(1);
    fireEvent.change(screen.getByLabelText('Search for a health dataset'), { target: { value: 'malaria' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search', exact: true }));
    await waitFor(() => expect(calls('/search-datasets')).toHaveLength(1));
    for (const [, options] of fetch.mock.calls) {
        expect(new Headers(options.headers).has('Authorization')).toBe(false);
        expect(options.credentials).toBe('same-origin');
    }
});

it('keeps the catalog usable while session preparation is pending', async () => {
    installApi();
    const original = fetch.getMockImplementation();
    let finish;
    const pending = new Promise(resolve => { finish = resolve; });
    fetch.mockImplementation(url => url.endsWith('/session') ? pending : original(url));
    render(<App />);
    expect(screen.getByRole('button', { name: 'Search', exact: true })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Catalog', exact: true }));
    await waitFor(() => expect(calls('/collected-datasets')).toHaveLength(1));
    expect(calls('/repository-analyses/latest')).toHaveLength(0);
    await act(async () => { finish(reply(204)); });
});

it('stops on expiration and requires an explicit new search after reconnecting', async () => {
    installApi(() => reply(401, { detail: 'Expired' }));
    render(<App />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Search', exact: true })).toBeEnabled());
    fireEvent.change(screen.getByLabelText('Search for a health dataset'), { target: { value: 'malaria' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search', exact: true }));
    await screen.findByRole('button', { name: 'Continue' });
    expect(calls('/session')).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Search', exact: true })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Search', exact: true })).toBeEnabled());
    expect(calls('/session')).toHaveLength(2);
    expect(calls('/search-datasets')).toHaveLength(1);
    expect(screen.getByLabelText('Search for a health dataset')).toHaveValue('malaria');
});

it('shows bootstrap failure and retries only on request', async () => {
    installApi();
    fetch.mockRejectedValueOnce(new TypeError('Network unavailable'));
    render(<App />);
    await screen.findByRole('button', { name: 'Retry access' });
    expect(calls('/session')).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Retry access' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Search', exact: true })).toBeEnabled());
    expect(calls('/session')).toHaveLength(2);
});

it('follows an online candidate through authenticated polling without posting classification', async () => {
    const candidate = { candidate_id: 'candidate', search_id: 'search', title: 'Malaria candidate',
        classification_status: 'queued', url: 'https://example.org/data', source: 'Test' };
    installApi(() => reply(200, { origin: 'online', search_id: 'search', items: [candidate] }));
    const original = fetch.getMockImplementation();
    fetch.mockImplementation(url => url.endsWith('/searches/search/progress')
        ? reply(200, { search_id: 'search', polling_required: false, items: [{ ...candidate, classification_status: 'accepted',
            classification: { accepted: true, ensemble: {} },
            automatic_collection: { state: 'saved', job: { id: 42, status: 'done', saved_count: 1 } } }] })
        : original(url));
    render(<App />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Search', exact: true })).toBeEnabled());
    fireEvent.change(screen.getByLabelText('Search for a health dataset'), { target: { value: 'malaria' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search', exact: true }));
    await screen.findByText('Dataset saved to the local catalog', {}, { timeout: 3000 });
    expect(calls('/searches/search/progress')).toHaveLength(1);
    expect(calls('/classify')).toHaveLength(0);
    expect(calls('/session')).toHaveLength(1);
});
