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

function formatRepositoryRelevanceLabel(label) {
    const labels = {
        relevant: 'Pertinent',
        somewhat_relevant: 'Partiellement pertinent',
        not_relevant: 'Non pertinent',
        insufficient_information: 'Information insuffisante',
    };

    return labels[label] ?? String(label ?? '').replaceAll('_', ' ').toLowerCase();
}

function formatDecisionReason(reason) {
    const reasons = {
        enough_accept_votes: 'accord suffisant',
        rejected_by_majority: 'rejet à la majorité',
        insufficient_accept_votes: 'accord insuffisant',
    };

    return reasons[reason] ?? reason;
}

export default function RepositoryAcceptedCard({ candidate }) {
    const { item } = candidate;
    const classification = item.classification;
    const ensemble = getEnsembleSummary(classification);
    const acceptedVotes = getAcceptedVoteCount(classification);
    const voters = Array.isArray(ensemble?.voters) ? ensemble.voters : [];
    const agreementLabel = acceptedVotes === null ? '' : ` ${acceptedVotes}/3`;

    return (
        <article className="repository-card repository-card--accepted">
            <div className="repository-card__top">
                <span className="repository-source-pill">{item.source}</span>
                <span className="repository-status-pill repository-status-pill--accepted">
                    Accepté{agreementLabel}
                </span>
            </div>

            <h3>{item.title}</h3>
            <p>{item.description || 'Description non disponible.'}</p>

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
                        Pertinence IA
                        <strong>
                            {formatRepositoryRelevanceLabel(
                                classification.relevance_label,
                            )}
                        </strong>
                    </span>
                </div>
            ) : null}

            <div className="repository-card__link-row">
                <span>{getHostname(item.url)}</span>
                <a href={item.url} target="_blank" rel="noreferrer">
                    Ouvrir le dataset
                </a>
            </div>

            {ensemble ? (
                <details className="repository-ai-details">
                    <summary>Détails IA</summary>
                    <p>
                        {acceptedVotes ?? 0}/3 votes favorables
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
                                        {voter.accepted ? 'Accepte' : 'Refuse'}
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
