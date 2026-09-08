/**
 * Cinema CI — Formatters & Presentation Utilities
 */

/**
 * Truncates a SHA-256 hash or string to short representation.
 * @param {string} hash
 * @param {number} [length=8]
 * @returns {string}
 */
export function shortHash(hash, length = 8) {
  if (!hash) return '—';
  return String(hash).slice(0, length);
}

/**
 * Formats an ISO date string to readable UTC or local representation.
 * @param {string} isoString
 * @returns {string}
 */
export function formatDate(isoString) {
  if (!isoString) return '—';
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return String(isoString);
    return d.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  } catch {
    return String(isoString);
  }
}

/**
 * Formats duration in seconds to "0.0s" or "MM:SS".
 * @param {number} seconds
 * @returns {string}
 */
export function formatDuration(seconds) {
  if (typeof seconds !== 'number' || isNaN(seconds)) return '0.0s';
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}m ${s}s`;
}

/**
 * Formats percentage with 1 decimal place.
 * @param {number} value
 * @returns {string}
 */
export function formatPercent(value) {
  if (typeof value !== 'number' || isNaN(value)) return '0.0%';
  return `${value.toFixed(1)}%`;
}

/**
 * Returns CSS class modifier and label for build status.
 * @param {string} status
 * @returns {{ badgeClass: string, label: string, isTerminal: boolean, isSuccess: boolean }}
 */
export function getBuildStatusMeta(status) {
  const norm = String(status || '').toUpperCase();
  switch (norm) {
    case 'RELEASE_READY':
      return { badgeClass: 'status-ready', label: 'RELEASE READY', isTerminal: true, isSuccess: true };
    case 'APPROVED_FOR_RELEASE':
      return { badgeClass: 'status-approved', label: 'APPROVED', isTerminal: true, isSuccess: true };
    case 'RELEASED':
      return { badgeClass: 'status-released', label: 'RELEASED', isTerminal: true, isSuccess: true };
    case 'PASSED':
      return { badgeClass: 'status-pass', label: 'PASSED', isTerminal: true, isSuccess: true };
    case 'BLOCKED':
      return { badgeClass: 'status-blocked', label: 'BLOCKED', isTerminal: true, isSuccess: false };
    case 'INVESTIGATING':
    case 'REPAIRING':
      return { badgeClass: 'status-repairing', label: 'ADK REPAIRING', isTerminal: false, isSuccess: false };
    case 'BUILDING':
    case 'GENERATING':
    case 'TESTING':
    case 'VALIDATING':
    case 'REBUILDING':
      return { badgeClass: 'status-running', label: norm, isTerminal: false, isSuccess: false };
    case 'CANCELED':
      return { badgeClass: 'status-canceled', label: 'CANCELED', isTerminal: true, isSuccess: false };
    default:
      return { badgeClass: 'status-idle', label: norm || 'IDLE', isTerminal: false, isSuccess: false };
  }
}

