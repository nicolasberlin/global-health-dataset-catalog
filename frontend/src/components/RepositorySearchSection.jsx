import LocalDatasetSearchCard from './LocalDatasetSearchCard.jsx';
import RepositoryAcceptedCard from './RepositoryAcceptedCard.jsx';
import RepositoryProgressCard from './RepositoryProgressCard.jsx';

const AGREEMENT_FILTERS = [
    { value: 'all', label: 'Tous' },
    { value: '1', label: '1/1' },
];

export default function RepositorySearchSection({
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
    return (
        <section
            className="repository-section"
            aria-labelledby="repository-search-title"
            aria-busy={repositoryAnalysisInProgress}
        >
            <div className="section-heading repository-heading">
                <div>
                    <h2 id="repository-search-title">Repository Search</h2>
                    <p>
                        Recherche d’abord dans le catalogue local, puis dans les
                        repositories avec validation IA si nécessaire.
                    </p>
                </div>
                {repositoryResultQuery ? (
                    <span className="repository-query-label">
                        « {repositoryResultQuery} »
                    </span>
                ) : null}
            </div>

            <form className="repository-search-form" onSubmit={searchRepositories}>
                <div className="repository-query-field">
                    <label htmlFor="repository-query">Rechercher un dataset santé</label>
                    <input
                        id="repository-query"
                        type="search"
                        value={repositoryQuery}
                        onChange={(event) => setRepositoryQuery(event.target.value)}
                        placeholder="Ex. malaria mortality France"
                        maxLength={300}
                        autoComplete="off"
                    />
                </div>
                <button type="submit" disabled={repositoryAnalysisInProgress}>
                    {repositorySearching
                        ? 'Recherche…'
                        : repositoryAnalysisInProgress
                          ? 'Analyse…'
                          : 'Rechercher'}
                </button>
            </form>

            {repositoryOrigin !== 'database' ? (
                <div className="repository-controls">
                    <fieldset className="agreement-filter">
                        <legend>Accord IA</legend>
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

                    <div
                        className="repository-counters"
                        aria-label="État de la classification"
                    >
                        <span>
                            <strong>{repositoryCandidates.length}</strong>
                            candidats
                        </span>
                        <span>
                            <strong>
                                {repositoryStatusCounts.pending +
                                    repositoryStatusCounts.classifying}
                            </strong>
                            en analyse
                        </span>
                        <span>
                            <strong>{repositoryStatusCounts.accepted}</strong>
                            acceptés
                        </span>
                        <span>
                            <strong>{repositoryStatusCounts.rejected}</strong>
                            rejetés
                        </span>
                        <span>
                            <strong>{repositoryStatusCounts.error}</strong>
                            erreurs
                        </span>
                    </div>
                </div>
            ) : null}

            {repositoryError ? (
                <div className="repository-message repository-message--error" role="alert">
                    <strong>Recherche impossible</strong>
                    <span>{repositoryError}</span>
                </div>
            ) : null}

            {repositoryWarnings.length > 0 ? (
                <div className="repository-message repository-message--warning" role="status">
                    <strong>Avertissements</strong>
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
                    <strong>Résultats trouvés dans le catalogue local</strong>
                    <span>Aucune recherche externe ni classification IA nécessaire.</span>
                </div>
            ) : null}

            {repositoryOrigin === 'online' ? (
                <div className="repository-message repository-message--online" role="status">
                    <strong>Aucun résultat local</strong>
                    <span>Recherche dans les repositories et validation IA en cours.</span>
                </div>
            ) : null}

            {!repositoryHasSearched ? (
                <div className="repository-empty-state">
                    <h3>Trouver un dataset santé</h3>
                    <p>Tape quelques mots-clés pour lancer la recherche et l’analyse IA.</p>
                </div>
            ) : null}

            {repositoryHasSearched && repositorySearching ? (
                <div
                    className="repository-empty-state repository-empty-state--loading"
                    role="status"
                >
                    <h3>Recherche des candidats</h3>
                    <p>Interrogation du catalogue local puis des repositories disponibles…</p>
                </div>
            ) : null}

            {!repositorySearching &&
            repositoryOrigin === 'database' &&
            localRepositoryResults.length > 0 ? (
                <div className="repository-result-grid" aria-live="polite">
                    {localRepositoryResults.map((item) => (
                        <LocalDatasetSearchCard
                            key={item.id ?? item.dataset_url}
                            item={item}
                        />
                    ))}
                </div>
            ) : null}

            {!repositorySearching &&
            (inProgressRepositoryCandidates.length > 0 ||
                acceptedRepositoryCandidates.length > 0) ? (
                <div className="repository-result-grid" aria-live="polite">
                    {acceptedRepositoryCandidates.map((candidate) => (
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
                    <h3>Aucun dataset accepté pour cette recherche.</h3>
                    <p>Essaie avec des mots-clés plus précis ou une autre zone géographique.</p>
                </div>
            ) : null}

            {repositoryHasSearched &&
            !repositoryAnalysisInProgress &&
            repositoryOrigin === 'online' &&
            repositoryStatusCounts.accepted > 0 &&
            acceptedRepositoryCandidates.length === 0 ? (
                <div className="repository-empty-state">
                    <h3>Aucun résultat avec ce niveau d’accord.</h3>
                    <p>Sélectionne « Tous » pour revoir les datasets acceptés.</p>
                </div>
            ) : null}

            {repositoryStatusCounts.rejected > 0 ? (
                <p className="repository-rejected-summary" aria-live="polite">
                    Sur {repositoryCandidates.length} candidats,{' '}
                    {repositoryStatusCounts.rejected}{' '}
                    {repositoryStatusCounts.rejected === 1
                        ? 'a été rejeté'
                        : 'ont été rejetés'}{' '}
                    par l’IA.
                </p>
            ) : null}

            {repositoryClassificationErrors.length > 0 ? (
                <div className="repository-classification-errors" aria-live="polite">
                    <strong>Erreurs de classification</strong>
                    <ul>
                        {repositoryClassificationErrors.map((candidate) => (
                            <li key={candidate.id}>
                                <span>
                                    {candidate.item.title}
                                    {candidate.error ? <small>{candidate.error}</small> : null}
                                </span>
                                <strong>Erreur</strong>
                            </li>
                        ))}
                    </ul>
                </div>
            ) : null}
        </section>
    );
}
