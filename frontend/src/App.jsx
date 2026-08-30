import { useEffect, useMemo, useRef, useState } from 'react';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8001';
const REPOSITORY_RESULT_LIMIT = 10;
const REPOSITORY_CLASSIFICATION_CONCURRENCY = 2;
const AGREEMENT_FILTERS = [
    { value: 'all', label: 'Tous' },
    { value: '3', label: '3/3' },
    { value: '2', label: '2/3' },
];

const SAMPLE_COLLECTOR_HTML = `<html>
  <head>
    <title>Mortality by age and sex dataset</title>
    <meta name="description" content="Official mortality health dataset." />
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "Dataset",
      "name": "Mortality by age and sex",
      "publisher": {"@type": "Organization", "name": "National Health Agency"},
      "spatialCoverage": {"@type": "Country", "name": "France"},
      "distribution": [
        {
          "@type": "DataDownload",
          "contentUrl": "https://example.org/files/mortality.csv",
          "encodingFormat": "text/csv"
        }
      ]
    }
    </script>
  </head>
  <body>
    <h1>Mortality by age and sex</h1>
    <p>This health dataset contains mortality and epidemiology indicators.</p>
    <a href="https://example.org/files/mortality.xlsx">Download data as XLSX</a>
    <a href="https://example.org/api/export?dataset=mortality&format=json">API export</a>
  </body>
</html>`;

function normalizeSearchValue(value) {
    return String(value ?? '')
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLowerCase();
}

function formatPercent(value) {
    return `${Math.round(Number(value ?? 0) * 100)}%`;
}

function getHostname(url) {
    try {
        return new URL(url).hostname;
    } catch {
        return url;
    }
}

function wait(milliseconds) {
    return new Promise((resolve) => {
        window.setTimeout(resolve, milliseconds);
    });
}

function formatCollectionMethods(methods) {
    const values = Array.isArray(methods) ? methods.filter(Boolean) : [];
    return values.length > 0 ? values.join(', ') : 'n/a';
}

function formatCountries(countries) {
    const values = Array.isArray(countries) ? countries.filter(Boolean) : [];
    return values.length > 0 ? values.join(', ') : 'pays non detecte';
}

function getResponseError(payload, fallbackMessage) {
    if (typeof payload?.detail === 'string' && payload.detail.trim()) {
        return payload.detail;
    }

    return fallbackMessage;
}

function isAbortError(exception) {
    return (
        typeof exception === 'object' &&
        exception !== null &&
        'name' in exception &&
        exception.name === 'AbortError'
    );
}

function getEnsembleSummary(classification) {
    return (
        classification?.ensemble ??
        classification?.dataset_signals?.ensemble ??
        classification?.health_signals?.ensemble ??
        null
    );
}

function getAcceptedVoteCount(classification) {
    const ensemble = getEnsembleSummary(classification);
    const explicitCount = Number(ensemble?.accepted_votes);
    if (Number.isFinite(explicitCount)) {
        return explicitCount;
    }

    if (Array.isArray(ensemble?.voters)) {
        return ensemble.voters.filter((voter) => voter?.accepted === true).length;
    }

    return null;
}

function formatRepositoryRelevanceLabel(label) {
    const labels = {
        relevant: 'Pertinent',
        somewhat_relevant: 'Partiellement pertinent',
        not_relevant: 'Non pertinent',
        insufficient_information: 'Information insuffisante',
    };

    return labels[label] ?? String(label ?? '').replaceAll('_', ' ').toLowerCase();
}

function formatDecisionReason(reason) {
    const reasons = {
        enough_accept_votes: 'accord suffisant',
        rejected_by_majority: 'rejet à la majorité',
        insufficient_accept_votes: 'accord insuffisant',
    };

    return reasons[reason] ?? reason;
}

function repositoryCandidateId(item, index) {
    return `${item.source}:${item.url}:${index}`;
}

