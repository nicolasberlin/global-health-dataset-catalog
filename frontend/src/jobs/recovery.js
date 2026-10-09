export function retryDate(errors = []) {
    return Math.max(0, ...errors.map(error => Date.parse(error.retry_at) || 0));
}
export function canRetry(errors = []) {
    return !errors.length || errors.some(error => error.recovery === 'manual');
}
export function diagnosticText(errors = []) {
    return [...new Set(errors.map(error => error.message).filter(Boolean))].join(' ');
}
