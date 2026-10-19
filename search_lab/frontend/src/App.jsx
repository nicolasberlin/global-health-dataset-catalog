import { useEffect, useMemo, useRef, useState } from 'react';
import { client, date, download } from './api.js';
import SearchHistory from './components/SearchHistory.jsx';
import SearchDetails from './components/SearchDetails.jsx';
import ComparisonView from './components/ComparisonView.jsx';

const emptyNotes = { label: '', expected_result: '', suspected_cause: '', change_tested: '', learned: '' };
export default function App() {
    const [mode, setMode] = useState(null);
    const [token, setToken] = useState('');
    const [tokenInput, setTokenInput] = useState('');
    const [selected, setSelected] = useState('');
    const [data, setData] = useState(null);
    const [candidateId, setCandidateId] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const [revision, setRevision] = useState(0);
    const [notes, setNotes] = useState(emptyNotes);
    const [snapshots, setSnapshots] = useState([]);
    const [capturing, setCapturing] = useState(false);
    const [message, setMessage] = useState('');
    const [sessionEpoch, setSessionEpoch] = useState(0);
    const api = useMemo(() => client(token), [token]);
    const currentApi = useRef(api);
    const workspace = useRef(null);
    currentApi.current = api;
    const candidate = data?.trace.summary.items?.find(item => item.candidate_id === candidateId) || data?.trace.summary.items?.[0];
    const ready = mode === 'local' || (mode === 'token' && Boolean(token));
    useEffect(() => { client()('/config').then(config => setMode(config.auth_mode)).catch(error => setError(error.message)); }, []);
    useEffect(() => {
        if (!ready) return;
        const controller = new AbortController();
        api('/snapshots', { signal: controller.signal }).then(data => { if (!controller.signal.aborted) setSnapshots(data.items); })
            .catch(error => { if (!controller.signal.aborted) setError(error.message); });
        return () => controller.abort();
    }, [api, ready]);
    useEffect(() => {
        if (!selected || !ready) return;
        const controller = new AbortController();
        setLoading(true); setError(''); setData(null);
        api(`/searches/${selected}`, { signal: controller.signal }).then(data => { if (!controller.signal.aborted) setData(data); })
            .catch(error => { if (!controller.signal.aborted) setError(error.message); })
            .finally(() => { if (!controller.signal.aborted) setLoading(false); });
        return () => controller.abort();
    }, [api, selected, revision, ready]);
    async function capture() {
        if (!candidate) return;
        const requestApi = api;
        setCapturing(true); setError(''); setMessage('');
        try {
            const snapshot = await api(`/searches/${selected}/snapshots`, { method: 'POST', body: JSON.stringify({ ...notes, candidate_id: candidate.candidate_id }) });
            if (currentApi.current !== requestApi) return;
            setMessage(`Candidate snapshot for ${snapshot.candidate.title} captured at ${date(snapshot.captured_at)}. Existing evidence was preserved.`);
            const list = await requestApi('/snapshots');
            if (currentApi.current !== requestApi) return;
            setSnapshots(list.items);
        } catch (error) { if (currentApi.current === requestApi) setError(error.message); }
        finally { if (currentApi.current === requestApi) setCapturing(false); }
    }
    async function downloadSnapshot(id) {
        const requestApi = api;
        try {
            const snapshot = await requestApi(`/snapshots/${id}`);
            if (currentApi.current === requestApi) download(snapshot);
        } catch (error) { if (currentApi.current === requestApi) setError(error.message); }
    }
    function clearSession() {
        setData(null); setCandidateId(''); setSelected(''); setSnapshots([]); setError('');
        setCapturing(false); setMessage(''); setNotes(emptyNotes);
        setSessionEpoch(value => value + 1);
    }
    return <>
        <header><div className="eyebrow">GLOBAL HEALTH · LOCAL RESEARCH TOOL</div><h1>Search laboratory</h1>
            <p>Inspect searches, understand failures, preserve evidence.</p><span className="badge">Observation mode · no collection is launched here</span></header>
        {mode === 'token' && <form className="token" onSubmit={event => { event.preventDefault(); setToken(tokenInput); clearSession(); }}>
            <label>API access token<input type="password" value={tokenInput} onChange={event => setTokenInput(event.target.value)} autoComplete="off" /></label><button>Connect</button>
            {token && <button type="button" onClick={() => { setToken(''); setTokenInput(''); clearSession(); }}>Disconnect</button>}
        </form>}
        {error && <p role="alert" className="error global-error">{error}</p>}
        {!mode && !error && <p>Connecting to the local laboratory…</p>}
        {ready && <main><SearchHistory key={sessionEpoch} api={api} selected={selected} onSelect={id => {
            setSelected(id); setCandidateId(''); setNotes(emptyNotes); setMessage('');
            requestAnimationFrame(() => workspace.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
        }} />
            <div className="workspace" ref={workspace}>
                {!selected && <section className="panel empty"><h2>Select a saved search</h2><p>Choose “External repositories” in the history to find the HIV collection attempts.</p><p>Opening a search reads existing evidence. It does not repeat the search or alter the catalog.</p></section>}
                {loading && <p role="status">Reading selected search…</p>}
                {data && <><SearchDetails key={selected} data={data} loading={loading} candidateId={candidateId} onCandidateChange={id => { setCandidateId(id); setNotes(emptyNotes); setMessage(''); }} onRefresh={() => setRevision(value => value + 1)} />
                    <section className="panel"><h2>Save this candidate for your report</h2><p>{candidate ? <>Only <strong>{candidate.title}</strong> and its recorded attempts will be saved.</> : 'Select an external search with a candidate to save evidence.'}</p>{candidate && <p><a href={candidate.url} target="_blank" rel="noreferrer">{candidate.url}</a></p>}<p>Each capture creates a new file and preserves older evidence.</p>
                        <div className="notes-grid">{Object.entries({ label: 'Snapshot label', expected_result: 'Expected result', suspected_cause: 'Suspected cause', change_tested: 'Change tested', learned: 'What I learned' }).map(([key, label]) => <label key={key}>{label}<textarea maxLength={key === 'label' ? 150 : 2000} value={notes[key]} onChange={event => setNotes(current => ({ ...current, [key]: event.target.value }))} /></label>)}</div>
                        <button disabled={capturing || !candidate} onClick={capture}>{capturing ? 'Saving…' : 'Save this candidate'}</button>{message && <p role="status">{message}</p>}
                    </section></>}
                <ComparisonView key={sessionEpoch} api={api} snapshots={snapshots} candidateUrl={candidate?.url} />
                {snapshots.length > 0 && <section className="panel"><h2>Saved evidence</h2><ul>{snapshots.map(item => <li key={item.id}>{item.scope === 'candidate' ? item.candidate.title : 'Whole search (older snapshot)'} · {item.label || item.query} · {date(item.captured_at)} <button className="small" onClick={() => downloadSnapshot(item.id)}>Download JSON</button></li>)}</ul></section>}
            </div></main>}
        <footer>Optional search laboratory · local evidence is stored with this tool.</footer>
    </>;
}
