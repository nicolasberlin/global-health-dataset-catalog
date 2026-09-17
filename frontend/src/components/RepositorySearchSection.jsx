import { useState } from 'react';
import { datasetCountries, datasetFormats } from './DatasetAccessDetails.jsx';
import LocalDatasetSearchCard from './LocalDatasetSearchCard.jsx';
import RepositoryAcceptedCard from './RepositoryAcceptedCard.jsx';
import RepositoryProgressCard from './RepositoryProgressCard.jsx';

const AGREEMENT_FILTERS = [
    { value: 'all', label: 'All' },
    { value: '2', label: '2/3' },
    { value: '3', label: '3/3' },
];

export default function RepositorySearchSection({
    collectedDatasets = [],
    acceptedRepositoryCandidates,
    agreementFilter,
    inProgressRepositoryCandidates,
    repositoryAnalysisInProgress,
    repositoryCandidates,
    repositoryClassificationErrors,
    repositoryError,
    repositoryHasSearched,
    repositoryOrigin,
    repositoryQuery,
    repositoryResultQuery,
    repositorySearching,
    repositoryStatusCounts,
    repositoryWarnings,
    localRepositoryResults,
    searchRepositories,
    setAgreementFilter,
    setRepositoryQuery,
}) {
    const [subject, setSubject] = useState('');
    const [country, setCountry] = useState('');
    const [format, setFormat] = useState('');
    const enrich = item => {
        const saved = collectedDatasets.find(dataset => dataset.dataset_url === (item.dataset_url || item.url));
        return saved ? { ...item, ...saved } : item;
    };
    const localItems = localRepositoryResults.map(enrich);
    const acceptedCandidates = acceptedRepositoryCandidates.map(candidate => ({
        ...candidate, item: enrich(candidate.item),
    }));
    const availableItems = repositoryOrigin === 'database' ? localItems :
        repositoryCandidates.filter(candidate => candidate.status === 'accepted').map(candidate => enrich(candidate.item));
    const countries = [...new Set(availableItems.flatMap(datasetCountries))].sort();
    const formats = [...new Set(availableItems.flatMap(datasetFormats))].sort();
    const normalize = value => String(value).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
    const matches = item => {
        const text = [item.title, item.description, ...(Array.isArray(item.keywords) ? item.keywords : [])].join(' ');
        return normalize(text).includes(normalize(subject.trim())) &&
            (!country || datasetCountries(item).includes(country)) &&
            (!format || datasetFormats(item).includes(format));
    };
    const visibleLocalItems = localItems.filter(matches);
    const visibleCandidates = acceptedCandidates.filter(candidate => matches(candidate.item));
    const visibleCount = repositoryOrigin === 'database' ? visibleLocalItems.length : visibleCandidates.length;
    const totalCount = availableItems.length;

    return (
        <section
            className="repository-section"
            aria-labelledby="repository-search-title"
            aria-busy={repositoryAnalysisInProgress}
        >
            <div className="section-heading repository-heading">
                <div>
                    <h2 id="repository-search-title">Search health datasets</h2>
                    <p>Explore datasets by topic, disease, or geographic area.</p>
                </div>
                {repositoryResultQuery ? (
                    <span className="repository-query-label">
                        « {repositoryResultQuery} »
                    </span>
                ) : null}
            </div>

            <form className="repository-search-form" onSubmit={event => {
                setSubject(''); setCountry(''); setFormat('');
                searchRepositories(event);
            }}>
                <div className="repository-query-field">
                    <label htmlFor="repository-query">Search for a health dataset</label>
                    <input
                        id="repository-query"
                        type="search"
                        value={repositoryQuery}
                        onChange={(event) => setRepositoryQuery(event.target.value)}
                        placeholder="For example, malaria mortality France"
                        maxLength={300}
                        autoComplete="off"
                    />
                </div>
                <button type="submit" disabled={repositoryAnalysisInProgress && repositoryQuery.trim() === repositoryResultQuery}>
                    {repositoryQuery.trim() !== repositoryResultQuery
                        ? 'Search'
                        : repositorySearching
                        ? 'Searching…'
                        : repositoryAnalysisInProgress
                          ? 'Analyzing…'
                          : 'Search'}
                </button>
            </form>

            {repositoryHasSearched && !repositorySearching && !repositoryError && (
                <div className="dataset-result-tools">
                    <p role="status"><strong>{visibleCount}</strong> of {totalCount} dataset{totalCount === 1 ? '' : 's'} displayed
                        {repositoryAnalysisInProgress ? ' · Analysis in progress…' : ''}</p>
                    {totalCount > 0 && <div className="dataset-filters">
                        <label>Topic<input value={subject} onChange={event => setSubject(event.target.value)} placeholder="Refine results" /></label>
                        <label>Country or area<select value={country} onChange={event => setCountry(event.target.value)}>
                            <option value="">All countries and areas</option>
                            {countries.map(value => <option key={value}>{value}</option>)}
                        </select></label>
                        <label>Format<select value={format} onChange={event => setFormat(event.target.value)}>
                            <option value="">All formats</option>
                            {formats.map(value => <option key={value}>{value}</option>)}
                        </select></label>
                        <button type="button" className="secondary-button" onClick={() => {
                            setSubject(''); setCountry(''); setFormat(''); setAgreementFilter('all');
                        }}>Clear filters</button>
                    </div>}
                </div>
            )}

            {repositoryOrigin !== 'database' ? (
                <div className="repository-controls">
                    <fieldset className="agreement-filter">
                        <legend>AI agreement</legend>
                        <div className="agreement-filter__options">
                            {AGREEMENT_FILTERS.map((filter) => (
                                <button
                                    key={filter.value}
                                    type="button"
                                    className={
                                        agreementFilter === filter.value
                                            ? 'agreement-filter__button agreement-filter__button--active'
                                            : 'agreement-filter__button'
                                    }
                                    aria-pressed={agreementFilter === filter.value}
                                    onClick={() => setAgreementFilter(filter.value)}
                                >
                                    {filter.label}
                                </button>
                            ))}
                        </div>
                    </fieldset>

                </div>
            ) : null}

            {repositoryError ? (
                <div className="repository-message repository-message--error" role="alert">
                    <strong>Search failed</strong>
                    <span>{repositoryError}</span>
                </div>
            ) : null}

            {repositoryWarnings.length > 0 ? (
                <div className="repository-message repository-message--warning" role="status">
                    <strong>Warnings</strong>
                    <ul>
                        {repositoryWarnings.map((warning, index) => (
                            <li key={`${warning.provider ?? 'repository'}-${index}`}>
                                {warning.provider ? `${warning.provider} : ` : ''}
                                {warning.message}
                            </li>
                        ))}
                    </ul>
                </div>
            ) : null}

            {repositoryOrigin === 'database' ? (
                <div className="repository-message repository-message--local" role="status">
                    <strong>Results found in the local catalog</strong>
                    <span>No external search or AI classification was needed.</span>
                </div>
            ) : null}

            {repositoryOrigin === 'online' ? (
                <div className="repository-message repository-message--online" role="status">
                    <strong>No local results</strong>
                    <span>Searching external repositories and running AI validation.</span>
                </div>
            ) : null}

            {!repositoryHasSearched ? (
                <div className="repository-empty-state">
                    <h3>Find a health dataset</h3>
                    <p>Enter a few keywords to start the search and AI analysis.</p>
                </div>
            ) : null}

            {repositoryHasSearched && repositorySearching ? (
                <div
                    className="repository-empty-state repository-empty-state--loading"
                    role="status"
                >
                    <h3>Searching for candidates</h3>
                    <p>Searching the local catalog, then available repositories…</p>
                </div>
            ) : null}

            {!repositorySearching &&
            repositoryOrigin === 'database' &&
            visibleLocalItems.length > 0 ? (
                <div className="repository-result-grid" aria-live="polite">
                    {visibleLocalItems.map((item) => (
                        <LocalDatasetSearchCard
                            key={item.id ?? item.dataset_url}
                            item={item}
                        />
                    ))}
                </div>
            ) : null}

            {!repositorySearching &&
            (inProgressRepositoryCandidates.length > 0 ||
                visibleCandidates.length > 0) ? (
                <div className="repository-result-grid" aria-live="polite">
                    {visibleCandidates.map((candidate) => (
                        <RepositoryAcceptedCard key={candidate.id} candidate={candidate} />
                    ))}
                    {inProgressRepositoryCandidates.map((candidate) => (
                        <RepositoryProgressCard key={candidate.id} candidate={candidate} />
                    ))}
                </div>
            ) : null}

            {repositoryHasSearched &&
            !repositoryAnalysisInProgress &&
            repositoryOrigin === 'online' &&
            repositoryStatusCounts.accepted === 0 &&
            !repositoryError ? (
                <div className="repository-empty-state">
                    <h3>No dataset was accepted for this search.</h3>
                    <p>Try more specific keywords or another geographic area.</p>
                </div>
            ) : null}

            {repositoryHasSearched &&
            !repositoryAnalysisInProgress &&
            totalCount > 0 && visibleCount === 0 ? (
                <div className="repository-empty-state">
                    <h3>No results match these filters.</h3>
                    <p>Clear the filters to see all datasets found.</p>
                </div>
            ) : null}

            {repositoryStatusCounts.rejected > 0 ? (
                <p className="repository-rejected-summary" aria-live="polite">
                    Of {repositoryCandidates.length} candidates,{' '}
                    {repositoryStatusCounts.rejected}{' '}
                    {repositoryStatusCounts.rejected === 1
                        ? 'was rejected'
                        : 'were rejected'}{' '}
                    by the AI classifiers.
                </p>
            ) : null}

            {repositoryClassificationErrors.length > 0 ? (
                <div className="repository-classification-errors" aria-live="polite">
                    <strong>Classification errors</strong>
                    <ul>
                        {repositoryClassificationErrors.map((candidate) => (
                            <li key={candidate.id}>
                                <span>
                                    {candidate.item.title}
                                    {candidate.error ? <small>{candidate.error}</small> : null}
                                </span>
                                <strong>Error</strong>
                            </li>
                        ))}
                    </ul>
                </div>
            ) : null}
        </section>
    );
}
