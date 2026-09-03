function getHostname(url) {
    try {
        return new URL(url).hostname;
    } catch {
        return url;
    }
}

export default function LocalDatasetSearchCard({ item }) {
    return (
        <article className="repository-card repository-card--accepted">
            <div className="repository-card__top">
                <span className="repository-source-pill">
                    {item.hosting_platform || 'Catalogue local'}
                </span>
                <span className="repository-status-pill repository-status-pill--local">
                    Déjà dans la base
                </span>
            </div>

            <h3>{item.title}</h3>
            <p>{item.description || 'Description non disponible.'}</p>

            {(item.publisher || item.geography?.length > 0) && (
                <dl className="repository-facts">
                    {item.publisher ? (
                        <div>
                            <dt>Publisher</dt>
                            <dd>{item.publisher}</dd>
                        </div>
                    ) : null}
                    {item.geography?.length > 0 ? (
                        <div>
                            <dt>Géographie</dt>
                            <dd>{item.geography.join(', ')}</dd>
                        </div>
                    ) : null}
                </dl>
            )}

            <div className="repository-card__link-row">
                <span>{getHostname(item.dataset_url)}</span>
                <a href={item.dataset_url} target="_blank" rel="noreferrer">
                    Ouvrir le dataset
                </a>
            </div>
        </article>
    );
}
