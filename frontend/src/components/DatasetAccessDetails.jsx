export function datasetCountries(item) {
    if (item?.collected_datasets?.length) return [...new Set(item.collected_datasets.flatMap(datasetCountries))];
    return Array.isArray(item?.geography) ? item.geography.filter(value => typeof value === 'string' && value) : [];
}

export function datasetFormats(item) {
    if (item?.collected_datasets?.length) return [...new Set(item.collected_datasets.flatMap(datasetFormats))];
    return [...new Set((item?.distributions ?? []).map(value => value.format).filter(Boolean))];
}

export default function DatasetAccessDetails({ item }) {
    const countries = datasetCountries(item);
    const distributions = item?.distributions ?? [];
    return (
        <div className="dataset-access-details">
            {item.date_of_publication && <p><strong>Publication date:</strong> {item.date_of_publication}</p>}
            {item.sharing_license && <p><strong>License:</strong> {item.sharing_license}</p>}
            {item.doi && <p><strong>DOI:</strong> <a href={`https://doi.org/${encodeURIComponent(item.doi)}`}
                target="_blank" rel="noreferrer">{item.doi}</a></p>}
            {Object.keys(item.metadata_provenance ?? {}).length > 0 && <details>
                <summary>Metadata sources</summary>
                <ul>{Object.entries(item.metadata_provenance).flatMap(([field, entries]) =>
                    (Array.isArray(entries) ? entries : []).map((entry, index) => <li key={`${field}-${index}`}>
                        {field.replaceAll('_', ' ')}: {entry.value} · {entry.provider || entry.kind} · {entry.source_url}
                    </li>))}</ul>
            </details>}
            <p><strong>Geographic coverage:</strong> {countries.join(', ') || 'Not provided'}</p>
            {distributions.length === 0 ? (
                <p>Data formats and access: not confirmed.</p>
            ) : (
                <ul className="dataset-access-links">
                    {distributions.map(distribution => {
                        const validation = item.validation_results?.find(value =>
                            value.url === distribution.url && value.format === distribution.format);
                        const checked = distribution.last_checked_at;
                        const date = checked ? new Date(checked) : null;
                        const status = validation?.ok ?? distribution.validation_ok;
                        const confirmed = validation || distribution.validation_attempted;
                        const accessLabel = {
                            available: 'Access confirmed at the last check',
                            restricted: 'Access restricted at the last check',
                            unavailable: 'Data unavailable at the last check',
                            unconfirmed: 'Access not confirmed at the last check',
                        }[validation?.status];
                        return (
                            <li key={`${distribution.url}-${distribution.format}`}>
                                <a href={distribution.url} target="_blank" rel="noreferrer">
                                    Access data · {distribution.format || 'Format not provided'}
                                </a>
                                <span>{confirmed ? (accessLabel || (status ? 'Access confirmed at the last check' : 'Access not confirmed at the last check')) : 'Access not checked'}</span>
                                {validation?.reason && <small>{validation.reason}</small>}
                                <small>Last checked: {date && !Number.isNaN(date.getTime())
                                    ? date.toLocaleString('en-GB') : 'date not provided'}</small>
                            </li>
                        );
                    })}
                </ul>
            )}
        </div>
    );
}
