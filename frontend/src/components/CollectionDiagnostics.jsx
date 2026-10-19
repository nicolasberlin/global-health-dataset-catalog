import { useState } from 'react';
import useCollectionHistory from '../hooks/useCollectionHistory.js';

const names = { dataverse_api: 'Dataverse API', zenodo_api: 'Zenodo API', figshare_api: 'Figshare API', dryad_api: 'Dryad API', inveniordm_api: 'InvenioRDM API', dspace_api: 'DSpace API', html: 'HTML', browser: 'Browser with JavaScript' };
const reasons = {
    no_download_links: 'No downloadable links detected',
    verification_unconfirmed: 'Access could not be confirmed',
    access_restricted: 'Permission or authentication required',
    repository_unavailable: 'Repository request failed',
    repository_http_error: 'Repository returned an unsuccessful HTTP response',
    repository_network_error: 'Repository connection failed',
    repository_timeout: 'Repository request timed out',
    repository_invalid_json: 'Received response could not be read as JSON',
    repository_response_too_large: 'Repository response exceeded the size limit',
    repository_metadata_invalid: 'Received metadata does not match the connector format',
    browser_unavailable: 'Browser service unavailable',
    browser_invalid_response: 'Browser service returned an invalid response',
    browser_render_failed: 'Browser could not render the page',
    browser_navigation_failed: 'Browser could not complete page navigation',
    browser_worker_exited: 'Isolated browser process stopped before completion',
    collection_budget_exhausted: 'Collection time limit reached',
    page_rejected: 'Page rejected by dataset classification',
    resource_checks_failed: 'Detected resources did not pass validation',
    llm_invalid_response: 'The model did not return a valid classification',
    llm_timeout: 'The model request timed out',
    llm_network_error: 'The model could not be reached',
    llm_rate_limited: 'The model provider rate limit was reached',
    llm_unavailable: 'The model provider is unavailable',
    llm_configuration_error: 'The model configuration requires attention',
    processing_interrupted: 'Processing was interrupted',
    processing_failed: 'This step could not finish',
    browser_timeout: 'The browser operation timed out',
};
const phases = {
    fetch: 'request', decode: 'response decoding', normalize: 'metadata analysis',
    render: 'page rendering', classify: 'dataset classification', validate: 'resource verification',
    access: 'page access verification',
};
export default function CollectionDiagnostics({ job, session }) {
    const [open, setOpen] = useState(false);
    const { trace, error, loading, paging, loadEarlier } = useCollectionHistory(job, session, open);
    const coverage = trace?.coverage ?? job.coverage ?? {};
    const steps = trace?.method_attempts ?? job.method_attempts ?? [];
    return <details onToggle={event => setOpen(event.currentTarget.open)}>
        <summary>Collection details</summary>
        {coverage.checked != null && <p>Latest collection: {coverage.checked} resource check(s), {coverage.validated} validated.
            {coverage.limited ? ' Coverage limited by the configured resource policy.' : ' Exhaustive coverage is not guaranteed.'}</p>}
        {loading && <p role="status">Loading collection history…</p>}
        {error && <p role="alert">Unable to read collection history: {error}</p>}
        {trace?.history_truncated && <p>Earlier collection steps are available.</p>}
        {trace?.next_offset != null && <button type="button" disabled={paging}
            onClick={() => loadEarlier('methods')}>Load earlier collection steps</button>}
        {trace?.checks_truncated && <p>Some resource checks are omitted from this history page.</p>}
        {!loading && !error && !steps.length && <p>No method history was recorded for this collection.</p>}
        {!!steps.length && <ol>{steps.map((step, index) => <li key={step.id ?? index}>
            <strong>{names[step.method] ?? step.method}</strong>: {step.status}
            {step.http_status != null && ` · HTTP ${step.http_status}`}
            {step.request_attempts != null && ` · ${step.request_attempts} metadata request attempt(s)`}
            {step.code && ` · ${reasons[step.code] ?? 'This step could not finish'}`}
            {phases[step.failure_phase] && ` · Failed during ${phases[step.failure_phase]}`}
            {step.service_http_status != null && ` · Browser service HTTP ${step.service_http_status}`}
            {step.metadata_code && <p>Optional API metadata: {reasons[step.metadata_code] ?? 'Check could not finish'}
                {step.metadata_http_status != null && ` · HTTP ${step.metadata_http_status}`}.
                {' '}Rendered HTML was used as a fallback.</p>}
            {step.resource_count != null && ` · ${step.resource_count} resource link(s)`}
            {step.checks?.length > 0 && <ul>{step.checks.map((check, index) => <li key={index}>
                {check.format || 'Unknown format'}: {check.status}
                {check.http_status != null && ` · HTTP ${check.http_status}`}
            </li>)}</ul>}
        </li>)}</ol>}
        {trace?.classification_history?.attempts?.length > 0 && <>
            <h4>Model classification history</h4>
            {trace.classification_history.history_truncated && <p>Earlier model attempts are available.</p>}
            {trace.classification_history.next_offset != null && <button type="button" disabled={paging}
                onClick={() => loadEarlier('votes')}>Load earlier model attempts</button>}
            <ul>{trace.classification_history.attempts.map(attempt => <li key={`${attempt.run_id}:${attempt.voter_id}:${attempt.attempt}`}>
                <strong>{attempt.model || attempt.voter_id}</strong>: attempt {attempt.attempt} · {attempt.status}
                {attempt.started_at && ` · ${new Date(attempt.started_at).toLocaleString()}`}
                {attempt.errors?.map((diagnostic, index) => <p key={`${diagnostic.code}:${index}`}>
                    {diagnostic.message}
                </p>)}
                {attempt.evidence === 'legacy_snapshot' && <p>Historical snapshot: earlier attempts and start time are unavailable.</p>}
            </li>)}</ul>
        </>}
    </details>;
}
