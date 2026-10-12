import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import CollectionDiagnostics from './CollectionDiagnostics.jsx';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function toggle(details, open) { details.open = open; fireEvent(details, new Event('toggle')); }
const job = { id: 12, updated_at: 'v1' };
const session = { token: 'test-private-token', mode: 'token', isCurrent: () => true };

it('distinguishes received metadata errors from browser service failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200,
        json: async () => ({ job_id: 12, method_attempts: [
            { id: 'api', method: 'dataverse_api', status: 'failed', http_status: 200,
                code: 'repository_metadata_invalid', failure_phase: 'normalize', resource_count: 0 },
            { id: 'browser', method: 'browser', status: 'failed', code: 'browser_navigation_failed',
                failure_phase: 'render', service_http_status: 503, resource_count: 0 },
        ] }) }));
    render(<CollectionDiagnostics job={job} session={session} />);
    toggle(screen.getByText('Collection details').closest('details'), true);
    expect(await screen.findByText(/Received metadata does not match the connector format/)).toHaveTextContent('HTTP 200');
    expect(screen.getByText(/Failed during metadata analysis/)).toBeInTheDocument();
    expect(screen.getByText(/Browser could not complete page navigation/)).toHaveTextContent('Browser service HTTP 503');
});

it('loads history only when opened, with the current authentication', async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({
        job_id: 12, coverage: { checked: 1, validated: 1, limited: true },
        method_attempts: [{ method: 'browser', status: 'succeeded', http_status: 200,
            checks: [{ format: 'CSV', status: 'available', http_status: 206 }] }],
    }) });
    vi.stubGlobal('fetch', fetch);
    render(<CollectionDiagnostics job={job} session={session} />);
    expect(fetch).not.toHaveBeenCalled();
    toggle(screen.getByText('Collection details').closest('details'), true);
    await screen.findByText('Browser with JavaScript');
    expect(fetch.mock.calls[0][0]).toContain('/collector/collection-jobs/12/diagnostics');
    expect(fetch.mock.calls[0][1].headers.Authorization).toBe('Bearer test-private-token');
    expect(screen.getByText(/Coverage limited/)).toBeInTheDocument();
    expect(screen.getByText(/CSV: available/)).toBeInTheDocument();
});

it('cancels a pending diagnostic read when the details close', async () => {
    const fetch = vi.fn(() => new Promise(() => {}));
    vi.stubGlobal('fetch', fetch);
    const { unmount } = render(<CollectionDiagnostics job={job} session={session} />);
    const details = screen.getByText('Collection details').closest('details');
    toggle(details, true);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    toggle(details, false);
    await waitFor(() => expect(fetch.mock.calls[0][1].signal.aborted).toBe(true));
    unmount();
});

it('reports missing historical evidence without implying success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200,
        json: async () => ({ job_id: 12, method_attempts: [] }) }));
    render(<CollectionDiagnostics job={job} session={session} />);
    toggle(screen.getByText('Collection details').closest('details'), true);
    expect(await screen.findByText('No method history was recorded for this collection.')).toBeInTheDocument();
});

it('shows the failed model attempt even after a successful retry', async () => {
    const attempts = [
        { run_id: 'run1', voter_id: 'apertus', model: 'Apertus Meditron', attempt: 1,
            status: 'error', error: 'dataset_signals must contain exactly reason and evidence.', evidence: 'live' },
        { run_id: 'run1', voter_id: 'apertus', model: 'Apertus Meditron', attempt: 2,
            status: 'succeeded', error: '', evidence: 'live' },
    ];
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200,
        json: async () => ({ job_id: 12, method_attempts: [], classification_history: { attempts } }) }));
    render(<CollectionDiagnostics job={job} session={session} />);
    toggle(screen.getByText('Collection details').closest('details'), true);
    expect(await screen.findByText('Model classification history')).toBeInTheDocument();
    expect(screen.getByText('dataset_signals must contain exactly reason and evidence.')).toBeInTheDocument();
    expect(screen.getByText(/attempt 1 · error/)).toBeInTheDocument();
    expect(screen.getByText(/attempt 2 · succeeded/)).toBeInTheDocument();
});
