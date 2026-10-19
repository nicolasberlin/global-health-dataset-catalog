import { useEffect, useRef, useState } from 'react';
import { date } from '../api.js';

export default function SearchHistory({ api, selected, onSelect }) {
    const [query, setQuery] = useState('');
    const [origin, setOrigin] = useState('');
    const [appliedQuery, setAppliedQuery] = useState('');
    const [items, setItems] = useState([]);
    const [cursor, setCursor] = useState(null);
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const [revision, setRevision] = useState(0);
    const generation = useRef(0);
    useEffect(() => {
        const version = ++generation.current;
        const controller = new AbortController();
        setLoading(true); setError(''); setCursor(null);
        const params = new URLSearchParams({ q: appliedQuery });
        if (origin) params.set('origin', origin);
        api(`/searches?${params}`, { signal: controller.signal }).then(data => {
            if (controller.signal.aborted || generation.current !== version) return;
            setItems(data.items); setCursor(data.next_cursor);
        }).catch(error => { if (!controller.signal.aborted) setError(error.message); })
            .finally(() => { if (!controller.signal.aborted) setLoading(false); });
        return () => { generation.current += 1; controller.abort(); };
    }, [api, origin, revision, appliedQuery]);
    async function older() {
        const version = generation.current;
        setLoading(true); setError('');
        try {
            const params = new URLSearchParams({ q: appliedQuery, cursor });
            if (origin) params.set('origin', origin);
            const data = await api(`/searches?${params}`);
            if (generation.current !== version) return;
            setItems(current => [...current, ...data.items]); setCursor(data.next_cursor);
        } catch (error) { if (generation.current === version) setError(error.message); }
        finally { if (generation.current === version) setLoading(false); }
    }
    return <aside className="history">
        <h2>Search history</h2>
        <form onSubmit={event => { event.preventDefault(); setAppliedQuery(query); setRevision(value => value + 1); }}>
            <label>Search text<input value={query} onChange={event => setQuery(event.target.value)} placeholder="HIV, malaria…" /></label>
            <label>Source<select value={origin} onChange={event => setOrigin(event.target.value)}>
                <option value="">All searches</option><option value="online">External repositories</option><option value="database">Local catalog</option>
            </select></label>
            <button disabled={loading}>{loading ? 'Loading…' : 'Refresh history'}</button>
        </form>
        {error && <p role="alert" className="error">{error}</p>}
        <p className="muted">Times shown in Europe/Zurich. Status is the current stored state.</p>
        <div className="history-list">{items.map(item => <button key={item.id} type="button"
            className={`history-item ${selected === item.id ? 'selected' : ''}`} onClick={() => onSelect(item.id)}>
            <strong>{item.query}</strong><span>{date(item.created_at)}</span>
            <span>{item.origin === 'online' ? 'External repositories' : 'Local catalog'} · {item.status}</span>
            <small>{item.candidate_count} candidates · search attempt {item.attempt_number}</small>
            <code>{item.id}</code>
        </button>)}</div>
        {!loading && !items.length && <p>No saved searches match this filter.</p>}
        {cursor && <button type="button" disabled={loading} onClick={older}>Load older searches</button>}
    </aside>;
}