function RepositoryProgressCard({ candidate }) {
    const { item, status } = candidate;

    return (
        <article className="repository-card repository-card--progress">
            <div className="repository-card__top">
                <span className="repository-source-pill">{item.source}</span>
                <span
                    className={`repository-status-pill repository-status-pill--${status}`}
                    role="status"
                >
                    {status === 'classifying' ? 'Analyse IA…' : 'En attente'}
                </span>
            </div>
            <h3>{item.title}</h3>
            <p>{item.description || 'Description non disponible.'}</p>
            <div className="repository-card__footer">
                <span>{item.publisher || getHostname(item.url)}</span>
                {item.date ? <small>{item.date}</small> : null}
            </div>
        </article>
    );
}

function RepositoryAcceptedCard({ candidate }) {
    const { item } = candidate;
    const classification = item.classification;
    const ensemble = getEnsembleSummary(classification);
    const acceptedVotes = getAcceptedVoteCount(classification);
    const voters = Array.isArray(ensemble?.voters) ? ensemble.voters : [];
    const agreementLabel = acceptedVotes === null ? '' : ` ${acceptedVotes}/3`;

    return (
        <article className="repository-card repository-card--accepted">
            <div className="repository-card__top">
                <span className="repository-source-pill">{item.source}</span>
                <span className="repository-status-pill repository-status-pill--accepted">
                    Accepté{agreementLabel}
                </span>
            </div>

            <h3>{item.title}</h3>
            <p>{item.description || 'Description non disponible.'}</p>

            {(item.publisher || item.date) && (
                <dl className="repository-facts">
                    {item.publisher ? (
                        <div>
                            <dt>Publisher</dt>
                            <dd>{item.publisher}</dd>
                        </div>
                    ) : null}
                    {item.date ? (
                        <div>
                            <dt>Date</dt>
                            <dd>{item.date}</dd>
                        </div>
                    ) : null}
                </dl>
            )}

            {classification?.relevance_label ? (
                <div className="repository-decision-row">
                    <span>
                        Pertinence IA
                        <strong>
                            {formatRepositoryRelevanceLabel(
                                classification.relevance_label,
                            )}
                        </strong>
                    </span>
                </div>
            ) : null}

            <div className="repository-card__link-row">
                <span>{getHostname(item.url)}</span>
                <a href={item.url} target="_blank" rel="noreferrer">
                    Ouvrir le dataset
                </a>
            </div>

            {ensemble ? (
                <details className="repository-ai-details">
                    <summary>Détails IA</summary>
                    <p>
                        {acceptedVotes ?? 0}/3 votes favorables
                        {ensemble.decision_reason
                            ? ` · ${formatDecisionReason(ensemble.decision_reason)}`
                            : ''}
                    </p>
                    {voters.length > 0 ? (
                        <ul>
                            {voters.map((voter, index) => (
                                <li key={`${voter.voter_id ?? 'ia'}-${index}`}>
                                    <span>
                                        {voter.voter_id || `IA ${index + 1}`}
                                        {voter.reason ? (
                                            <small>{voter.reason}</small>
                                        ) : null}
                                    </span>
                                    <strong>
                                        {voter.accepted ? 'Accepte' : 'Refuse'}
                                        {voter.relevance_label
                                            ? ` · ${formatRepositoryRelevanceLabel(
                                                  voter.relevance_label,
                                              )}`
                                            : ''}
                                    </strong>
                                </li>
                            ))}
                        </ul>
                    ) : null}
                    {Number(ensemble.failed_votes) > 0 ? (
                        <small>{ensemble.failed_votes} vote IA indisponible.</small>
                    ) : null}
                </details>
            ) : null}
        </article>
    );
}

