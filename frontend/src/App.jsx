import { useEffect, useMemo, useRef, useState } from 'react';

import { isAbortError, requestJson } from './api/client.js';
import { useApiSession } from './auth/useApiSession.js';
import { useDatasetCatalog } from './catalog/useDatasetCatalog.js';
import CollectedDatasetsSection from './components/CollectedDatasetsSection.jsx';
import { getAcceptedVoteCount, getTotalVoteCount } from './components/RepositoryAcceptedCard.jsx';
import RepositorySearchSection from './components/RepositorySearchSection.jsx';

import { useClassifications } from './jobs/useClassifications.js';
import { useCollectionJobs } from './jobs/useCollectionJobs.js';

const CLASSIFICATION_SUBMISSION_CONCURRENCY = 2;

export default function App() {
    const [activeView, setActiveView] = useState('search');
    const LOCAL_ACCESS = import.meta.env.DEV && import.meta.env.VITE_API_AUTH_MODE === 'local';
    const repositorySearchRunRef = useRef(0);
    const repositorySearchIdRef = useRef(null);
    const repositorySearchAbortRef = useRef(null);
    const { collectedDatasets, collectedLoading, collectedError, loadCollectedDatasets } = useDatasetCatalog();
    const { session, changeToken } = useApiSession(LOCAL_ACCESS);
    const { registerJob, resolveCollection } = useCollectionJobs(session, loadCollectedDatasets);
    const { follow } = useClassifications(session, (item, requestSession, trackingError, requesting) => {
        const registered = registerCandidateCollection(item, requestSession);
        if (repositorySearchIdRef.current !== item.search_id) return;
        setRepositoryCandidates(current => current.map(candidate => candidate.id === item.candidate_id
            ? { ...candidate, item: registered, status: item.classification_status,
                error: item.classification_error ?? '', trackingError, requesting }
            : candidate));
    });
    const apiToken = session.token;
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
    const [apiTokenInput, setApiTokenInput] = useState('');
    const [apiTokenError, setApiTokenError] = useState('');
    function clearPrivateSearch() {
        repositorySearchRunRef.current += 1;
        repositorySearchAbortRef.current?.abort();
        repositorySearchAbortRef.current = null;
        repositorySearchIdRef.current = null;
        setRepositorySearching(false);
        setRepositoryHasSearched(false);
        setRepositoryCandidates([]);
        setLocalRepositoryResults([]);
        setRepositoryWarnings([]);
        setRepositoryError('');
        setRepositoryOrigin(null);
        setRepositoryQuery('');
        setRepositoryResultQuery('');
        setAgreementFilter('all');
    }

    function saveApiToken(event) {
        event.preventDefault();
        const normalizedToken = apiTokenInput.trim();
        if (!normalizedToken) {
            setApiTokenError('Enter an API token.');
            return;
        }

        if (changeToken(normalizedToken)) clearPrivateSearch();
        setApiTokenInput('');
        setApiTokenError('');
    }

    function removeApiToken() {
        changeToken('');
        clearPrivateSearch();
        setApiTokenInput('');
        setApiTokenError('');
    }

    useEffect(() => () => {
        repositorySearchRunRef.current += 1;
        repositorySearchAbortRef.current?.abort();
    }, []);

    function registerCandidateCollection(item, requestSession) {
        const collection = item.automatic_collection;
        if (!collection?.job?.id) return item;
        registerJob(collection.job, requestSession);
        // Store only the reference; the job manager owns every job status.
        return { ...item, automatic_collection: { jobId: collection.job.id } };
    }

    async function classifyRepositoryCandidates(candidates, runId, abortController, requestSession) {
        let next = 0;
        async function submitNext() {
            while (repositorySearchRunRef.current === runId && requestSession.isCurrent() &&
                !abortController.signal.aborted && next < candidates.length) {
                const candidate = candidates[next++];
                await follow(candidate.item, requestSession, { submit: true });
            }
        }
        await Promise.all(Array.from(
            { length: Math.min(CLASSIFICATION_SUBMISSION_CONCURRENCY, candidates.length) }, submitNext,
        ));
    }

    async function restoreAnalysis(manual = false) {
        const requestSession = session;
        if (!requestSession.local && !requestSession.token) return;
        const runId = ++repositorySearchRunRef.current;
        setRepositorySearching(false);
        repositorySearchAbortRef.current?.abort();
        repositorySearchAbortRef.current = null;
        try {
            const data = await requestJson('/collector/repository-analyses/latest', { session: requestSession });
            if (!requestSession.isCurrent() || repositorySearchRunRef.current !== runId) return;
            if (typeof data?.search_id !== 'string' || typeof data.query !== 'string' ||
                !Array.isArray(data.items) || data.items.some(item => item.search_id !== data.search_id ||
                    typeof item.candidate_id !== 'string')) throw new Error('The saved analysis is incomplete.');
            repositorySearchIdRef.current = data.search_id;
            setRepositoryOrigin('online');
            setRepositoryHasSearched(true);
            setRepositoryQuery(current => manual || !current ? data.query : current);
            setRepositorySearching(false);
            setRepositoryWarnings([]);
            setLocalRepositoryResults([]);
            setAgreementFilter('all');
            setRepositoryResultQuery(data.query);
            setRepositoryError('');
            setRepositoryCandidates(data.items.map(item => ({
                id: item.candidate_id, item: registerCandidateCollection(item, requestSession),
                status: item.classification_status, error: item.classification_error ?? '',
            })));
            for (const item of data.items) void follow(item, requestSession);
        } catch (error) {
            if (!isAbortError(error) && requestSession.isCurrent() &&
                repositorySearchRunRef.current === runId && (manual || error.status !== 404)) {
                setRepositoryError(`Unable to restore the last analysis: ${error.message}`);
            }
        }
    }

    useEffect(() => { void restoreAnalysis(); }, [session]);

    function analyzeCandidate(candidate) {
        void follow(candidate.item, session, { submit: true, retry: candidate.status === 'error' });
    }

    async function searchRepositories(event) {
        event.preventDefault();

        if (repositoryAnalysisInProgress && repositoryQuery.trim() === repositoryResultQuery) {
            return;
        }

        const query = repositoryQuery.trim();

        if (!query) {
            setRepositoryError('Enter a search query to continue.');
            return;
        }

        const requestSession = session;
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
            const responsePayload = await requestJson('/collector/search-datasets', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query }),
                signal: abortController.signal,
                session: requestSession,
            });

            if (!requestSession.isCurrent() || repositorySearchRunRef.current !== runId) return;

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
                item: registerCandidateCollection(item, requestSession),
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
                    abortController,
                    requestSession,
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

    const repositoryStatusCounts = useMemo(
        () =>
            repositoryCandidates.reduce(
                (counts, candidate) => ({
                    ...counts,
                    [candidate.status]: (counts[candidate.status] ?? 0) + 1,
                }),
                {
                    pending: 0,
                    queued: 0,
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
                    ['pending', 'queued', 'classifying'].includes(candidate.status),
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
            }).map((candidate) => ({
                ...candidate,
                item: {
                    ...candidate.item,
                    automatic_collection: resolveCollection(candidate.item.automatic_collection),
                },
            })),
        [agreementFilter, repositoryCandidates, resolveCollection],
    );

    const repositoryClassificationErrors = useMemo(
        () => repositoryCandidates.filter((candidate) => candidate.status === 'error'),
        [repositoryCandidates],
    );

    const repositoryAnalysisInProgress =
        repositorySearching || repositoryCandidates.some(candidate => candidate.requesting) ||
        repositoryStatusCounts.queued > 0 ||
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
                analyzeCandidate={analyzeCandidate}
                restoreAnalysis={() => restoreAnalysis(true)}
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
