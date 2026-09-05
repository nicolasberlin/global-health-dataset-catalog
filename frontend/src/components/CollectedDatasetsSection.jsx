function getHostname(url) {
    try {
        return new URL(url).hostname;
    } catch {
        return url;
    }
}

function formatCountries(countries) {
    const values = Array.isArray(countries) ? countries.filter(Boolean) : [];
    return values.length > 0 ? values.join(', ') : 'pays non detecte';
}

export default function CollectedDatasetsSection({
    collectedDatasets,
    collectedError,
    collectedLoading,
    loadCollectedDatasets,
}) {
    return (
        <section className="collected-section">
            <div className="section-heading">
                <div>
                    <h2>Datasets collectés</h2>
                    <p>
                        Résultats sauvegardés après classification santé et validation des fichiers.
                    </p>
                </div>
                <button
                    type="button"
                    className="secondary-button"
                    onClick={() => loadCollectedDatasets()}
                    disabled={collectedLoading}
                >
                    {collectedLoading ? 'Chargement...' : 'Actualiser'}
                </button>
            </div>

            {collectedError ? (
                <article className="empty-card empty-card--error">
                    <h3>Impossible de charger les datasets collectés</h3>
                    <p>{collectedError}</p>
                </article>
            ) : null}

            {!collectedError && collectedLoading ? (
                <article className="empty-card empty-card--loading">
                    <h3>Chargement des datasets collectés</h3>
                    <p>Lecture des résultats sauvegardés.</p>
                </article>
            ) : null}

            {!collectedError && !collectedLoading && collectedDatasets.length === 0 ? (
                <article className="empty-card">
                    <h3>Aucun dataset collecté</h3>
                    <p>Lance une collecte depuis une source pour remplir cette liste.</p>
                </article>
            ) : null}

            {!collectedError && !collectedLoading && collectedDatasets.length > 0 ? (
                <div className="dataset-grid">
                    {collectedDatasets.map((dataset) => (
                        <article className="dataset-card" key={dataset.dataset_url}>
                            <div className="dataset-card__meta">
                                <span className="theme-pill">
                                    {dataset.discovery_method || 'source'}
                                </span>
                            </div>
                            <h3>{dataset.title}</h3>
                            <p>{dataset.description || dataset.dataset_url}</p>

                            <div className="dataset-score-row">
                                <span>
                                    Fichiers
                                    <strong>{dataset.distributions?.length ?? 0}</strong>
                                </span>
                            </div>

                            <div className="dataset-card__source">
                                <div className="dataset-card__source-text">
                                    <span>
                                        {dataset.publisher || getHostname(dataset.dataset_url)}
                                    </span>
                                    <small>{formatCountries(dataset.geography)}</small>
                                </div>
                                <a href={dataset.dataset_url} target="_blank" rel="noreferrer">
                                    Page dataset
                                </a>
                            </div>

                            {dataset.distributions?.length > 0 ? (
                                <ul className="distribution-list distribution-list--compact">
                                    {dataset.distributions.slice(0, 4).map((distribution) => {
                                        const validation = dataset.validation_results?.find(
                                            (item) => item.url === distribution.url,
                                        );

                                        return (
                                            <li key={`${dataset.dataset_url}-${distribution.url}`}>
                                                <strong>{distribution.format}</strong>
                                                <span>{distribution.url}</span>
                                                <small>
                                                    {validation?.http_status
                                                        ? `HTTP ${validation.http_status}`
                                                        : 'validé'}
                                                    {validation?.size_bytes
                                                        ? ` · ${validation.size_bytes} bytes`
                                                        : ''}
                                                </small>
                                            </li>
                                        );
                                    })}
                                </ul>
                            ) : null}
                        </article>
                    ))}
                </div>
            ) : null}
        </section>
    );
}
