import LocalDatasetSearchCard from './LocalDatasetSearchCard.jsx';

export default function CollectedDatasetsSection({
    collectedDatasets,
    collectedError,
    collectedLoading,
    loadCollectedDatasets,
}) {
    return (
        <section className="collected-section" aria-label="Dataset catalog">
            <div className="section-heading">
                <div>
                    <h2>Catalog</h2>
                    <p>Browse saved datasets and access their data files.</p>
                </div>
                <button type="button" className="secondary-button"
                    onClick={() => loadCollectedDatasets()} disabled={collectedLoading}>
                    {collectedLoading ? 'Loading…' : 'Refresh'}
                </button>
            </div>
            {collectedError ? (
                <article className="empty-card empty-card--error" role="alert">
                    <h3>Unable to load the catalog</h3>
                    <p>{collectedError}</p>
                </article>
            ) : collectedLoading ? (
                <article className="empty-card empty-card--loading" role="status">
                    <h3>Loading the catalog</h3>
                </article>
            ) : collectedDatasets.length === 0 ? (
                <article className="empty-card">
                    <h3>No datasets in the catalog yet</h3>
                    <p>Run a search. Accepted datasets with validated links are added automatically.</p>
                </article>
            ) : (
                <>
                    <p>{collectedDatasets.length} dataset{collectedDatasets.length === 1 ? '' : 's'}</p>
                    <div className="repository-result-grid">
                        {collectedDatasets.map(dataset => (
                            <LocalDatasetSearchCard key={dataset.dataset_url} item={dataset} />
                        ))}
                    </div>
                </>
            )}
        </section>
    );
}
