const test = require('node:test');
const assert = require('node:assert/strict');
const { workerFailure, serviceFailure } = require('../failures.cjs');

test('browser failures keep controlled categories without provider text', () => {
  assert.equal(workerFailure({ name: 'TimeoutError', message: 'secret' }, 'navigation'), 'browser_timeout');
  assert.equal(workerFailure(Error('secret'), 'navigation'), 'browser_navigation_failed');
  assert.equal(workerFailure(Error('secret'), 'launch'), 'browser_render_failed');
  assert.equal(serviceFailure(Error('worker_exited')), 'browser_worker_exited');
  assert.equal(serviceFailure(Error('timeout')), 'browser_timeout');
  assert.equal(serviceFailure(Error('browser_navigation_failed')), 'browser_navigation_failed');
  assert.equal(serviceFailure(Error('secret URL cookie')), 'browser_unavailable');
});
