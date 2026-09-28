import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import DatasetAccessDetails from './DatasetAccessDetails.jsx';

afterEach(cleanup);

it('shows the recorded link check and never labels an unchecked link as confirmed', () => {
    render(<DatasetAccessDetails item={{
        geography: ['France'],
        distributions: [
            { url: 'https://example.org/checked', format: 'CSV', last_checked_at: '2026-09-10T08:00:00Z' },
            { url: 'https://example.org/unchecked', format: 'JSON' },
        ],
        validation_results: [{ url: 'https://example.org/checked', format: 'CSV', ok: true }],
    }} />);
    expect(screen.getByText('Access confirmed at the last check')).toBeVisible();
    expect(screen.getByText('Access not checked')).toBeVisible();
    expect(screen.getByText(/Last checked: 10\/09\/2026/)).toBeVisible();
    expect(screen.getByText('Last checked: date not provided')).toBeVisible();
    expect(screen.getByRole('link', { name: 'Access data · CSV' })).toHaveAttribute('href', 'https://example.org/checked');
});

it.each([
    ['restricted', 'Access restricted at the last check',
        'The response explicitly requires authentication or access permission.'],
    ['unconfirmed', 'Access not confirmed at the last check',
        'HTTP 403 refused the check without explicit authentication or permission requirements.'],
    ['unconfirmed', 'Access not confirmed at the last check',
        'An anti-bot challenge prevented verification of data access.'],
    ['unavailable', 'Data unavailable at the last check',
        'Resource was not found at this URL.'],
])('shows %s with its recorded reason: %s', (status, label, reason) => {
    render(<DatasetAccessDetails item={{
        distributions: [{ url: 'https://example.org/data', format: 'CSV' }],
        validation_results: [{ url: 'https://example.org/data', format: 'CSV',
            ok: false, status, reason }],
    }} />);
    expect(screen.getByText(label)).toBeVisible();
    expect(screen.getByText(reason)).toBeVisible();
    expect(screen.queryByText('Access confirmed at the last check')).not.toBeInTheDocument();
    if (status === 'unconfirmed') {
        expect(screen.queryByText('Access restricted at the last check')).not.toBeInTheDocument();
    }
});
