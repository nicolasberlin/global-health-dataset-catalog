import DatasetAccessDetails from './DatasetAccessDetails.jsx';

function getHostname(url) {
    try {
        return new URL(url).hostname;
    } catch {
        return url;
    }
}

export function getEnsembleSummary(classification) {
    return (
        classification?.ensemble ??
        classification?.dataset_signals?.ensemble ??
        null
    );
}

export function getAcceptedVoteCount(classification) {
    const ensemble = getEnsembleSummary(classification);
    const explicitCount = Number(ensemble?.accepted_votes);
    if (Number.isFinite(explicitCount)) {
        return explicitCount;
    }

    if (Array.isArray(ensemble?.voters)) {
        return ensemble.voters.filter((voter) => voter?.accepted === true).length;
    }

    return null;
}

export function getTotalVoteCount(classification) {
    const ensemble = getEnsembleSummary(classification);
    const successfulVotes = Number(ensemble?.successful_votes);
    const failedVotes = Number(ensemble?.failed_votes);
    if (Number.isFinite(successfulVotes) && Number.isFinite(failedVotes)) {
        return successfulVotes + failedVotes;
    }

    const voters = Array.isArray(ensemble?.voters) ? ensemble.voters.length : 0;
    const failures = Array.isArray(ensemble?.failures) ? ensemble.failures.length : 0;
    return voters + failures || null;
}

function formatRepositoryRelevanceLabel(label) {
    const labels = {
        relevant: 'Relevant',
        somewhat_relevant: 'Somewhat relevant',
        not_relevant: 'Not relevant',
        insufficient_information: 'Insufficient information',
    };

    return labels[label] ?? String(label ?? '').replaceAll('_', ' ').toLowerCase();
}

function formatDecisionReason(reason) {
    const reasons = {
        enough_accept_votes: 'enough positive votes',
        rejected_by_majority: 'rejected by majority',
        insufficient_accept_votes: 'not enough positive votes',
    };

    return reasons[reason] ?? reason;
}

function automaticCollectionStatus(automaticCollection) {
    const job = automaticCollection?.job;
    if (['retrying', 'unavailable'].includes(automaticCollection?.tracking)) {
        return {
            title: 'Collection tracking temporarily unavailable',
            detail: automaticCollection.tracking === 'retrying'
                ? 'The server may still be working. Retrying automatically.'
                : 'Unable to read this job. Check your API access.',
            tone: 'empty',
        };
    }
    const statuses = {
        pending: {
            title: 'Automatic collection pending',
            detail: '',
            tone: 'loading',
        },
        running: {
            title: 'Automatic collection in progress',
            detail: 'Checking data links.',
            tone: 'loading',
        },
        saved: {
            title: 'Dataset saved to the local catalog',
            detail: job?.saved_count
                ? `${job.saved_count} dataset(s) saved.`
                : 'This dataset was already in the catalog.',
            tone: 'saved',
        },
        empty: {
            title: 'Collection completed without a valid file',
            detail: 'No valid downloadable data file was found.',
            tone: 'empty',
        },
        error: {
            title: 'Automatic collection failed',
            detail:
                automaticCollection?.error ||
                job?.error ||
                'The page or its files could not be collected.',
            tone: 'error',
        },
    };

    return statuses[automaticCollection?.state] ?? null;
}

export default function RepositoryAcceptedCard({ candidate }) {
    const { item } = candidate;
    const classification = item.classification;
    const ensemble = getEnsembleSummary(classification);
    const acceptedVotes = getAcceptedVoteCount(classification);
    const totalVotes = getTotalVoteCount(classification);
    const voters = Array.isArray(ensemble?.voters) ? ensemble.voters : [];
    const collectionStatus = automaticCollectionStatus(item.automatic_collection);
    const agreementLabel =
        acceptedVotes === null || totalVotes === null
            ? ''
            : ` ${acceptedVotes}/${totalVotes}`;

    return (
        <article className="repository-card repository-card--accepted">
            <div className="repository-card__top">
                <span className="repository-source-pill">{item.source}</span>
                <span className="repository-status-pill repository-status-pill--accepted">
                    Accepted candidate{agreementLabel}
                </span>
            </div>

            <h3>{item.title}</h3>
            <p>{item.description || 'Description unavailable.'}</p>

            {(item.publisher || item.date) && (
                <dl className="repository-facts">
                    {item.publisher ? (
                        <div>
                            <dt>Publisher</dt>
                            <dd>{item.publisher}</dd>
                        </div>
                    ) : null}
                    {item.date ? (
                        <div>
                            <dt>Date</dt>
                            <dd>{item.date}</dd>
                        </div>
                    ) : null}
                </dl>
            )}

            {classification?.relevance_label ? (
                <div className="repository-decision-row">
                    <span>
                        AI relevance
                        <strong>
                            {formatRepositoryRelevanceLabel(
                                classification.relevance_label,
                            )}
                        </strong>
                    </span>
                </div>
            ) : null}

            {collectionStatus ? (
                <div
                    className={`repository-collection-status repository-collection-status--${collectionStatus.tone}`}
                    role="status"
                >
                    <strong>{collectionStatus.title}</strong>
                    {collectionStatus.detail ? <span>{collectionStatus.detail}</span> : null}
                </div>
            ) : null}

            <DatasetAccessDetails item={item} />
            <div className="repository-card__link-row">
                <span>{getHostname(item.url)}</span>
                <a href={item.url} target="_blank" rel="noreferrer">
                    Open dataset page
                </a>
            </div>

            {ensemble ? (
                <details className="repository-ai-details">
                    <summary>AI details</summary>
                    <p>
                        {acceptedVotes ?? 0}/{totalVotes ?? 1} positive votes
                        {ensemble.decision_reason
                            ? ` · ${formatDecisionReason(ensemble.decision_reason)}`
                            : ''}
                    </p>
                    {voters.length > 0 ? (
                        <ul>
                            {voters.map((voter, index) => (
                                <li key={`${voter.voter_id ?? 'ia'}-${index}`}>
                                    <span>
                                        {voter.voter_id || `IA ${index + 1}`}
                                        {voter.reason ? (
                                            <small>{voter.reason}</small>
                                        ) : null}
                                    </span>
                                    <strong>
                                        {voter.accepted ? 'Accepts' : 'Rejects'}
                                        {voter.relevance_label
                                            ? ` · ${formatRepositoryRelevanceLabel(
                                                  voter.relevance_label,
                                              )}`
                                            : ''}
                                    </strong>
                                </li>
                            ))}
                        </ul>
                    ) : null}
                    {Number(ensemble.failed_votes) > 0 ? (
                        <small>{ensemble.failed_votes} vote IA indisponible.</small>
                    ) : null}
                </details>
            ) : null}
        </article>
    );
}
