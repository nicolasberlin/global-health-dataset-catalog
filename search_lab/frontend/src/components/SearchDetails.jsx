import { date } from '../api.js';
import AttemptTimeline from './AttemptTimeline.jsx';

export default function SearchDetails({ data, onRefresh, loading, candidateId = '', onCandidateChange }) {
    const trace = data.trace;
    const items = trace.summary.items || [];
    const candidate = items.find(item => item.candidate_id === candidateId) || items[0];
    const job = candidate?.automatic_collection?.job;
    const collection = trace.collections.find(item => item?.job_id === job?.id);
    const modelAttempts = collection?.classification_history?.attempts || [];
    const candidateErrors = [...(candidate?.errors || []), ...(job?.errors || [])];
    const searchErrors = trace.summary.errors || [];
    return <><section className="panel">
        <div className="heading-row"><div><h2>{trace.context.query}</h2><code>{trace.context.search_id}</code></div>
            <button onClick={onRefresh} disabled={loading}>{loading ? 'Reading…' : 'Refresh selected search'}</button></div>
        <p>Whole search: {trace.summary.execution_status} · {trace.summary.outcome || 'No final outcome yet'} · Observed: {date(trace.exported_at)}</p>
        <p className="notice">{data.warning}</p>
        {items.length ? <>
            <label>Candidate<select value={candidate?.candidate_id || ''} onChange={event => onCandidateChange?.(event.target.value)}>
                {items.map(item => <option key={item.candidate_id} value={item.candidate_id}>{item.title}</option>)}
            </select></label>
            <h3>{candidate.title}</h3><p>{candidate.description}</p>
            <p><a href={candidate.url} target="_blank" rel="noreferrer">Open source page</a></p>
            <p>Relevance classification: <strong>{candidate.classification_status}</strong></p>
            {candidate.classification?.ensemble && <details><summary>Current saved relevance votes</summary><ul>{candidate.classification.ensemble.voters.map(vote => <li key={vote.voter_id}>{vote.voter_id} · {vote.relevance_label}<p>{vote.reason}</p></li>)}</ul></details>}
            <section aria-label="Selected candidate errors">
                <h3>Errors for this candidate</h3>
                {candidateErrors.length ? candidateErrors.map((error, index) => <p className="error" key={index}><code>{error.code}</code> · {error.message}</p>) : <p>No error is reported in the current candidate or collection job state. Earlier failures may appear in the dated attempts below.</p>}
            </section>
            {job ? <>
                <div className="current-result"><strong>Current collection job — selected candidate</strong><p>Job {job.id} · {job.execution_status} · {job.outcome || 'Pending conclusion'} · {job.saved_count} datasets saved</p>
                </div>
                <AttemptTimeline attempts={data.attempts.filter(attempt => attempt.job_id === job.id)} />
                {modelAttempts.length > 0 && <details><summary>Recorded page classification attempts</summary><ul>{modelAttempts.map((attempt, index) => <li key={index}>{attempt.model || attempt.voter_id} · attempt {attempt.attempt} · {attempt.status}{attempt.error && <p className="error">{attempt.error}</p>}</li>)}</ul></details>}
            </> : <p>No collection job is associated with this candidate.</p>}
        </> : <p>This search used the local catalog. {trace.summary.local_dataset_ids?.length || 0} local datasets are associated with it. Select an external search to inspect collection attempts.</p>}
    </section>
    <section className="panel" aria-label="Whole search diagnostics">
        <h2>Whole search diagnostics</h2>
        <p>These diagnostics cover the entire search, across its candidates and discovery steps. They do not establish an error for the selected candidate.</p>
        <details><summary>Errors reported for the whole search ({searchErrors.length})</summary>
            {searchErrors.length ? searchErrors.map((error, index) => <p className="error" key={index}><code>{error.code}</code> · {error.message}</p>) : <p>No error is reported for the whole search.</p>}
        </details>
        <details><summary>Limits of the recorded evidence</summary>
            <ul>{trace.export?.missing_evidence?.map(text => <li key={text}>{text}</li>)}</ul>
        </details>
    </section></>;
}
