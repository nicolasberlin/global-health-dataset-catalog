import { date } from '../api.js';

const methods = { dataverse_api: 'Dataverse API', zenodo_api: 'Zenodo API', html: 'HTML', browser: 'Browser with JavaScript' };
export default function AttemptTimeline({ attempts }) {
    return <section>
        <h3>Collection attempts</h3>
        {!attempts.length && <p>No method history is available. Historical execution cannot be reconstructed.</p>}
        {attempts.map((attempt, index) => <details className="attempt" key={attempt.case_id} open={index === attempts.length - 1}>
            <summary>Attempt {index + 1} · {date(attempt.claim_version || attempt.methods[0]?.started_at)}
                {' · '}{attempt.methods.at(-1)?.status || 'Unknown'}</summary>
            <dl><dt>Case ID</dt><dd><code>{attempt.case_id}</code></dd>
                <dt>Previous case</dt><dd><code>{attempt.previous_case_id || 'None in available history'}</code></dd>
                <dt>Collection job</dt><dd>{attempt.job_id}</dd>
                <dt>Collector version</dt><dd>Unknown — not recorded for this execution</dd></dl>
            {attempt.history_truncated && <p className="notice">History was truncated. Earlier observations may be missing.</p>}
            <ol>{attempt.methods.map((step, stepIndex) => <li className="method" key={step.id || stepIndex}>
                <strong>{methods[step.method] || step.method}</strong>
                <span className={`badge ${step.status}`}>{step.status}</span>
                <p>{date(step.started_at)} → {date(step.finished_at)}</p>
                <p>Repository HTTP: {step.http_status ?? 'Unknown'} · Links found: {step.resource_count ?? 'Unknown'}</p>
                {step.service_http_status != null && <p>Browser service HTTP: {step.service_http_status}</p>}
                {step.code && <p className="error"><code>{step.code}</code>{step.failure_phase && ` · phase: ${step.failure_phase}`}<br />{step.reason || 'No detailed historical reason was recorded.'}</p>}
                {step.metadata_code && <p>Optional API metadata: <code>{step.metadata_code}</code> · HTTP {step.metadata_http_status ?? 'Unknown'}</p>}
                <ul>{(step.checks || []).map((check, index) => <li key={index}>{check.format || 'Unknown format'}: {check.status} · HTTP {check.http_status ?? 'Unknown'}</li>)}</ul>
            </li>)}</ol>
            <p className="muted">{attempt.checks_recorded} recorded checks · {attempt.available_checks} access checks passed. These method traces do not establish the historical catalog save count.</p>
        </details>)}
    </section>;
}
