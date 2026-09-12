import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import RepositoryAcceptedCard from './RepositoryAcceptedCard.jsx';

function acceptedCandidate(state) {
    return {
        id: 'DataCite:https://example.org/dataset:0',
        status: 'accepted',
        item: {
            title: 'Malaria mortality dataset',
            description: 'Annual mortality observations.',
            url: 'https://example.org/dataset',
            source: 'DataCite',
            publisher: 'Example Institute',
            date: '2025',
            doi: '',
            keywords: ['malaria'],
            metadata: {},
            classification: {
                accepted: true,
                relevance_label: 'relevant',
                reason: 'Matches the query.',
                missing_information: [],
                ensemble: {
                    successful_votes: 1,
                    accepted_votes: 1,
                    failed_votes: 0,
                    voters: [],
                },
            },
            automatic_collection: {
                state,
                job: {
                    id: 12,
                    status: state === 'empty' ? 'done' : state,
                    saved_count: state === 'saved' ? 1 : 0,
                    message: '',
                    error: state === 'error' ? 'Network failure.' : '',
                },
            },
        },
    };
}

afterEach(cleanup);

describe('automatic repository collection status', () => {
    it.each([
        ['pending', 'Automatic collection pending'],
        ['running', 'Automatic collection in progress'],
        ['saved', 'Dataset saved to the local catalog'],
        ['empty', 'Collection completed without a valid file'],
        ['error', 'Automatic collection failed'],
    ])('shows the %s state', (state, expectedText) => {
        render(<RepositoryAcceptedCard candidate={acceptedCandidate(state)} />);

        expect(screen.getByText('Accepted candidate 1/1')).toBeInTheDocument();
        expect(screen.getByText(expectedText)).toBeInTheDocument();
    });

    it('shows a scheduling error even when no job was created', () => {
        const candidate = acceptedCandidate('error');
        candidate.item.automatic_collection = {
            state: 'error',
            job: null,
            error: 'Automatic collection scheduling failed.',
        };

        render(<RepositoryAcceptedCard candidate={candidate} />);

        expect(
            screen.getByText('Automatic collection scheduling failed.'),
        ).toBeInTheDocument();
    });
});
