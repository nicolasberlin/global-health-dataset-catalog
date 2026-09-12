export function datasetCountries(item) {
    return Array.isArray(item?.geography) ? item.geography.filter(value => typeof value === 'string' && value) : [];
}

export function datasetFormats(item) {
    return [...new Set((item?.distributions ?? []).map(value => value.format).filter(Boolean))];
}

export default function DatasetAccessDetails({ item }) {
    const countries = datasetCountries(item);
    const distributions = item?.distributions ?? [];
    return (
        <div className="dataset-access-details">
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
                        return (
                            <li key={`${distribution.url}-${distribution.format}`}>
                                <a href={distribution.url} target="_blank" rel="noreferrer">
                                    Access data · {distribution.format || 'Format not provided'}
                                </a>
                                <span>{confirmed ? (status ? 'Access confirmed at the last check' : 'Access not confirmed at the last check') : 'Access not checked'}</span>
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
