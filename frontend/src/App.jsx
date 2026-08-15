import { useState } from 'react';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000';

export default function App() {
    const [sources, setSources] = useState([]);
    const [selectedTheme, setSelectedTheme] = useState('All');
    const [loading, setLoading] = useState(false);
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
            setError(exception instanceof Error ? exception.message : 'Erreur inconnue');
        } finally {
            setLoading(false);
        }
    }

    const themes = ['All', ...new Set(sources.map((source) => source.theme))];
    const filteredSources =
        selectedTheme === 'All'
            ? sources
            : sources.filter((source) => source.theme === selectedTheme);

    return (
        <main className="page-shell">
            <section className="hero">
                <div className="hero__content">
                    <span className="eyebrow">Global Health</span>
                    <h1>Catalogue de datasets santé.</h1>
                    <p>
                        Une liste de pages officielles pour retrouver rapidement des datasets santé
                        sans télécharger les données dans l’application.
                    </p>
                </div>

                <div className="hero__panel">
                    <div className="panel-card">
                        <span className="panel-card__label">Catalogue</span>
                        <strong>{loading ? 'Chargement...' : error ? 'Erreur' : `${sources.length} datasets`}</strong>
                        <p>
                            {loading
                                ? 'Lecture des URLs depuis le backend.'
                                : error || 'Charge les pages de datasets enregistrées dans SQLite.'}
                        </p>
                        <button type="button" onClick={loadSources} disabled={loading}>
                            {loading ? 'Chargement...' : 'Charger les datasets'}
                        </button>
                    </div>
                </div>
            </section>

            <section className="section-block">
                <h2>Pages de datasets santé</h2>
                {sources.length > 0 ? (
                    <div className="filter-row">
                        <label htmlFor="theme-filter">Thème</label>
                        <select
                            id="theme-filter"
                            value={selectedTheme}
                            onChange={(event) => setSelectedTheme(event.target.value)}
                        >
                            {themes.map((theme) => (
                                <option key={theme} value={theme}>
                                    {theme === 'All' ? 'Tous' : theme}
                                </option>
                            ))}
                        </select>
                    </div>
                ) : null}
                <div className="section-grid">
                    {filteredSources.length > 0 ? (
                        filteredSources.map((source) => (
                            <article className="feature-card" key={source.id}>
                                <span className="theme-pill">{source.theme}</span>
                                <h3>{source.name}</h3>
                                <p>{source.description}</p>
                                <a
                                    className="source-link"
                                    href={`${API_BASE_URL}/sources/${source.id}/page`}
                                    target="_blank"
                                    rel="noreferrer"
                                >
                                    Voir le dataset
                                </a>
                            </article>
                        ))
                    ) : (
                        <article className="feature-card">
                            <h3>{loaded ? 'Aucun dataset pour ce thème' : 'Catalogue non chargé'}</h3>
                            <p>
                                {loaded
                                    ? 'Choisis un autre thème pour voir les pages disponibles.'
                                    : 'Clique sur le bouton pour lire les URLs stockées côté backend.'}
                            </p>
                        </article>
                    )}
                </div>
            </section>

            <section className="section-block">
                <h2>Etat</h2>
                <div className="feature-card">
                    <p>
                        {error
                            ? error
                            : loaded
                                ? 'Le catalogue a bien été chargé depuis l’API.'
                                : 'Le frontend attend le chargement du catalogue.'}
                    </p>
                </div>
            </section>
        </main>
    );
}
