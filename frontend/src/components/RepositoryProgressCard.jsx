function getHostname(url) {
    try {
        return new URL(url).hostname;
    } catch {
        return url;
    }
}

export default function RepositoryProgressCard({ candidate }) {
    const { item, status } = candidate;

    return (
        <article className="repository-card repository-card--progress">
            <div className="repository-card__top">
                <span className="repository-source-pill">{item.source}</span>
                <span
                    className={`repository-status-pill repository-status-pill--${status}`}
                    role="status"
                >
                    {status === 'classifying' ? 'AI analysis…' : 'Waiting'}
                </span>
            </div>
            <h3>{item.title}</h3>
            <p>{item.description || 'Description unavailable.'}</p>
            <div className="repository-card__footer">
                <span>{item.publisher || getHostname(item.url)}</span>
                {item.date ? <small>{item.date}</small> : null}
            </div>
        </article>
    );
}
