import { useEffect, useMemo, useState } from 'react';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8001';

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

export default function App() {
    const [sources, setSources] = useState([]);
    const [selectedTheme, setSelectedTheme] = useState('All');
    const [searchTerm, setSearchTerm] = useState('');
    const [loading, setLoading] = useState(true);
    const [loaded, setLoaded] = useState(false);
    const [error, setError] = useState('');
    const [collectorUrl, setCollectorUrl] = useState('https://example.org/data/catalog');
    const [collectorHtml, setCollectorHtml] = useState(SAMPLE_COLLECTOR_HTML);
    const [collectorLoading, setCollectorLoading] = useState(false);
    const [collectorError, setCollectorError] = useState('');
    const [collectorResult, setCollectorResult] = useState(null);

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
                    <small>collector MVP</small>
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
                                    <span>{getHostname(source.page_url)}</span>
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
