import { useState } from 'react';
import LocalDatasetSearchCard from './LocalDatasetSearchCard.jsx';

export default function CollectedDatasetsSection({
    collectedDatasets,
    collectedError,
    collectedLoading,
    loadCollectedDatasets,
    loadMoreCollectedDatasets,
    collectedLoadingMore,
    nextCursor,
    catalogFilters,
    setCatalogFilters,
}) {
    const [filters, setFilters] = useState(catalogFilters);
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
            <form className="dataset-filters" onSubmit={event => {
                event.preventDefault(); setCatalogFilters({ ...filters });
            }}>
                <label>Catalog search<input type="search" maxLength={300} value={filters.query}
                    onChange={event => setFilters({ ...filters, query: event.target.value })} /></label>
                <label>Catalog country or area<input maxLength={200} value={filters.country}
                    placeholder="For example, France"
                    onChange={event => setFilters({ ...filters, country: event.target.value })} /></label>
                <label>Catalog format<input maxLength={100} value={filters.format} placeholder="For example, CSV"
                    onChange={event => setFilters({ ...filters, format: event.target.value })} /></label>
                <button type="submit">Apply catalog filters</button>
                <button type="button" onClick={() => {
                    const empty = { query: '', country: '', format: '' };
                    setFilters(empty); setCatalogFilters(empty);
                }}>Clear catalog filters</button>
            </form>
            {collectedError ? (
                <article className="empty-card empty-card--error" role="alert">
                    <h3>Unable to load the catalog</h3>
                    <p>{collectedError}</p>
                </article>
            ) : null}
            {collectedLoading && collectedDatasets.length === 0 ? (
                <article className="empty-card empty-card--loading" role="status">
                    <h3>Loading the catalog</h3>
                </article>
            ) : collectedDatasets.length === 0 && !collectedError ? (
                <article className="empty-card">
                    <h3>{Object.values(catalogFilters).some(value => value.trim())
                        ? 'No datasets match these catalog filters' : 'No datasets in the catalog yet'}</h3>
                    <p>{Object.values(catalogFilters).some(value => value.trim())
                        ? 'Change or clear the filters to browse the catalog.'
                        : 'Run a search. Accepted datasets with validated links are added automatically.'}</p>
                </article>
            ) : collectedDatasets.length > 0 ? (
                <>
                    <p>{collectedDatasets.length} dataset{collectedDatasets.length === 1 ? '' : 's'} loaded</p>
                    <div className="repository-result-grid">
                        {collectedDatasets.map(dataset => (
                            <LocalDatasetSearchCard key={dataset.id} item={dataset} />
                        ))}
                    </div>
                    {nextCursor != null && <button type="button" onClick={loadMoreCollectedDatasets}
                        disabled={collectedLoading || collectedLoadingMore}>
                        {collectedLoadingMore ? 'Loading more…' : 'Show more'}
                    </button>}
                </>
            ) : null}
        </section>
    );
}
