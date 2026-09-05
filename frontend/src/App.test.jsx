import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import App from './App.jsx';

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

afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
});

describe('database-first dataset search', () => {
    it('shows local results immediately without classification controls or calls', async () => {
        mockApi((url) => {
            if (url.endsWith('/collector/search-datasets')) {
                return Promise.resolve(
                    jsonResponse({
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
                String(url).endsWith('/collector/classify-repository-result'),
            ),
        ).toBe(false);
    });

    it('keeps the online progressive classification flow', async () => {
        let resolveClassification;
        const classificationResponse = new Promise((resolve) => {
            resolveClassification = resolve;
        });
        const onlineItem = {
            title: 'Online malaria dataset',
            description: 'Annual observations.',
            url: 'https://example.org/malaria',
            source: 'DataCite',
            search_query: 'malaria mortality',
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
                        query: 'malaria mortality',
                        origin: 'online',
                        items: [onlineItem],
                        warnings: [],
                    }),
                );
            }
            if (url.endsWith('/collector/classify-repository-result')) {
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
                }),
            );
        });

        expect(await screen.findByText('Accepté 1/1')).toBeInTheDocument();
        expect(screen.getByText('Accord IA')).toBeInTheDocument();
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
