import { test, expect } from '@playwright/test';

const origin = 'http://localhost:9080';
const cookieName = 'global-health-session';

test('HTTP visitor searches through the real UI and retains the cookie after reload', async ({ page, context }) => {
    const bootstrap = page.waitForResponse(`${origin}/ai-commons/api/session`);
    await page.goto(`${origin}/ai-commons/`);
    expect((await bootstrap).status()).toBe(204);
    await expect(page.getByRole('button', { name: 'Search', exact: true })).toBeEnabled();
    const cookie = (await context.cookies()).find(cookie => cookie.name === cookieName);
    expect(cookie).toMatchObject({ httpOnly: true, secure: false, sameSite: 'Lax' });
    expect(await page.evaluate(() => document.cookie)).not.toContain(cookieName);
    expect(await page.evaluate(() => sessionStorage.getItem('global-health-api-token'))).toBeNull();

    await page.getByLabel('Search for a health dataset').fill('malaria');
    const searchResponse = page.waitForResponse(`${origin}/ai-commons/api/collector/searches`);
    await page.getByRole('button', { name: 'Search', exact: true }).click();
    const response = await searchResponse;
    expect(response.status()).toBe(202);
    expect(await response.request().headerValue('idempotency-key')).toBeTruthy();
    expect(await response.request().headerValue('authorization')).toBeNull();
    expect(await response.request().headerValue('origin')).toBe(origin);
    await expect(page.getByRole('heading', { name: 'Malaria browser fixture' }).filter({ visible: true })).toBeVisible();

    await page.reload();
    await expect(page.getByRole('heading', { name: 'Malaria browser fixture' }).filter({ visible: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Search', exact: true })).toBeEnabled();
    expect((await context.cookies()).find(cookie => cookie.name === cookieName).value).toBe(cookie.value);
});

test('internal HTTP still refuses a browser POST from another origin', async ({ page }) => {
    await page.goto('http://127.0.0.1:9080/');
    await page.setContent(`<form method="POST" action="${origin}/ai-commons/api/session">
        <button type="submit">Submit</button></form>`);
    const [response] = await Promise.all([
        page.waitForNavigation(), page.getByRole('button', { name: 'Submit' }).click(),
    ]);
    expect(response.status()).toBe(403);
    expect(await response.headerValue('set-cookie')).toBeNull();
});

test('one search snapshot follows ten candidates through collection and stops', async ({ page }) => {
    const searchId = '11111111-1111-4111-8111-111111111111';
    const items = Array.from({ length: 10 }, (_, index) => ({
        candidate_id: `candidate-${index}`, search_id: searchId,
        title: `Progress dataset ${index}`, url: 'https://example.org/data', source: 'Test',
        classification_status: 'queued',
    }));
    let reads = 0;
    const individual = [];
    page.on('request', request => {
        if (/\/repository-candidates\/|\/collection-jobs\//.test(request.url())) individual.push(request.url());
    });
    await page.route('**/collector/searches', route => route.fulfill({ status: 202, json: {
        search_id: searchId, execution_status: 'queued', attempt: 1, progress_url: `/collector/searches/${searchId}/progress`,
    } }));
    await page.route(`**/collector/searches/${searchId}/progress`, route => {
        const saved = ++reads > 1;
        return route.fulfill({ json: {
            search_id: searchId, query: 'progress', origin: 'online', polling_required: !saved,
            execution_status: saved ? 'finished' : 'running', outcome: saved ? 'results' : null,
            dataset_ids: [], local_dataset_ids: [], warnings: [], errors: [],
            items: items.map((item, index) => ({ ...item, classification_status: 'accepted',
                classification: { accepted: true, ensemble: {} },
                automatic_collection: { state: saved ? 'saved' : 'running',
                    job: { id: index + 1, status: saved ? 'done' : 'running', saved_count: saved ? 1 : 0 },
                },
            })),
        } });
    });
    await page.goto(`${origin}/ai-commons/`);
    await expect(page.getByRole('button', { name: 'Search', exact: true })).toBeEnabled();
    await page.getByLabel('Search for a health dataset').fill('progress');
    await page.getByRole('button', { name: 'Search', exact: true }).click();
    await expect(page.getByText('Dataset saved to the local catalog')).toHaveCount(10);
    // Observe longer than one polling interval to verify terminal cleanup.
    await page.waitForTimeout(2300);
    expect(reads).toBe(2);
    expect(individual).toEqual([]);
});

test('discovery without candidates is followed and a failed search stays restorable', async ({ page }) => {
    const id = '11111111-1111-4111-8111-111111111119';
    const failed = { search_id: id, query: 'error example', origin: 'online', attempt: 1,
        execution_status: 'failed', outcome: 'incomplete', polling_required: false,
        items: [], dataset_ids: [], local_dataset_ids: [], warnings: [],
        errors: [{ recovery: 'configuration_required', message: 'Search provider unavailable.' }] };
    let started = false, reads = 0;
    await page.route('**/collector/searches/latest', route => route.fulfill(started
        ? { json: failed } : { status: 404, json: { detail: 'None' } }));
    await page.route('**/collector/searches', route => {
        started = true;
        return route.fulfill({ status: 202, json: { search_id: id, attempt: 1, execution_status: 'queued',
            progress_url: `/collector/searches/${id}/progress` } });
    });
    await page.route(`**/collector/searches/${id}/progress`, route => route.fulfill({ json: ++reads === 1
        ? { ...failed, origin: null, errors: [], execution_status: 'running', outcome: null, polling_required: true }
        : failed }));
    await page.goto(`${origin}/ai-commons/`);
    await expect(page.getByRole('button', { name: 'Search', exact: true })).toBeEnabled();
    await page.getByLabel('Search for a health dataset').fill('error example');
    await page.getByRole('button', { name: 'Search', exact: true }).click();
    await expect(page.getByText('Search in progress')).toBeVisible();
    await expect(page.getByText('Search incomplete')).toBeVisible();
    await expect(page.getByText('No datasets found', { exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Retry search' })).toHaveCount(0);
    await page.reload();
    await expect(page.getByText('Search incomplete')).toBeVisible();
    await page.waitForTimeout(2300);
    expect(reads).toBe(2);
});
