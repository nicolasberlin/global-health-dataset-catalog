function getHostname(url) {
    try {
        return new URL(url).hostname;
    } catch {
        return url;
    }
}

function formatCollectionMethods(methods) {
    const values = Array.isArray(methods) ? methods.filter(Boolean) : [];
    return values.length > 0 ? values.join(', ') : 'n/a';
}

export default function SourceCatalogSection({
    activeCollectionJob,
    apiBaseUrl,
    collectSource,
    collectingSourceId,
    collectionNotice,
    emptyState,
    error,
    filteredSources,
    loadSources,
    loading,
    searchTerm,
    selectedTheme,
    setSearchTerm,
    setSelectedTheme,
    sources,
    statusTone,
    themes,
}) {
    return (
        <section className="catalog-section">
            <div className="section-heading">
                <div>
                    <h2>Sources disponibles</h2>
                    <p>
                        {error
                            ? 'Le catalogue ne peut pas être lu pour le moment.'
                            : 'Catalogue local synchronisé depuis le backend FastAPI.'}
                    </p>
                </div>
            </div>

            <div className="catalog-toolbar">
                <div className="search-field">
                    <label htmlFor="source-search">Recherche</label>
                    <input
                        id="source-search"
                        type="search"
                        value={searchTerm}
                        onChange={(event) => setSearchTerm(event.target.value)}
                        placeholder="Nom, thème, source key, URL..."
                        disabled={loading || sources.length === 0}
                    />
                </div>
                <div className="filter-row">
                    <label htmlFor="theme-filter">Thème</label>
                    <select
                        id="theme-filter"
                        value={selectedTheme}
                        onChange={(event) => setSelectedTheme(event.target.value)}
                        disabled={loading || sources.length === 0}
                    >
                        {themes.map((theme) => (
                            <option key={theme} value={theme}>
                                {theme === 'All' ? 'Tous' : theme}
                            </option>
                        ))}
                    </select>
                </div>
                <span className="results-count">
                    {filteredSources.length} / {sources.length}
                </span>
            </div>

            <div className="source-grid">
                {filteredSources.length > 0 ? (
                    filteredSources.map((source) => (
                        <article className="source-card" key={source.id}>
                            <div className="source-card__meta">
                                <span className="theme-pill">{source.theme}</span>
                                <span className="source-key">{source.source_key}</span>
                            </div>
                            <h3>{source.name}</h3>
                            <p>{source.description}</p>
                            <div className="source-card__footer">
                                <span>{getHostname(source.page_url)}</span>
                                <div className="source-card__actions">
                                    <a
                                        className="source-link"
                                        href={`${apiBaseUrl}/sources/${source.id}/page`}
                                        target="_blank"
                                        rel="noreferrer"
                                    >
                                        Ouvrir
                                    </a>
                                    <button
                                        type="button"
                                        className="secondary-button source-action-button"
                                        onClick={() => collectSource(source)}
                                        disabled={collectingSourceId !== null}
                                    >
                                        {collectingSourceId === source.id
                                            ? 'Collecte...'
                                            : 'Collecter'}
                                    </button>
                                </div>
                            </div>
                        </article>
                    ))
                ) : (
                    <article className={`empty-card empty-card--${statusTone}`}>
                        <h3>{emptyState.title}</h3>
                        <p>{emptyState.description}</p>
                        {error ? (
                            <button type="button" onClick={loadSources}>
                                Réessayer
                            </button>
                        ) : null}
                    </article>
                )}
            </div>

            {collectionNotice ? (
                <article className={`collection-notice collection-notice--${collectionNotice.tone}`}>
                    <p>{collectionNotice.message}</p>
                    {activeCollectionJob ? (
                        <>
                            <small>
                                Statut: {activeCollectionJob.status} · méthodes:{' '}
                                {formatCollectionMethods(activeCollectionJob.discovery_methods)}
                            </small>
                            <div className="collection-notice__summary">
                                <span>
                                    <strong>{activeCollectionJob.discovered_count ?? 0}</strong>
                                    découvertes
                                </span>
                                <span>
                                    <strong>{activeCollectionJob.analyzed_count ?? 0}</strong>
                                    analysées
                                </span>
                                <span>
                                    <strong>{activeCollectionJob.accepted_count ?? 0}</strong>
                                    acceptées
                                </span>
                                <span>
                                    <strong>{activeCollectionJob.rejected_count ?? 0}</strong>
                                    rejetées
                                </span>
                                <span>
                                    <strong>
                                        {activeCollectionJob.invalid_distribution_count ?? 0}
                                    </strong>
                                    fichiers invalides
                                </span>
                                <span>
                                    <strong>{activeCollectionJob.saved_count ?? 0}</strong>
                                    sauvegardées
                                </span>
                            </div>
                        </>
                    ) : null}
                </article>
            ) : null}
        </section>
    );
}
