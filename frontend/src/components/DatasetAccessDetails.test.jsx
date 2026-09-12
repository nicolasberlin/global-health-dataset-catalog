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
