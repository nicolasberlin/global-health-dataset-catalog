import ClassificationProgress from './ClassificationProgress.jsx';

function getHostname(url) {
    try {
        return new URL(url).hostname;
    } catch {
        return url;
    }
}

export default function RepositoryProgressCard({ candidate, onAnalyze }) {
    const { item, status } = candidate;

    return (
        <article className="repository-card repository-card--progress">
            <div className="repository-card__top">
                <span className="repository-source-pill">{item.source}</span>
                <span
                    className={`repository-status-pill repository-status-pill--${status}`}
                    role="status"
                >
                    {candidate.requesting ? 'Requesting analysis…' : status === 'classifying' ? 'AI analysis…' : status === 'queued' ? 'Waiting' : 'Not requested'}
                </span>
            </div>
            <h3>{item.title}</h3>
            <ClassificationProgress progress={item.classification_progress} />
            {candidate.trackingError && <p role="status">Analysis tracking unavailable: {candidate.trackingError}</p>}
            {status === 'pending' && <button disabled={candidate.requesting} type="button" onClick={onAnalyze}>Analyze</button>}
            <p>{item.description || 'Description unavailable.'}</p>
            <div className="repository-card__footer">
                <span>{item.publisher || getHostname(item.url)}</span>
                {item.date ? <small>{item.date}</small> : null}
            </div>
        </article>
    );
}
