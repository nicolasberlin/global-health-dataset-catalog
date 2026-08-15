import { useEffect, useMemo, useState } from 'react';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8001';

function normalizeSearchValue(value) {
    return String(value ?? '')
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLowerCase();
}

export default function App() {
    const [sources, setSources] = useState([]);
    const [selectedTheme, setSelectedTheme] = useState('All');
    const [searchTerm, setSearchTerm] = useState('');
    const [loading, setLoading] = useState(true);
    const [loaded, setLoaded] = useState(false);
    const [error, setError] = useState('');

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

    useEffect(() => {
        loadSources();
    }, []);

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
                description: 'Le backend répond, mais aucun dataset n’est encore dans SQLite.',
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
                    <span>Version</span>
                    <strong>0.1</strong>
                    <small>sans collector</small>
                </article>
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
                                    <span>{new URL(source.page_url).hostname}</span>
                                    <a
                                        className="source-link"
                                        href={`${API_BASE_URL}/sources/${source.id}/page`}
                                        target="_blank"
                                        rel="noreferrer"
                                    >
                                        Ouvrir
                                    </a>
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
            </section>
        </main>
    );
}
