import { useEffect, useRef, useState } from 'react';
import { date } from '../api.js';

export default function ComparisonView({ api, snapshots, candidateUrl }) {
    const [before, setBefore] = useState('');
    const [after, setAfter] = useState('');
    const [result, setResult] = useState(null);
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const generation = useRef(0);
    const eligible = snapshots.filter(item => item.scope === 'candidate' && item.candidate?.url === candidateUrl);
    useEffect(() => { generation.current += 1; setBefore(''); setAfter(''); setResult(null); setError(''); setLoading(false); }, [candidateUrl]);
    async function compare() {
        const version = ++generation.current;
        setLoading(true); setError(''); setResult(null);
        try { const value = await api(`/compare/${before}/${after}`); if (generation.current === version) setResult(value); }
        catch (error) { if (generation.current === version) setError(error.message); }
        finally { if (generation.current === version) setLoading(false); }
    }
    return <section className="panel">
        <h2>Compare this candidate before and after</h2><p>Only saved observations of the selected candidate are listed.</p>{eligible.length < 2 && <p>Save this candidate at two different times to compare its observations.</p>}
        <div className="comparison-controls">{[['Before', before, setBefore], ['After', after, setAfter]].map(([label, value, set]) => <label key={label}>{label}<select value={value} onChange={event => { generation.current += 1; set(event.target.value); setResult(null); setLoading(false); }}>
            <option value="">Select a snapshot</option>{eligible.map(item => <option key={item.id} value={item.id}>{item.label || item.query} · {date(item.captured_at)}</option>)}
        </select></label>)}<button onClick={compare} disabled={!before || !after || before === after || loading}>{loading ? 'Comparing…' : 'Compare'}</button></div>
        {error && <p role="alert" className="error">{error}</p>}
        {result && <><ul className="notice">{result.warnings.map(text => <li key={text}>{text}</li>)}</ul>
            <table><thead><tr><th>Candidate</th><th>Before</th><th>After</th></tr></thead><tbody>{result.items.map(item => <tr key={item.url}>
                <td>{item.after?.title || item.before?.title}</td>{['before', 'after'].map(side => <td key={side}>{item[side] ? <>{item[side].outcome || 'Unknown'}<br />Saved: {item[side].saved_count ?? 'Unknown'}<br />{item[side].errors.join(', ') || 'No job error reported'}</> : 'Not present in this snapshot'}</td>)}
            </tr>)}</tbody></table></>}
    </section>;
}
