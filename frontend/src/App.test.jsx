import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from './App.jsx';

const SEARCH_ID = '11111111-1111-4111-8111-111111111111';
const CANDIDATE_ID = '22222222-2222-4222-8222-222222222222';

function jsonResponse(payload, { ok = true, status = 200 } = {}) {
    return {
        ok,
        status,
        json: async () => payload,
    };
}

function mockApi(searchHandler) {
    global.fetch = vi.fn((input, options = {}) => {
        const url = String(input);
        if (url.endsWith('/sources')) {
            return Promise.resolve(jsonResponse({ items: [] }));
        }
        if (url.endsWith('/collector/collected-datasets')) {
            return Promise.resolve(jsonResponse({ items: [] }));
        }
        return searchHandler(url, options);
    });
}

function submitSearch(query = 'malaria mortality') {
    fireEvent.change(screen.getByLabelText('Rechercher un dataset santé'), {
        target: { value: query },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Rechercher' }));
}

beforeEach(() => {
    window.sessionStorage.setItem('global-health-api-token', 'frontend-test-token');
});

afterEach(() => {
    cleanup();
    window.sessionStorage.clear();
    vi.restoreAllMocks();
});

describe('database-first dataset search', () => {
    it('shows local results immediately without classification controls or calls', async () => {
        mockApi((url) => {
            if (url.endsWith('/collector/search-datasets')) {
                return Promise.resolve(
                    jsonResponse({
                        search_id: SEARCH_ID,
                        query: 'malaria mortality',
                        origin: 'database',
                        warnings: [],
                        items: [
                            {
                                id: 42,
                                dataset_url: 'https://catalog.example.org/malaria',
                                title: 'Local malaria dataset',
                                description: 'Annual mortality observations.',
                                publisher: 'Health Institute',
                                hosting_platform: 'CKAN',
                                geography: ['Senegal'],
                                distributions: [],
                            },
                        ],
                    }),
                );
            }
            throw new Error(`Unexpected request: ${url}`);
        });
        render(<App />);

        submitSearch();

        expect(await screen.findByText('Local malaria dataset')).toBeInTheDocument();
        expect(screen.getByText('Déjà dans la base')).toBeInTheDocument();
        expect(
            screen.getByText('Résultats trouvés dans le catalogue local'),
        ).toBeInTheDocument();
        expect(screen.queryByText('Accord IA')).not.toBeInTheDocument();
        expect(screen.queryByText(/votes favorables/)).not.toBeInTheDocument();
        expect(
            global.fetch.mock.calls.some(([url]) =>
                String(url).includes('/collector/repository-candidates/'),
            ),
        ).toBe(false);
    });

    it('keeps the online progressive classification flow', async () => {
        let resolveClassification;
        const classificationResponse = new Promise((resolve) => {
            resolveClassification = resolve;
        });
        const onlineItem = {
            candidate_id: CANDIDATE_ID,
            search_id: SEARCH_ID,
            title: 'Online malaria dataset',
            description: 'Annual observations.',
            url: 'https://example.org/malaria',
            source: 'DataCite',
            classification_status: 'pending',
            publisher: 'Example Institute',
            date: '2025',
            doi: '',
            keywords: ['malaria'],
            metadata: {},
        };
        mockApi((url) => {
            if (url.endsWith('/collector/search-datasets')) {
                return Promise.resolve(
                    jsonResponse({
                        search_id: SEARCH_ID,
                        query: 'malaria mortality',
                        origin: 'online',
                        items: [onlineItem],
                        warnings: [],
                    }),
                );
            }
            if (
                url.endsWith(
                    `/collector/repository-candidates/${CANDIDATE_ID}/classify`,
                )
            ) {
                return classificationResponse;
            }
            throw new Error(`Unexpected request: ${url}`);
        });
        render(<App />);

        submitSearch();

        expect(await screen.findByText('Analyse IA…')).toBeInTheDocument();
        expect(screen.getByText('Aucun résultat local')).toBeInTheDocument();

        await act(async () => {
            resolveClassification(
                jsonResponse({
                    ...onlineItem,
                    classification: {
                        accepted: true,
                        relevance_label: 'relevant',
                        reason: 'Matches the query.',
                        missing_information: [],
                        ensemble: {
                            successful_votes: 1,
                            accepted_votes: 1,
                            failed_votes: 0,
                            decision_reason: 'enough_accept_votes',
                            voters: [],
                        },
                    },
                    automatic_collection: {
                        state: 'saved',
                        job: {
                            id: 12,
                            status: 'done',
                            saved_count: 1,
                        },
                    },
                }),
            );
        });

        expect(await screen.findByText('Candidat accepté 1/1')).toBeInTheDocument();
        expect(
            screen.getByText('Dataset sauvegardé dans le catalogue local'),
        ).toBeInTheDocument();
        expect(screen.getByText('Accord IA')).toBeInTheDocument();
        const classificationCall = global.fetch.mock.calls.find(([url]) =>
            String(url).includes(`/repository-candidates/${CANDIDATE_ID}/classify`),
        );
        expect(classificationCall?.[1]?.body).toBeUndefined();
        expect(classificationCall?.[1]?.headers?.Authorization).toBe(
            'Bearer frontend-test-token',
        );
    });

    it('polls automatic collection until the accepted candidate is saved', async () => {
        const onlineItem = {
            candidate_id: CANDIDATE_ID,
            search_id: SEARCH_ID,
            title: 'Online malaria dataset',
            description: 'Annual observations.',
            url: 'https://example.org/malaria',
            source: 'DataCite',
            classification_status: 'pending',
            publisher: 'Example Institute',
            date: '2025',
            doi: '',
            keywords: ['malaria'],
            metadata: {},
        };
        mockApi((url) => {
            if (url.endsWith('/collector/search-datasets')) {
                return Promise.resolve(
                    jsonResponse({
                        search_id: SEARCH_ID,
                        query: 'malaria mortality',
                        origin: 'online',
                        items: [onlineItem],
                        warnings: [],
                    }),
                );
            }
            if (
                url.endsWith(
                    `/collector/repository-candidates/${CANDIDATE_ID}/classify`,
                )
            ) {
                return Promise.resolve(
                    jsonResponse({
                        ...onlineItem,
                        classification: {
                            accepted: true,
                            relevance_label: 'relevant',
                            reason: 'Matches the query.',
                            missing_information: [],
                            ensemble: {
                                successful_votes: 1,
                                accepted_votes: 1,
                                failed_votes: 0,
                                decision_reason: 'enough_accept_votes',
                                voters: [],
                            },
                        },
                        automatic_collection: {
                            state: 'pending',
                            job: {
                                id: 55,
                                status: 'pending',
                                saved_count: 0,
                            },
                        },
                    }),
                );
            }
            if (url.endsWith('/collector/collection-jobs/55')) {
                return Promise.resolve(
                    jsonResponse({
                        job: {
                            id: 55,
                            status: 'done',
                            saved_count: 1,
                        },
                    }),
                );
            }
            throw new Error(`Unexpected request: ${url}`);
        });
        render(<App />);

        submitSearch();

        expect(
            await screen.findByText('Collecte automatique en attente'),
        ).toBeInTheDocument();
        expect(
            await screen.findByText('Dataset sauvegardé dans le catalogue local', {}, {
                timeout: 2500,
            }),
        ).toBeInTheDocument();
        expect(
            global.fetch.mock.calls.some(([url]) =>
                String(url).endsWith('/collector/collection-jobs/55'),
            ),
        ).toBe(true);
    });

    it('leaves rejected candidates unscheduled', async () => {
        const onlineItem = {
            candidate_id: CANDIDATE_ID,
            search_id: SEARCH_ID,
            title: 'Unrelated dataset',
            description: 'Unrelated observations.',
            url: 'https://example.org/unrelated',
            source: 'DataCite',
            classification_status: 'pending',
            publisher: '',
            date: '',
            doi: '',
            keywords: [],
            metadata: {},
        };
        mockApi((url) => {
            if (url.endsWith('/collector/search-datasets')) {
                return Promise.resolve(
                    jsonResponse({
                        search_id: SEARCH_ID,
                        query: 'malaria mortality',
                        origin: 'online',
                        items: [onlineItem],
                        warnings: [],
                    }),
                );
            }
            if (
                url.endsWith(
                    `/collector/repository-candidates/${CANDIDATE_ID}/classify`,
                )
            ) {
                return Promise.resolve(
                    jsonResponse({
                        ...onlineItem,
                        classification: {
                            accepted: false,
                            relevance_label: 'not_relevant',
                            reason: 'Does not match the query.',
                            missing_information: [],
                            ensemble: {},
                        },
                        automatic_collection: null,
                    }),
                );
            }
            throw new Error(`Unexpected request: ${url}`);
        });
        render(<App />);

        submitSearch();

        expect(await screen.findByText(/1 a été rejeté/)).toBeInTheDocument();
        expect(
            global.fetch.mock.calls.some(([url]) =>
                String(url).includes('/collector/collection-jobs/'),
            ),
        ).toBe(false);
    });

    it('shows the loading and empty online states', async () => {
        let resolveSearch;
        const searchResponse = new Promise((resolve) => {
            resolveSearch = resolve;
        });
        mockApi((url) => {
            if (url.endsWith('/collector/search-datasets')) {
                return searchResponse;
            }
            throw new Error(`Unexpected request: ${url}`);
        });
        render(<App />);

        submitSearch();
        expect(await screen.findByText('Recherche des candidats')).toBeInTheDocument();

        await act(async () => {
            resolveSearch(
                jsonResponse({
                    search_id: SEARCH_ID,
                    query: 'malaria mortality',
                    origin: 'online',
                    items: [],
                    warnings: [],
                }),
            );
        });

        expect(
            await screen.findByText('Aucun dataset accepté pour cette recherche.'),
        ).toBeInTheDocument();
    });

    it('shows API search errors', async () => {
        mockApi((url) => {
            if (url.endsWith('/collector/search-datasets')) {
                return Promise.resolve(
                    jsonResponse(
                        { detail: 'Database search failed.' },
                        { ok: false, status: 500 },
                    ),
                );
            }
            throw new Error(`Unexpected request: ${url}`);
        });
        render(<App />);

        submitSearch();

        expect(await screen.findByText('Recherche impossible')).toBeInTheDocument();
        expect(screen.getByText('Database search failed.')).toBeInTheDocument();
    });
});

describe('protected API access', () => {
    it('requires a runtime token and never starts a protected request without one', async () => {
        window.sessionStorage.clear();
        mockApi((url) => {
            throw new Error(`Unexpected protected request: ${url}`);
        });
        render(<App />);

        submitSearch();

        expect(
            await screen.findByText('Un jeton API est requis pour cette opération.'),
        ).toBeInTheDocument();
        expect(
            global.fetch.mock.calls.some(([url]) =>
                String(url).endsWith('/collector/search-datasets'),
            ),
        ).toBe(false);
    });

    it('uses a token entered at runtime for protected requests', async () => {
        window.sessionStorage.clear();
        mockApi((url) => {
            if (url.endsWith('/collector/search-datasets')) {
                return Promise.resolve(
                    jsonResponse({
                        search_id: SEARCH_ID,
                        query: 'malaria mortality',
                        origin: 'database',
                        items: [],
                    }),
                );
            }
            throw new Error(`Unexpected request: ${url}`);
        });
        render(<App />);

        fireEvent.change(screen.getByLabelText('Jeton API'), {
            target: { value: 'runtime-test-token' },
        });
        fireEvent.click(screen.getByRole('button', { name: 'Enregistrer' }));
        submitSearch();

        await waitFor(() => {
            expect(
                global.fetch.mock.calls.some(
                    ([url, options]) =>
                        String(url).endsWith('/collector/search-datasets') &&
                        options?.headers?.Authorization === 'Bearer runtime-test-token',
                ),
            ).toBe(true);
        });
        expect(window.sessionStorage.getItem('global-health-api-token')).toBe(
            'runtime-test-token',
        );
    });
});
