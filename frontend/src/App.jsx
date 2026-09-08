import { useEffect, useMemo, useRef, useState } from 'react';

import CollectedDatasetsSection from './components/CollectedDatasetsSection.jsx';
import { getAcceptedVoteCount } from './components/RepositoryAcceptedCard.jsx';
import RepositorySearchSection from './components/RepositorySearchSection.jsx';
import SourceCatalogSection from './components/SourceCatalogSection.jsx';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8001';
const REPOSITORY_CLASSIFICATION_CONCURRENCY = 2;
const API_TOKEN_STORAGE_KEY = 'global-health-api-token';

function storedApiToken() {
    try {
        return window.sessionStorage.getItem(API_TOKEN_STORAGE_KEY) ?? '';
    } catch {
        return '';
    }
}

function normalizeSearchValue(value) {
    return String(value ?? '')
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLowerCase();
}

function wait(milliseconds) {
    return new Promise((resolve) => {
        window.setTimeout(resolve, milliseconds);
    });
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

export default function App() {
    const repositorySearchRunRef = useRef(0);
    const repositorySearchIdRef = useRef(null);
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
    const [repositoryQuery, setRepositoryQuery] = useState('');
    const [repositoryResultQuery, setRepositoryResultQuery] = useState('');
    const [repositoryOrigin, setRepositoryOrigin] = useState(null);
    const [localRepositoryResults, setLocalRepositoryResults] = useState([]);
    const [repositoryCandidates, setRepositoryCandidates] = useState([]);
    const [repositoryWarnings, setRepositoryWarnings] = useState([]);
    const [repositoryError, setRepositoryError] = useState('');
    const [repositorySearching, setRepositorySearching] = useState(false);
    const [repositoryHasSearched, setRepositoryHasSearched] = useState(false);
    const [agreementFilter, setAgreementFilter] = useState('all');
    const [apiToken, setApiToken] = useState(storedApiToken);
    const [apiTokenInput, setApiTokenInput] = useState('');
    const [apiTokenError, setApiTokenError] = useState('');
    const apiTokenRef = useRef(apiToken);

    function saveApiToken(event) {
        event.preventDefault();
        const normalizedToken = apiTokenInput.trim();
        if (!normalizedToken) {
            setApiTokenError('Saisis un jeton API.');
            return;
        }

        window.sessionStorage.setItem(API_TOKEN_STORAGE_KEY, normalizedToken);
        apiTokenRef.current = normalizedToken;
        setApiToken(normalizedToken);
        setApiTokenInput('');
        setApiTokenError('');
    }

    function removeApiToken() {
        repositorySearchRunRef.current += 1;
        repositorySearchAbortRef.current?.abort();
        window.sessionStorage.removeItem(API_TOKEN_STORAGE_KEY);
        apiTokenRef.current = '';
        setApiToken('');
        setApiTokenInput('');
        setApiTokenError('');
    }

    async function protectedFetch(url, options = {}) {
        const currentToken = apiTokenRef.current;
        if (!currentToken) {
            throw new Error('Un jeton API est requis pour cette opération.');
        }

        return fetch(url, {
            ...options,
            headers: {
                ...(options.headers ?? {}),
                Authorization: `Bearer ${currentToken}`,
            },
        });
    }

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

    function updateRepositoryCandidate(runId, searchId, candidateId, update) {
        if (
            repositorySearchRunRef.current !== runId ||
            repositorySearchIdRef.current !== searchId
        ) {
            return;
        }

        setRepositoryCandidates((currentCandidates) =>
            currentCandidates.map((candidate) =>
                candidate.id === candidateId ? { ...candidate, ...update } : candidate,
            ),
        );
    }

    function updateRepositoryCandidateCollection(
        runId,
        searchId,
        candidateId,
        automaticCollection,
    ) {
        if (
            repositorySearchRunRef.current !== runId ||
            repositorySearchIdRef.current !== searchId
        ) {
            return;
        }

        setRepositoryCandidates((currentCandidates) =>
            currentCandidates.map((candidate) =>
                candidate.id === candidateId
                    ? {
                          ...candidate,
                          item: {
                              ...candidate.item,
                              automatic_collection: automaticCollection,
                          },
                      }
                    : candidate,
            ),
        );
    }

    async function pollAutomaticRepositoryCollection(
        candidateId,
        initialJob,
        runId,
        searchId,
        signal,
    ) {
        const maxAttempts = 80;

        try {
            for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
                await wait(attempt === 0 ? 700 : 1500);
                if (
                    signal.aborted ||
                    repositorySearchRunRef.current !== runId ||
                    repositorySearchIdRef.current !== searchId
                ) {
                    return;
                }

                const job = await loadCollectionJob(initialJob.id);
                if (job.status === 'done') {
                    const state = job.saved_count > 0 ? 'saved' : 'empty';
                    updateRepositoryCandidateCollection(runId, searchId, candidateId, {
                        state,
                        job,
                    });
                    if (state === 'saved') {
                        await loadCollectedDatasets({ silent: true });
                    }
                    return;
                }

                if (job.status === 'error') {
                    updateRepositoryCandidateCollection(runId, searchId, candidateId, {
                        state: 'error',
                        job,
                    });
                    return;
                }

                updateRepositoryCandidateCollection(runId, searchId, candidateId, {
                    state: job.status,
                    job,
                });
            }

            throw new Error('La collecte automatique prend trop de temps.');
        } catch (exception) {
            if (isAbortError(exception) || signal.aborted) {
                return;
            }

            updateRepositoryCandidateCollection(runId, searchId, candidateId, {
                state: 'error',
                job: {
                    ...initialJob,
                    status: 'error',
                    error:
                        exception instanceof Error
                            ? exception.message
                            : 'Impossible de suivre la collecte automatique.',
                },
            });
        }
    }

    async function classifyRepositoryCandidates(
        candidates,
        runId,
        searchId,
        abortController,
    ) {
        let nextCandidateIndex = 0;
        const { signal } = abortController;

        async function classificationWorker() {
            while (
                repositorySearchRunRef.current === runId &&
                repositorySearchIdRef.current === searchId &&
                !signal.aborted
            ) {
                const candidateIndex = nextCandidateIndex;
                nextCandidateIndex += 1;

                if (candidateIndex >= candidates.length) {
                    return;
                }

                const candidate = candidates[candidateIndex];
                updateRepositoryCandidate(runId, searchId, candidate.id, {
                    status: 'classifying',
                    error: '',
                });

                try {
                    const response = await protectedFetch(
                        `${API_BASE_URL}/collector/repository-candidates/${candidate.id}/classify`,
                        {
                            method: 'POST',
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

                    if (
                        responsePayload.candidate_id !== candidate.id ||
                        responsePayload.search_id !== searchId
                    ) {
                        throw new Error('La réponse de classification ne correspond plus.');
                    }

                    if (
                        responsePayload.classification.accepted &&
                        !responsePayload.automatic_collection
                    ) {
                        throw new Error(
                            'La réponse de collecte automatique est incomplète.',
                        );
                    }

                    updateRepositoryCandidate(runId, searchId, candidate.id, {
                        item: responsePayload,
                        status: responsePayload.classification.accepted
                            ? 'accepted'
                            : 'rejected',
                        error: '',
                    });

                    const automaticCollection = responsePayload.automatic_collection;
                    if (
                        responsePayload.classification.accepted &&
                        ['pending', 'running'].includes(automaticCollection?.state) &&
                        automaticCollection?.job?.id
                    ) {
                        void pollAutomaticRepositoryCollection(
                            candidate.id,
                            automaticCollection.job,
                            runId,
                            searchId,
                            signal,
                        );
                    }
                } catch (exception) {
                    if (isAbortError(exception) || signal.aborted) {
                        return;
                    }

                    updateRepositoryCandidate(runId, searchId, candidate.id, {
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
        repositorySearchIdRef.current = null;
        repositorySearchAbortRef.current = abortController;
        setRepositorySearching(true);
        setRepositoryHasSearched(true);
        setRepositoryResultQuery(query);
        setRepositoryOrigin(null);
        setLocalRepositoryResults([]);
        setRepositoryCandidates([]);
        setRepositoryWarnings([]);
        setRepositoryError('');

        let classificationStarted = false;
        try {
            const response = await protectedFetch(`${API_BASE_URL}/collector/search-datasets`, {
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

            if (!['database', 'online'].includes(responsePayload?.origin)) {
                throw new Error('La réponse de recherche est incomplète.');
            }
            if (typeof responsePayload?.search_id !== 'string') {
                throw new Error('La réponse de recherche est incomplète.');
            }

            const searchId = responsePayload.search_id;
            repositorySearchIdRef.current = searchId;

            setRepositoryOrigin(responsePayload.origin);
            if (responsePayload.origin === 'database') {
                setLocalRepositoryResults(
                    Array.isArray(responsePayload.items) ? responsePayload.items : [],
                );
                setRepositoryWarnings([]);
                return;
            }

            const onlineItems = Array.isArray(responsePayload.items)
                ? responsePayload.items
                : [];
            if (
                onlineItems.some(
                    (item) =>
                        typeof item?.candidate_id !== 'string' ||
                        item.search_id !== searchId,
                )
            ) {
                throw new Error('La réponse de recherche est incomplète.');
            }

            const candidates = onlineItems.map((item) => ({
                id: item.candidate_id,
                item,
                status: item.classification_status ?? 'pending',
                error: item.classification_error ?? '',
            }));

            setRepositoryCandidates(candidates);
            setRepositoryWarnings(
                Array.isArray(responsePayload?.warnings) ? responsePayload.warnings : [],
            );

            if (candidates.length > 0) {
                classificationStarted = true;
                void classifyRepositoryCandidates(
                    candidates,
                    runId,
                    searchId,
                    abortController,
                );
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
        const response = await protectedFetch(
            `${API_BASE_URL}/collector/collection-jobs/${jobId}`,
        );
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

            const response = await protectedFetch(`${API_BASE_URL}/collector/collection-jobs`, {
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

            <section className="api-access-bar" aria-label="Accès API protégé">
                <div className="api-access-status">
                    <strong>Accès API</strong>
                    <span>{apiToken ? 'Jeton actif pour cette session' : 'Jeton requis'}</span>
                </div>
                <form className="api-access-form" onSubmit={saveApiToken}>
                    <label htmlFor="api-token">Jeton API</label>
                    <input
                        id="api-token"
                        type="password"
                        autoComplete="off"
                        value={apiTokenInput}
                        onChange={(event) => setApiTokenInput(event.target.value)}
                    />
                    <button type="submit" className="secondary-button">
                        Enregistrer
                    </button>
                    {apiToken ? (
                        <button type="button" onClick={removeApiToken}>
                            Retirer
                        </button>
                    ) : null}
                </form>
                {apiTokenError ? <p className="api-access-error">{apiTokenError}</p> : null}
            </section>

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

            <RepositorySearchSection
                acceptedRepositoryCandidates={acceptedRepositoryCandidates}
                agreementFilter={agreementFilter}
                inProgressRepositoryCandidates={inProgressRepositoryCandidates}
                repositoryAnalysisInProgress={repositoryAnalysisInProgress}
                repositoryCandidates={repositoryCandidates}
                repositoryClassificationErrors={repositoryClassificationErrors}
                repositoryError={repositoryError}
                repositoryHasSearched={repositoryHasSearched}
                repositoryOrigin={repositoryOrigin}
                repositoryQuery={repositoryQuery}
                repositoryResultQuery={repositoryResultQuery}
                repositorySearching={repositorySearching}
                repositoryStatusCounts={repositoryStatusCounts}
                repositoryWarnings={repositoryWarnings}
                localRepositoryResults={localRepositoryResults}
                searchRepositories={searchRepositories}
                setAgreementFilter={setAgreementFilter}
                setRepositoryQuery={setRepositoryQuery}
            />

            <SourceCatalogSection
                activeCollectionJob={activeCollectionJob}
                apiBaseUrl={API_BASE_URL}
                collectSource={collectSource}
                collectingSourceId={collectingSourceId}
                collectionNotice={collectionNotice}
                emptyState={emptyState}
                error={error}
                filteredSources={filteredSources}
                loadSources={loadSources}
                loading={loading}
                searchTerm={searchTerm}
                selectedTheme={selectedTheme}
                setSearchTerm={setSearchTerm}
                setSelectedTheme={setSelectedTheme}
                sources={sources}
                statusTone={statusTone}
                themes={themes}
            />

            <CollectedDatasetsSection
                collectedDatasets={collectedDatasets}
                collectedError={collectedError}
                collectedLoading={collectedLoading}
                loadCollectedDatasets={loadCollectedDatasets}
            />

        </main>
    );
}
