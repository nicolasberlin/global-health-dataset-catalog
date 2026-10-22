import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, expect, it, vi } from 'vitest';
import { client, date } from './api.js';
import AttemptTimeline from './components/AttemptTimeline.jsx';
import SearchDetails from './components/SearchDetails.jsx';
import ComparisonView from './components/ComparisonView.jsx';

afterEach(() => vi.unstubAllGlobals());

it('reads local diagnostics without cookies or access tokens', async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [] }) });
    vi.stubGlobal('fetch', fetch);
    const controller = new AbortController();
    await client()('/searches?q=HIV', { signal: controller.signal });
    expect(fetch.mock.calls[0][0]).toBe('/lab/searches?q=HIV');
    expect(fetch.mock.calls[0][1]).toMatchObject({ credentials: 'omit', headers: {} });
    expect(fetch.mock.calls[0][1].signal).toBe(controller.signal);
});

it('exposes controlled authorization errors without treating them as empty history', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 403, json: async () => ({ detail: 'Local laboratory access only.' }) }));
    await expect(client()('/searches')).rejects.toThrow('Local laboratory access only.');
});

it('shows dated attempts with unknown code versions and distinguishes browser service HTTP', () => {
    const html = renderToStaticMarkup(<AttemptTimeline attempts={[{
        case_id: 'attempt-before', job_id: 44, claim_version: '2026-10-09T14:33:00Z', checks_recorded: 0, available_checks: 0,
        methods: [{ id: '1', method: 'browser', status: 'failed', service_http_status: 503,
            code: 'browser_worker_exited', failure_phase: 'render' }],
    }]} />);
    expect(html).toContain('Browser service HTTP: 503');
    expect(html).toContain('Repository HTTP: Unknown');
    expect(html).toContain('Unknown — not recorded for this execution');
    expect(html).toContain('do not establish the historical catalog save count');
});

it('local catalog history does not pretend to contain collection attempts', () => {
    const data = { warning: 'Current state only', trace: {
        context: { query: 'HIV', search_id: 'local' }, summary: { items: [], local_dataset_ids: [3, 6], execution_status: 'finished', outcome: 'results' },
        collections: [],
    } };
    const html = renderToStaticMarkup(<SearchDetails data={data} />);
    expect(html).toContain('This search used the local catalog.');
    expect(html).toContain('2 local datasets');
    expect(html).not.toContain('Attempt 1');
});

it('does not invent dates for missing evidence', () => {
    expect(date(null)).toBe('Unknown'); expect(date('invalid')).toBe('Unknown');
});

it('uses the actual saved relevance-vote shape without assuming nested classification', () => {
    const data = { warning: 'Current state only', attempts: [], trace: {
        context: { query: 'HIV', search_id: 'external' }, summary: { execution_status: 'finished', outcome: 'incomplete', items: [{ candidate_id: 'c1', title: 'Survey', url: 'https://example.org/file', classification_status: 'accepted', classification: { ensemble: { voters: [{ voter_id: 'model1', relevance_label: 'relevant', reason: 'Health survey.' }] } } }] }, collections: [],
    } };
    const html = renderToStaticMarkup(<SearchDetails data={data} />);
    expect(html).toContain('Health survey.'); expect(html).toContain('model1');
});

it.each([false, true])('keeps search errors separate from selected candidate errors (candidate failed: %s)', candidateFailed => {
    const globalError = { code: 'llm_invalid_response', message: 'A model response was invalid.' };
    const candidateError = { code: 'repository_request_failed', message: 'The selected repository request failed.' };
    const data = { warning: 'Current state only', attempts: [], trace: {
        context: { query: 'HIV', search_id: 'external' },
        summary: { execution_status: 'finished', outcome: 'incomplete', errors: [globalError], items: [{
            candidate_id: 'c1', title: 'Survey', url: 'https://example.org/file', classification_status: 'accepted',
            automatic_collection: { job: { id: 42, execution_status: 'finished', outcome: candidateFailed ? 'incomplete' : 'results', saved_count: candidateFailed ? 0 : 1, errors: candidateFailed ? [candidateError] : [] } },
        }] }, collections: [],
    } };
    const html = renderToStaticMarkup(<SearchDetails data={data} />);
    const [selected, global] = html.split('aria-label="Whole search diagnostics"');
    expect(selected).not.toContain('llm_invalid_response');
    expect(global).toContain('llm_invalid_response');
    expect(global).toContain('They do not establish an error for the selected candidate.');
    if (candidateFailed) expect(selected).toContain('repository_request_failed');
    else expect(selected).toContain('No error is reported in the current candidate or collection job state.');
});


it('comparison lists only snapshots of the selected candidate and excludes older whole searches', () => {
    const snapshots = [
        {id: 'one', scope: 'candidate', candidate: {url: 'https://example.org/file'}, label: 'Selected before'},
        {id: 'two', scope: 'candidate', candidate: {url: 'https://example.org/file'}, label: 'Selected after'},
        {id: 'other', scope: 'candidate', candidate: {url: 'https://example.org/other'}, label: 'Unrelated candidate'},
        {id: 'legacy', scope: 'search', label: 'Older whole search'},
    ];
    const html = renderToStaticMarkup(<ComparisonView snapshots={snapshots} candidateUrl="https://example.org/file" />);
    expect(html).toContain('Selected before'); expect(html).toContain('Selected after');
    expect(html).not.toContain('Unrelated candidate'); expect(html).not.toContain('Older whole search');
});
