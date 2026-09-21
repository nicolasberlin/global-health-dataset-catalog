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
        if (url.endsWith('/repository-analyses/latest')) return Promise.resolve(jsonResponse({ detail: 'None' }, { ok: false, status: 404 }));
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
    fireEvent.change(screen.getByLabelText('Search for a health dataset'), {
        target: { value: query },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
}

beforeEach(() => {
    window.sessionStorage.setItem('global-health-api-token', 'frontend-test-token');
});

afterEach(() => {
    cleanup();
    window.sessionStorage.clear();
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
});

describe('database-first dataset search', () => {
    it('offers search and catalog without manual collection and filters search results', async () => {
        vi.stubEnv('VITE_API_AUTH_MODE', 'local');
        const items = [
            { id: 1, title: 'Malaria Senegal', description: 'Mortality', geography: ['Senegal'], dataset_url: 'https://example.org/1', distributions: [{ url: 'https://example.org/1.csv', format: 'CSV' }] },
            { id: 2, title: 'Malaria France', description: 'Cases', geography: ['France'], dataset_url: 'https://example.org/2', distributions: [{ url: 'https://example.org/2.json', format: 'JSON' }] },
            { id: 3, title: 'Vaccination Senegal', description: 'Coverage', geography: ['Senegal'], dataset_url: 'https://example.org/3', distributions: [{ url: 'https://example.org/3.csv', format: 'CSV' }] },
        ];
        mockApi(() => Promise.resolve(jsonResponse({
            search_id: SEARCH_ID, query: 'health', origin: 'database', warnings: [], items,
        })));
        render(<App />);
        expect(screen.queryByText('API connected')).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Administration' })).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Collect', hidden: true })).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Catalog' }));
        expect(screen.getByRole('heading', { name: 'Catalog' })).toBeVisible();
        expect(global.fetch.mock.calls.some(([url]) => String(url).endsWith('/sources'))).toBe(false);
        fireEvent.click(screen.getByRole('button', { name: 'Search datasets' }));
        submitSearch('health');
        expect(await screen.findByRole('heading', { name: 'Malaria Senegal' })).toBeVisible();
        fireEvent.change(screen.getByLabelText('Country or area'), { target: { value: 'Senegal' } });
        expect(screen.queryByRole('heading', { name: 'Malaria France' })).not.toBeInTheDocument();
        fireEvent.change(screen.getByLabelText('Topic'), { target: { value: 'malaria' } });
        expect(screen.queryByRole('heading', { name: 'Vaccination Senegal' })).not.toBeInTheDocument();
        fireEvent.change(screen.getByLabelText('Format'), { target: { value: 'JSON' } });
        expect(screen.getByText('No results match these filters.')).toBeVisible();
        fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
        expect(screen.getByRole('heading', { name: 'Malaria France' })).toBeVisible();
        expect(screen.getByRole('heading', { name: 'Vaccination Senegal' })).toBeVisible();
    });

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
        expect(screen.getByText('In the catalog')).toBeInTheDocument();
        expect(
            screen.getByText('Results found in the local catalog'),
        ).toBeInTheDocument();
        expect(screen.queryByText('AI agreement')).not.toBeInTheDocument();
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
            classification_status: 'queued',
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
                    `/collector/repository-candidates/${CANDIDATE_ID}`,
                )
            ) {
                return classificationResponse;
            }
            throw new Error(`Unexpected request: ${url}`);
        });
        render(<App />);

        submitSearch();

        expect(await screen.findByText('Waiting')).toBeInTheDocument();
        expect(screen.getByText('No local results')).toBeInTheDocument();

        await act(async () => {
            resolveClassification(
                jsonResponse({
                    ...onlineItem,
                    classification_status: 'accepted',
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

        expect(await screen.findByText('Accepted candidate 1/1')).toBeInTheDocument();
        expect(
            screen.getByText('Dataset saved to the local catalog'),
        ).toBeInTheDocument();
        expect(screen.getByText('AI agreement')).toBeInTheDocument();
        const classificationCall = global.fetch.mock.calls.find(([url]) =>
            String(url).includes(`/repository-candidates/${CANDIDATE_ID}`),
        );
        expect(global.fetch.mock.calls.some(([url]) => String(url).includes('/classify'))).toBe(false);
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
            classification_status: 'queued',
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
                    `/collector/repository-candidates/${CANDIDATE_ID}`,
                )
            ) {
                return Promise.resolve(
                    jsonResponse({
                        ...onlineItem,
                        classification_status: 'accepted',
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
            await screen.findByText('Automatic collection pending'),
        ).toBeInTheDocument();
        expect(
            await screen.findByText('Dataset saved to the local catalog', {}, {
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
            classification_status: 'queued',
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
                    `/collector/repository-candidates/${CANDIDATE_ID}`,
                )
            ) {
                return Promise.resolve(
                    jsonResponse({
                        ...onlineItem,
                        classification_status: 'rejected',
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

        expect(await screen.findByText(/1 was rejected/)).toBeInTheDocument();
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
        expect(await screen.findByText('Searching for candidates')).toBeInTheDocument();

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
            await screen.findByText('No dataset was accepted for this search.'),
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

        expect(await screen.findByText('Search failed')).toBeInTheDocument();
        expect(screen.getByText('Database search failed.')).toBeInTheDocument();
    });
});

describe('protected API access', () => {
    it('allows local searches without displaying or sending a token', async () => {
        vi.stubEnv('VITE_API_AUTH_MODE', 'local');
        window.sessionStorage.clear();
        mockApi(() => Promise.resolve(jsonResponse({
            search_id: SEARCH_ID, query: 'malaria mortality', origin: 'database',
            items: [], candidates: [], warnings: [],
        })));
        render(<App />);
        expect(screen.queryByLabelText('API token')).not.toBeInTheDocument();
        submitSearch();
        await waitFor(() => {
            const call = global.fetch.mock.calls.find(([url]) =>
                String(url).endsWith('/collector/search-datasets'));
            expect(call).toBeDefined();
            expect(call[1]?.headers?.Authorization).toBeUndefined();
        });
    });

    it('requires a runtime token and never starts a protected request without one', async () => {
        window.sessionStorage.clear();
        mockApi((url) => {
            throw new Error(`Unexpected protected request: ${url}`);
        });
        render(<App />);

        submitSearch();

        expect(
            await screen.findByText('An API token is required for this operation.'),
        ).toBeInTheDocument();
        expect(
            global.fetch.mock.calls.some(([url]) =>
                String(url).endsWith('/collector/search-datasets'),
            ),
        ).toBe(false);
    });

    it('uses an existing session token without displaying token controls', async () => {
        window.sessionStorage.setItem('global-health-api-token', 'runtime-test-token');
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

        expect(screen.queryByLabelText('API token')).not.toBeInTheDocument();
        expect(screen.queryByRole('region', { name: 'Protected API access' })).not.toBeInTheDocument();
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
