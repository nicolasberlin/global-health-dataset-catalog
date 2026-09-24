import { test, expect } from '@playwright/test';

const origin = 'https://localhost:9443';
const cookieName = '__Host-global-health-session';

// Run fetch in the page, not Playwright's HTTP client. The browser supplies all headers.
async function fetchFromPage(page, path, method = 'POST') {
    return page.evaluate(async ({ path, method }) => {
        const response = await fetch(path, { method });
        return { status: response.status, body: await response.text() };
    }, { path, method });
}

test('same-origin POST creates an HttpOnly session and authenticates later requests', async ({ page, context }) => {
    await page.goto('/');
    expect((await fetchFromPage(page, '/identity')).status).toBe(401);

    const bootstrapRequest = page.waitForRequest(request => request.url() === `${origin}/session`);
    expect(await fetchFromPage(page, '/session')).toEqual({ status: 204, body: '' });
    expect(await (await bootstrapRequest).headerValue('origin')).toBe(origin);

    const cookie = (await context.cookies()).find(cookie => cookie.name === cookieName);
    expect(cookie).toMatchObject({ secure: true, httpOnly: true, sameSite: 'Lax', path: '/' });
    expect(await page.evaluate(() => document.cookie)).not.toContain(cookieName);

    const identity = await fetchFromPage(page, '/identity');
    expect(identity.status).toBe(200);
    expect(JSON.parse(identity.body).owner_id).toMatch(/^visitor:[0-9a-f]{32}$/);
    expect(await fetchFromPage(page, '/identity', 'GET')).toEqual(identity);
    expect((await fetchFromPage(page, '/session')).status).toBe(204);
    expect(await fetchFromPage(page, '/identity')).toEqual(identity);
});

test('foreign-origin POST cannot create a session or use protected operations', async ({ page, context }) => {
    await page.goto('/');
    expect((await fetchFromPage(page, '/session')).status).toBe(204);
    const cookies = await context.cookies();
    // Same harness, different browser origin. No request interception or forged headers.
    for (const path of ['/session', '/identity']) {
        await page.goto('https://127.0.0.1:9443/');
        // A form POST models CSRF and exposes the server response without CORS masking it.
        await page.setContent(`<form method="POST" action="${origin}${path}">
            <button type="submit">Submit</button></form>`);
        const [response] = await Promise.all([
            page.waitForNavigation(),
            page.getByRole('button', { name: 'Submit' }).click(),
        ]);
        expect(await response.request().headerValue('origin')).toBe('https://127.0.0.1:9443');
        expect(response.status()).toBe(403);
        expect(await response.headerValue('set-cookie')).toBeNull();
    }
    expect(await context.cookies()).toEqual(cookies);
});
