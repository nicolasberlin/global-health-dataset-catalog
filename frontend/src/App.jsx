import { useEffect, useMemo, useRef, useState } from 'react';

import CollectedDatasetsSection from './components/CollectedDatasetsSection.jsx';
import { getAcceptedVoteCount, getTotalVoteCount } from './components/RepositoryAcceptedCard.jsx';
import RepositorySearchSection from './components/RepositorySearchSection.jsx';

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
    const [activeView, setActiveView] = useState('search');
    const LOCAL_ACCESS = import.meta.env.DEV && import.meta.env.VITE_API_AUTH_MODE === 'local';
    const repositorySearchRunRef = useRef(0);
    const repositorySearchIdRef = useRef(null);
    const repositorySearchAbortRef = useRef(null);
    const [collectedDatasets, setCollectedDatasets] = useState([]);
    const [collectedLoading, setCollectedLoading] = useState(true);
    const [collectedError, setCollectedError] = useState('');
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
            setApiTokenError('Enter an API token.');
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
        if (LOCAL_ACCESS) return fetch(url, options);
        const currentToken = apiTokenRef.current;
        if (!currentToken) {
            throw new Error('An API token is required for this operation.');
        }

        return fetch(url, {
            ...options,
            headers: {
                ...(options.headers ?? {}),
                Authorization: `Bearer ${currentToken}`,
            },
        });
    }

    async function loadCollectedDatasets({ silent = false } = {}) {
        try {
            if (!silent) {
                setCollectedLoading(true);
            }
            setCollectedError('');

            const response = await fetch(`${API_BASE_URL}/collector/collected-datasets`);
            if (!response.ok) {
                throw new Error('Unable to load catalog datasets.');
            }

            const data = await response.json();
            setCollectedDatasets(data.items ?? []);
        } catch (exception) {
            setCollectedDatasets([]);
            setCollectedError(exception instanceof Error ? exception.message : 'Unknown error');
        } finally {
            if (!silent) {
                setCollectedLoading(false);
            }
        }
    }

    useEffect(() => {
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

            throw new Error('Automatic collection is taking too long.');
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
                            : 'Unable to track automatic collection.',
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
                                'AI classification failed.',
                            ),
                        );
                    }

                    if (typeof responsePayload?.classification?.accepted !== 'boolean') {
                        throw new Error('The classification response is incomplete.');
                    }

                    if (
                        responsePayload.candidate_id !== candidate.id ||
                        responsePayload.search_id !== searchId
                    ) {
                        throw new Error('The classification response no longer matches this search.');
                    }

                    if (
                        responsePayload.classification.accepted &&
                        !responsePayload.automatic_collection
                    ) {
                        throw new Error(
                            'The automatic collection response is incomplete.',
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
                                : 'Classification error.',
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
            setRepositoryError('Enter a search query to continue.');
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
                    getResponseError(responsePayload, 'Repository search failed.'),
                );
            }

            if (repositorySearchRunRef.current !== runId) {
                return;
            }

            if (!['database', 'online'].includes(responsePayload?.origin)) {
                throw new Error('The search response is incomplete.');
            }
            if (typeof responsePayload?.search_id !== 'string') {
                throw new Error('The search response is incomplete.');
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
                throw new Error('The search response is incomplete.');
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
                exception instanceof Error ? exception.message : 'Search error.',
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
            throw new Error(errorPayload?.detail ?? 'Unable to read collection status.');
        }

        const data = await response.json();
        return data.job;
    }

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
                    getTotalVoteCount(candidate.item.classification) === 3 &&
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

    return (
        <main className="app-shell">
            <header className="app-header">
                <div className="title-block">
                    <span className="eyebrow">Global Health</span>
                    <h1>Dataset Catalog</h1>
                    <p>Find health datasets and access their source files.</p>
                </div>

            </header>

            <nav className="catalog-navigation" aria-label="Catalog navigation">
                <button type="button" aria-pressed={activeView === 'search'}
                    onClick={() => setActiveView('search')}>Search datasets</button>
                <button type="button" aria-pressed={activeView === 'catalog'}
                    onClick={() => setActiveView('catalog')}>Catalog</button>
            </nav>

            {!LOCAL_ACCESS && <section className="api-access-bar" aria-label="Protected API access">
                <div className="api-access-status">
                    <strong>API access</strong>
                    <span>{apiToken ? 'Token active for this session' : 'Token required'}</span>
                </div>
                <form className="api-access-form" onSubmit={saveApiToken}>
                    <label htmlFor="api-token">API token</label>
                    <input
                        id="api-token"
                        type="password"
                        autoComplete="off"
                        value={apiTokenInput}
                        onChange={(event) => setApiTokenInput(event.target.value)}
                    />
                    <button type="submit" className="secondary-button">
                        Save
                    </button>
                    {apiToken ? (
                        <button type="button" onClick={removeApiToken}>
                            Remove
                        </button>
                    ) : null}
                </form>
                {apiTokenError ? <p className="api-access-error">{apiTokenError}</p> : null}
            </section>}

            <div hidden={activeView !== 'search'}>
            <RepositorySearchSection
                collectedDatasets={collectedDatasets}
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
            </div>

            <div hidden={activeView !== 'catalog'}>
            <CollectedDatasetsSection
                collectedDatasets={collectedDatasets}
                collectedError={collectedError}
                collectedLoading={collectedLoading}
                loadCollectedDatasets={loadCollectedDatasets}
            />
            </div>

        </main>
    );
}
