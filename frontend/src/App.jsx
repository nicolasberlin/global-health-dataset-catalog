import { useEffect, useMemo, useRef, useState } from 'react';

import { isAbortError, requestJson } from './api/client.js';
import { useApiSession } from './auth/useApiSession.js';
import { useDatasetCatalog } from './catalog/useDatasetCatalog.js';
import CollectedDatasetsSection from './components/CollectedDatasetsSection.jsx';
import { getVoteAgreement } from './components/RepositoryAcceptedCard.jsx';
import RepositorySearchSection from './components/RepositorySearchSection.jsx';

import { useSearchProgress } from './jobs/useSearchProgress.js';

export default function App() {
    const [activeView, setActiveView] = useState('search');
    const repositorySearchRunRef = useRef(0);
    const repositorySearchIdRef = useRef(null);
    const repositorySearchAbortRef = useRef(null);
    const catalog = useDatasetCatalog();
    const { loadCollectedDatasets } = catalog;
    const { session, status: sessionStatus, error: sessionError, reconnect } = useApiSession();
    const { followSearch, analyze, retryCollection } = useSearchProgress(session,
        (searchId, items, requestSession, trackingError) => {
            if (!requestSession.isCurrent() || repositorySearchIdRef.current !== searchId) return;
            setRepositoryCandidates(items.map(item => ({
                id: item.candidate_id, item, status: item.classification_status,
                error: item.classification_error ?? '',
                trackingError: item.trackingError || trackingError, requesting: item.requesting,
            })));
        }, loadCollectedDatasets);
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
    useEffect(() => () => {
        repositorySearchRunRef.current += 1;
        repositorySearchAbortRef.current?.abort();
    }, []);

    useEffect(() => {
        if (session.mode !== 'public' || sessionStatus === 'ready') return;
        repositorySearchRunRef.current += 1;
        repositorySearchAbortRef.current?.abort();
        repositorySearchIdRef.current = null;
        setRepositoryCandidates([]);
        setLocalRepositoryResults([]);
        setRepositoryHasSearched(false);
        setRepositorySearching(false);
        setRepositoryError('');
        setRepositoryWarnings([]);
    }, [session, sessionStatus]);

    async function restoreAnalysis(manual = false) {
        const requestSession = session;
        if (!requestSession.ready || !requestSession.isCurrent() ||
            (requestSession.mode !== 'public' && !requestSession.local && !requestSession.token)) return;
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
                id: item.candidate_id, item: item,
                status: item.classification_status, error: item.classification_error ?? '',
            })));
            followSearch(data.search_id, data.items, requestSession);
        } catch (error) {
            if (!isAbortError(error) && requestSession.isCurrent() &&
                repositorySearchRunRef.current === runId && (manual || error.status !== 404)) {
                setRepositoryError(`Unable to restore the last analysis: ${error.message}`);
            }
        }
    }

    useEffect(() => { void restoreAnalysis(); }, [session, sessionStatus]);

    function analyzeCandidate(candidate) {
        void analyze(candidate.item, session);
    }

    async function searchRepositories(event) {
        event.preventDefault();
        if (!session.ready || !session.isCurrent()) return;

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
                item: item,
                status: item.classification_status ?? 'pending',
                error: item.classification_error ?? '',
            }));

            setRepositoryCandidates(candidates);
            setRepositoryWarnings(
                Array.isArray(responsePayload?.warnings) ? responsePayload.warnings : [],
            );

            followSearch(searchId, onlineItems, requestSession);
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

            if (repositorySearchAbortRef.current === abortController) {
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

                return getVoteAgreement(candidate.item.classification) === agreementFilter;
            }),
        [agreementFilter, repositoryCandidates],
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

            <div hidden={activeView !== 'search'}>
            {session.mode === 'public' && sessionStatus !== 'ready' && (
                <div className="repository-message" role={sessionStatus === 'preparing' ? 'status' : 'alert'}>
                    <span>{sessionStatus === 'preparing' ? 'Preparing visitor access…' : sessionError}</span>
                    {sessionStatus !== 'preparing' && <button type="button" onClick={reconnect}>
                        {sessionStatus === 'expired' ? 'Continue' : 'Retry access'}
                    </button>}
                </div>
            )}
            <RepositorySearchSection
                accessReady={sessionStatus === 'ready'}
                analyzeCandidate={analyzeCandidate}
                retryCollection={candidate => retryCollection(candidate.item, session)}
                restoreAnalysis={() => restoreAnalysis(true)}
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
                {...catalog}
            />
            </div>

        </main>
    );
}
