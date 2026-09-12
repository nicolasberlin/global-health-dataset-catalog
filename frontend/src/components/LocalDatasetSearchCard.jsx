import DatasetAccessDetails from './DatasetAccessDetails.jsx';

function getHostname(url) {
    try {
        return new URL(url).hostname;
    } catch {
        return url;
    }
}

export default function LocalDatasetSearchCard({ item }) {
    return (
        <article className="repository-card repository-card--accepted">
            <div className="repository-card__top">
                <span className="repository-source-pill">
                    {item.hosting_platform || 'Local catalog'}
                </span>
                <span className="repository-status-pill repository-status-pill--local">
                    In the catalog
                </span>
            </div>

            <h3>{item.title}</h3>
            <p>{item.description || 'Description unavailable.'}</p>

            {(item.publisher || item.geography?.length > 0) && (
                <dl className="repository-facts">
                    {item.publisher ? (
                        <div>
                            <dt>Publisher</dt>
                            <dd>{item.publisher}</dd>
                        </div>
                    ) : null}
                </dl>
            )}

            <DatasetAccessDetails item={item} />
            <div className="repository-card__link-row">
                <span>{getHostname(item.dataset_url)}</span>
                <a href={item.dataset_url} target="_blank" rel="noreferrer">
                    Open dataset page
                </a>
            </div>
        </article>
    );
}
