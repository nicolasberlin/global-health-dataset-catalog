// Return only controlled categories; never return Playwright exception bodies.
function workerFailure(error, phase) {
  if (error?.name === 'TimeoutError') return 'browser_timeout';
  if (phase === 'navigation') return 'browser_navigation_failed';
  if (error?.message === 'response_too_large') return 'browser_invalid_response';
  return 'browser_render_failed';
}
function serviceFailure(error) {
  const codes = new Set(['browser_timeout', 'browser_navigation_failed', 'browser_invalid_response', 'browser_render_failed']);
  if (codes.has(error?.message)) return error.message;
  if (error?.message === 'timeout' || error?.message === 'expired') return 'browser_timeout';
  if (error?.message === 'worker_exited') return 'browser_worker_exited';
  return 'browser_unavailable';
}
module.exports = { workerFailure, serviceFailure };