export default function App() {
    const repositorySearchRunRef = useRef(0);
    const repositorySearchAbortRef = useRef(null);
    const [sources, setSources] = useState([]);
    const [collectedDatasets, setCollectedDatasets] = useState([]);
    const [selectedTheme, setSelectedTheme] = useState('All');
    const [searchTerm, setSearchTerm] = useState('');
    const [loading, setLoading] = useState(true);
    const [loaded, setLoaded] = useState(false);
    const [error, setError] = useState('');
    const [collectedLoading, setCollectedLoading] = useState(true);
    const [collectedError, setCollectedError] = useState('');
    const [collectingSourceId, setCollectingSourceId] = useState(null);
    const [collectionNotice, setCollectionNotice] = useState(null);
    const [activeCollectionJob, setActiveCollectionJob] = useState(null);
    const [collectorUrl, setCollectorUrl] = useState('https://example.org/data/catalog');
    const [collectorHtml, setCollectorHtml] = useState(SAMPLE_COLLECTOR_HTML);
    const [collectorLoading, setCollectorLoading] = useState(false);
    const [collectorError, setCollectorError] = useState('');
    const [collectorResult, setCollectorResult] = useState(null);
    const [repositoryQuery, setRepositoryQuery] = useState('');
    const [repositoryResultQuery, setRepositoryResultQuery] = useState('');
    const [repositoryCandidates, setRepositoryCandidates] = useState([]);
    const [repositoryWarnings, setRepositoryWarnings] = useState([]);
    const [repositoryError, setRepositoryError] = useState('');
    const [repositorySearching, setRepositorySearching] = useState(false);
    const [repositoryHasSearched, setRepositoryHasSearched] = useState(false);
    const [agreementFilter, setAgreementFilter] = useState('all');

    async function loadSources() {
        try {
            setLoading(true);
            setError('');

            const response = await fetch(`${API_BASE_URL}/sources`);
            if (!response.ok) {
                throw new Error('Impossible de récupérer les datasets.');
            }

            const data = await response.json();
            setSources(data.items ?? []);
            setLoaded(true);
        } catch (exception) {
            setSources([]);
            setError(exception instanceof Error ? exception.message : 'Erreur inconnue');
            setLoaded(true);
        } finally {
            setLoading(false);
        }
    }

    async function loadCollectedDatasets({ silent = false } = {}) {
        try {
            if (!silent) {
                setCollectedLoading(true);
            }
            setCollectedError('');

            const response = await fetch(`${API_BASE_URL}/collector/collected-datasets`);
            if (!response.ok) {
                throw new Error('Impossible de récupérer les datasets collectés.');
            }

            const data = await response.json();
            setCollectedDatasets(data.items ?? []);
        } catch (exception) {
            setCollectedDatasets([]);
            setCollectedError(exception instanceof Error ? exception.message : 'Erreur inconnue');
        } finally {
            if (!silent) {
                setCollectedLoading(false);
            }
        }
    }

    useEffect(() => {
        loadSources();
        loadCollectedDatasets();

        return () => {
            repositorySearchRunRef.current += 1;
            repositorySearchAbortRef.current?.abort();
        };
    }, []);

    function updateRepositoryCandidate(runId, candidateId, update) {
        if (repositorySearchRunRef.current !== runId) {
            return;
        }

        setRepositoryCandidates((currentCandidates) =>
            currentCandidates.map((candidate) =>
                candidate.id === candidateId ? { ...candidate, ...update } : candidate,
            ),
        );
    }

    async function classifyRepositoryCandidates(candidates, runId, abortController) {
        let nextCandidateIndex = 0;
        const { signal } = abortController;

        async function classificationWorker() {
            while (repositorySearchRunRef.current === runId && !signal.aborted) {
                const candidateIndex = nextCandidateIndex;
                nextCandidateIndex += 1;

                if (candidateIndex >= candidates.length) {
                    return;
                }

                const candidate = candidates[candidateIndex];
                updateRepositoryCandidate(runId, candidate.id, {
                    status: 'classifying',
                    error: '',
                });

                try {
                    const response = await fetch(
                        `${API_BASE_URL}/collector/classify-repository-result`,
                        {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                            body: JSON.stringify(candidate.item),
                            signal,
                        },
                    );

                    const responsePayload = await response.json().catch(() => null);
                    if (!response.ok) {
                        throw new Error(
                            getResponseError(
                                responsePayload,
                                'La classification IA a échoué.',
                            ),
                        );
                    }

                    if (typeof responsePayload?.classification?.accepted !== 'boolean') {
                        throw new Error('La réponse de classification est incomplète.');
                    }

                    updateRepositoryCandidate(runId, candidate.id, {
                        item: responsePayload,
                        status: responsePayload.classification.accepted
                            ? 'accepted'
                            : 'rejected',
                        error: '',
                    });
                } catch (exception) {
                    if (isAbortError(exception) || signal.aborted) {
                        return;
                    }

                    updateRepositoryCandidate(runId, candidate.id, {
                        status: 'error',
                        error:
                            exception instanceof Error
                                ? exception.message
                                : 'Erreur de classification.',
                    });
                }
            }
        }

        const workerCount = Math.min(
            REPOSITORY_CLASSIFICATION_CONCURRENCY,
            candidates.length,
        );
        await Promise.all(
            Array.from({ length: workerCount }, () => classificationWorker()),
        );

        if (
            repositorySearchRunRef.current === runId &&
            repositorySearchAbortRef.current === abortController
        ) {
            repositorySearchAbortRef.current = null;
        }
    }

    async function searchRepositories(event) {
        event.preventDefault();

        if (repositoryAnalysisInProgress) {
            return;
        }

        const query = repositoryQuery.trim();

        if (!query) {
            setRepositoryError('Saisis une recherche avant de continuer.');
            return;
        }

        const runId = repositorySearchRunRef.current + 1;
        repositorySearchAbortRef.current?.abort();
        const abortController = new AbortController();
        repositorySearchRunRef.current = runId;
        repositorySearchAbortRef.current = abortController;
        setRepositorySearching(true);
        setRepositoryHasSearched(true);
        setRepositoryResultQuery(query);
        setRepositoryCandidates([]);
        setRepositoryWarnings([]);
        setRepositoryError('');

        let classificationStarted = false;
        try {
            const response = await fetch(`${API_BASE_URL}/collector/search-repositories`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ query }),
                signal: abortController.signal,
            });
            const responsePayload = await response.json().catch(() => null);

            if (!response.ok) {
                throw new Error(
                    getResponseError(responsePayload, 'La recherche repository a échoué.'),
                );
            }

            if (repositorySearchRunRef.current !== runId) {
                return;
            }

            const candidates = (Array.isArray(responsePayload?.items)
                ? responsePayload.items
                : []
            )
                .slice(0, REPOSITORY_RESULT_LIMIT)
                .map((item, index) => ({
                    id: repositoryCandidateId(item, index),
                    item: {
                        ...item,
                        search_query: item.search_query || query,
                    },
                    status: 'pending',
                    error: '',
                }));

            setRepositoryCandidates(candidates);
            setRepositoryWarnings(
                Array.isArray(responsePayload?.warnings) ? responsePayload.warnings : [],
            );

            if (candidates.length > 0) {
                classificationStarted = true;
                void classifyRepositoryCandidates(candidates, runId, abortController);
            }
        } catch (exception) {
            if (isAbortError(exception) || abortController.signal.aborted) {
                return;
            }

            if (repositorySearchRunRef.current !== runId) {
                return;
            }

            setRepositoryError(
                exception instanceof Error ? exception.message : 'Erreur de recherche.',
            );
        } finally {
            if (repositorySearchRunRef.current === runId) {
                setRepositorySearching(false);
            }

            if (
                !classificationStarted &&
                repositorySearchAbortRef.current === abortController
            ) {
                repositorySearchAbortRef.current = null;
            }
        }
    }

    async function loadCollectionJob(jobId) {
        const response = await fetch(`${API_BASE_URL}/collector/collection-jobs/${jobId}`);
        if (!response.ok) {
            const errorPayload = await response.json().catch(() => null);
            throw new Error(errorPayload?.detail ?? 'Impossible de lire le statut de collecte.');
        }

        const data = await response.json();
        return data.job;
    }

    async function pollCollectionJob(jobId, sourceName) {
        const maxAttempts = 80;

        for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
            await wait(attempt === 0 ? 700 : 1500);

            const job = await loadCollectionJob(jobId);
            setActiveCollectionJob(job);

            if (job.status === 'done') {
                await loadCollectedDatasets({ silent: true });
                setCollectionNotice({
                    tone: job.saved_count > 0 ? 'ok' : 'empty',
                    message:
                        job.saved_count > 0
                            ? `${job.saved_count} dataset(s) sauvegardé(s) depuis ${sourceName}.`
                            : `Aucun dataset santé avec fichier valide trouvé pour ${sourceName}.`,
                });
                return;
            }

            if (job.status === 'error') {
                throw new Error(job.error || 'Collecte échouée.');
            }

            setCollectionNotice({
                tone: 'loading',
                message: `Job #${job.id}: ${job.message || 'collecte en cours.'}`,
            });
        }

        throw new Error('La collecte prend trop de temps. Réessaie plus tard.');
    }

    async function collectSource(source) {
        try {
            setCollectingSourceId(source.id);
            setCollectionNotice(null);
            setActiveCollectionJob(null);

            const response = await fetch(`${API_BASE_URL}/collector/collection-jobs`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    url: source.page_url,
                }),
            });

            if (!response.ok) {
                const errorPayload = await response.json().catch(() => null);
                throw new Error(errorPayload?.detail ?? 'Impossible de collecter cette source.');
            }

            const data = await response.json();
            setActiveCollectionJob(data.job);
            setCollectionNotice({
                tone: 'loading',
                message: `Job #${data.job.id}: collecte lancée pour ${source.name}.`,
            });
            await pollCollectionJob(data.job.id, source.name);
        } catch (exception) {
            setCollectionNotice({
                tone: 'error',
                message: exception instanceof Error ? exception.message : 'Erreur inconnue',
            });
        } finally {
            setCollectingSourceId(null);
        }
    }

    async function analyzeCollector(endpoint, payload) {
        try {
            setCollectorLoading(true);
            setCollectorError('');
            setCollectorResult(null);

            const response = await fetch(`${API_BASE_URL}/collector/${endpoint}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload),
            });

            if (!response.ok) {
                const errorPayload = await response.json().catch(() => null);
                throw new Error(errorPayload?.detail ?? 'Impossible d’analyser cette page.');
            }

            setCollectorResult(await response.json());
        } catch (exception) {
            setCollectorError(exception instanceof Error ? exception.message : 'Erreur inconnue');
        } finally {
            setCollectorLoading(false);
        }
    }

    async function analyzeCollectorHtml(event) {
        event.preventDefault();
        await analyzeCollector('analyze-html', {
            url: collectorUrl,
            html: collectorHtml,
        });
    }

    async function analyzeCollectorUrl() {
        await analyzeCollector('analyze-url', {
            url: collectorUrl,
        });
    }

    const themes = useMemo(
        () => ['All', ...Array.from(new Set(sources.map((source) => source.theme))).sort()],
        [sources],
    );

    const filteredSources = useMemo(() => {
        const normalizedSearchTerm = normalizeSearchValue(searchTerm.trim());

        return sources.filter((source) => {
            const matchesTheme = selectedTheme === 'All' || source.theme === selectedTheme;
            const matchesSearch =
                normalizedSearchTerm.length === 0 ||
                normalizeSearchValue(
                    [
                        source.source_key,
                        source.name,
                        source.description,
                        source.theme,
                        source.page_url,
                    ].join(' '),
                ).includes(normalizedSearchTerm);

            return matchesTheme && matchesSearch;
        });
    }, [searchTerm, selectedTheme, sources]);

    const collectedDistributionCount = useMemo(
        () =>
            collectedDatasets.reduce(
                (total, dataset) => total + (dataset.distributions?.length ?? 0),
                0,
            ),
        [collectedDatasets],
    );

    const repositoryStatusCounts = useMemo(
        () =>
            repositoryCandidates.reduce(
                (counts, candidate) => ({
                    ...counts,
                    [candidate.status]: (counts[candidate.status] ?? 0) + 1,
                }),
                {
                    pending: 0,
                    classifying: 0,
                    accepted: 0,
                    rejected: 0,
                    error: 0,
                },
            ),
        [repositoryCandidates],
    );

    const inProgressRepositoryCandidates = useMemo(
        () =>
            repositoryCandidates.filter(
                (candidate) =>
                    candidate.status === 'pending' || candidate.status === 'classifying',
            ),
        [repositoryCandidates],
    );

    const acceptedRepositoryCandidates = useMemo(
        () =>
            repositoryCandidates.filter((candidate) => {
                if (candidate.status !== 'accepted') {
                    return false;
                }

                if (agreementFilter === 'all') {
                    return true;
                }

                return (
                    getAcceptedVoteCount(candidate.item.classification) ===
                    Number(agreementFilter)
                );
            }),
        [agreementFilter, repositoryCandidates],
    );

    const repositoryClassificationErrors = useMemo(
        () => repositoryCandidates.filter((candidate) => candidate.status === 'error'),
        [repositoryCandidates],
    );

    const repositoryAnalysisInProgress =
        repositorySearching ||
        repositoryStatusCounts.pending > 0 ||
        repositoryStatusCounts.classifying > 0;

    const themeCount = themes.length > 0 ? themes.length - 1 : 0;
    const statusTone = error ? 'error' : loading ? 'loading' : 'ok';
    const statusLabel = error ? 'Erreur API' : loading ? 'Chargement' : 'API connectée';
    const selectedThemeLabel = selectedTheme === 'All' ? 'Tous les thèmes' : selectedTheme;

    const emptyState = useMemo(() => {
        if (loading) {
            return {
                title: 'Chargement du catalogue',
                description: 'Lecture des sources depuis l’API.',
            };
        }

        if (error) {
            return {
                title: 'Impossible de charger le catalogue',
                description: error,
            };
        }

        if (loaded && sources.length === 0) {
            return {
                title: 'Aucune source enregistrée',
                description: 'Le backend répond, mais aucune source n’est encore enregistrée.',
            };
        }

        return {
            title: 'Aucun résultat',
            description: 'Aucune source ne correspond au filtre actuel.',
        };
    }, [error, loaded, loading, sources.length]);

    return (
        <main className="app-shell">
            <header className="app-header">
                <div className="title-block">
                    <span className="eyebrow">Global Health</span>
                    <h1>Dataset Catalog</h1>
                    <p>Pages officielles de datasets santé, organisées par source et par thème.</p>
                </div>

                <div className={`api-status api-status--${statusTone}`}>
                    <span>{statusLabel}</span>
                    <strong>{loading ? 'Synchronisation...' : `${sources.length} sources`}</strong>
                    <small>{API_BASE_URL}</small>
                    <button type="button" onClick={loadSources} disabled={loading}>
                        {loading ? 'Chargement...' : 'Actualiser'}
                    </button>
                </div>
            </header>

            <section className="summary-grid" aria-label="Résumé du catalogue">
                <article className="metric-card">
                    <span>Sources</span>
                    <strong>{sources.length}</strong>
                    <small>pages référencées</small>
                </article>
                <article className="metric-card metric-card--accent">
                    <span>Thèmes</span>
                    <strong>{themeCount}</strong>
                    <small>catégories actives</small>
                </article>
                <article className="metric-card">
                    <span>Résultats</span>
                    <strong>{filteredSources.length}</strong>
                    <small>{selectedThemeLabel}</small>
                </article>
                <article className="metric-card metric-card--muted">
                    <span>Collectés</span>
                    <strong>{collectedDatasets.length}</strong>
                    <small>{collectedDistributionCount} fichiers valides</small>
                </article>
            </section>

            <section
                className="repository-section"
                aria-labelledby="repository-search-title"
                aria-busy={repositoryAnalysisInProgress}
            >
                <div className="section-heading repository-heading">
                    <div>
                        <h2 id="repository-search-title">Repository Search</h2>
                        <p>
                            Recherche des datasets santé, puis affiche progressivement ceux
                            acceptés par les trois IA.
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

                    <div className="repository-counters" aria-label="État de la classification">
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

                {!repositoryHasSearched ? (
                    <div className="repository-empty-state">
                        <h3>Trouver un dataset santé</h3>
                        <p>
                            Tape quelques mots-clés pour lancer la recherche et l’analyse IA.
                        </p>
                    </div>
                ) : null}

                {repositoryHasSearched && repositorySearching ? (
                    <div
                        className="repository-empty-state repository-empty-state--loading"
                        role="status"
                    >
                        <h3>Recherche des candidats</h3>
                        <p>Interrogation des repositories disponibles…</p>
                    </div>
                ) : null}

                {!repositorySearching &&
                (inProgressRepositoryCandidates.length > 0 ||
                    acceptedRepositoryCandidates.length > 0) ? (
                    <div className="repository-result-grid" aria-live="polite">
                        {acceptedRepositoryCandidates.map((candidate) => (
                            <RepositoryAcceptedCard
                                key={candidate.id}
                                candidate={candidate}
                            />
                        ))}
                        {inProgressRepositoryCandidates.map((candidate) => (
                            <RepositoryProgressCard
                                key={candidate.id}
                                candidate={candidate}
                            />
                        ))}
                    </div>
                ) : null}

                {repositoryHasSearched &&
                !repositoryAnalysisInProgress &&
                repositoryStatusCounts.accepted === 0 &&
                !repositoryError ? (
                    <div className="repository-empty-state">
                        <h3>Aucun dataset accepté pour cette recherche.</h3>
                        <p>Essaie avec des mots-clés plus précis ou une autre zone géographique.</p>
                    </div>
                ) : null}

                {repositoryHasSearched &&
                !repositoryAnalysisInProgress &&
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
                                        {candidate.error ? (
                                            <small>{candidate.error}</small>
                                        ) : null}
                                    </span>
                                    <strong>Erreur</strong>
                                </li>
                            ))}
                        </ul>
                    </div>
                ) : null}
            </section>

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
                                            href={`${API_BASE_URL}/sources/${source.id}/page`}
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

            <section className="collected-section">
                <div className="section-heading">
                    <div>
                        <h2>Datasets collectés</h2>
                        <p>Résultats sauvegardés après classification santé et validation des fichiers.</p>
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
                                    <span className="theme-pill">{dataset.discovery_method || 'source'}</span>
                                    <span className="health-pill">{dataset.health_label}</span>
                                </div>
                                <h3>{dataset.title}</h3>
                                <p>{dataset.description || dataset.dataset_url}</p>

                                <div className="dataset-score-row">
                                    <span>
                                        Dataset
                                        <strong>{formatPercent(dataset.dataset_probability)}</strong>
                                    </span>
                                    <span>
                                        Santé
                                        <strong>{formatPercent(dataset.health_probability)}</strong>
                                    </span>
                                    <span>
                                        Fichiers
                                        <strong>{dataset.distributions?.length ?? 0}</strong>
                                    </span>
                                </div>

                                <div className="dataset-card__source">
                                    <div className="dataset-card__source-text">
                                        <span>{dataset.publisher || getHostname(dataset.dataset_url)}</span>
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

            <section className="collector-section">
                <div className="section-heading">
                    <div>
                        <h2>Test collector</h2>
                        <p>
                            Colle du HTML ou analyse directement une URL publique pour voir comment
                            le collector l’interprete.
                        </p>
                    </div>
                </div>

                <form className="collector-form" onSubmit={analyzeCollectorHtml}>
                    <div className="collector-url-field">
                        <label htmlFor="collector-url">URL de la page</label>
                        <input
                            id="collector-url"
                            type="url"
                            value={collectorUrl}
                            onChange={(event) => setCollectorUrl(event.target.value)}
                            required
                        />
                    </div>
                    <div className="collector-html-field">
                        <label htmlFor="collector-html">HTML a analyser</label>
                        <textarea
                            id="collector-html"
                            value={collectorHtml}
                            onChange={(event) => setCollectorHtml(event.target.value)}
                            rows={12}
                            required
                        />
                    </div>
                    <div className="collector-action-row">
                        <button type="submit" disabled={collectorLoading}>
                            {collectorLoading ? 'Analyse...' : 'Analyser le HTML'}
                        </button>
                        <button
                            type="button"
                            className="secondary-button"
                            onClick={analyzeCollectorUrl}
                            disabled={collectorLoading}
                        >
                            Analyser l’URL
                        </button>
                    </div>
                </form>

                {collectorError ? (
                    <article className="collector-result collector-result--error">
                        <h3>Erreur collector</h3>
                        <p>{collectorError}</p>
                    </article>
                ) : null}

                {collectorResult ? (
                    <article className="collector-result">
                        <div className="collector-result__header">
                            <div>
                                <span className="theme-pill">
                                    {collectorResult.accepted ? 'Dataset accepte' : 'Dataset rejete'}
                                </span>
                                <h3>{collectorResult.title}</h3>
                                <p>{collectorResult.description || collectorResult.dataset_url}</p>
                            </div>
                            <div className="collector-score-grid">
                                <span>
                                    Dataset
                                    <strong>
                                        {formatPercent(collectorResult.dataset_probability)}
                                    </strong>
                                </span>
                                <span>
                                    Sante
                                    <strong>{formatPercent(collectorResult.health_probability)}</strong>
                                </span>
                            </div>
                        </div>

                        <div className="collector-detail-grid">
                            <div>
                                <h4>Classification</h4>
                                <p>
                                    Label sante: <strong>{collectorResult.health_label}</strong>
                                </p>
                                <p>
                                    Publisher:{' '}
                                    <strong>{collectorResult.publisher || 'non detecte'}</strong>
                                </p>
                                <p>
                                    Plateforme:{' '}
                                    <strong>
                                        {collectorResult.hosting_platform || 'non detectee'}
                                    </strong>
                                </p>
                                <p>
                                    Uploader:{' '}
                                    <strong>{collectorResult.uploader || 'non detecte'}</strong>
                                </p>
                                <p>
                                    Pays:{' '}
                                    <strong>{formatCountries(collectorResult.geography)}</strong>
                                </p>
                            </div>
                            <div>
                                <h4>Distributions trouvees</h4>
                                {collectorResult.distributions.length > 0 ? (
                                    <ul className="distribution-list">
                                        {collectorResult.distributions.map((distribution) => (
                                            <li key={`${distribution.format}-${distribution.url}`}>
                                                <strong>{distribution.format}</strong>
                                                <span>{distribution.url}</span>
                                            </li>
                                        ))}
                                    </ul>
                                ) : (
                                    <p>Aucun lien CSV/XLSX/API trouve.</p>
                                )}
                            </div>
                        </div>
                    </article>
                ) : null}
            </section>
        </main>
    );
}
