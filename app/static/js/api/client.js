/**
 * Cinema CI — API Client Layer
 * Strongly structured HTTP client interfacing with FastAPI control plane.
 */

const BASE_URL = '';

class ApiError extends Error {
  constructor(message, status, details = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;
  }
}

async function request(endpoint, options = {}) {
  const url = `${BASE_URL}${endpoint}`;
  const config = {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  };

  try {
    const res = await fetch(url, config);
    if (!res.ok) {
      let errDetails = null;
      try {
        errDetails = await res.json();
      } catch {
        errDetails = await res.text();
      }
      throw new ApiError(
        (errDetails && errDetails.detail) || `HTTP ${res.status} on ${endpoint}`,
        res.status,
        errDetails
      );
    }
    const contentType = res.headers.get('content-type');
    if (contentType && contentType.includes('application/json')) {
      return await res.json();
    }
    return await res.text();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(`Network or connection failure: ${err.message}`, 0, err);
  }
}

export const api = {
  // Project & Creative Contract
  getProject: () => request('/api/project'),
  saveContract: (contractData) => request('/api/contract', {
    method: 'PUT',
    body: JSON.stringify(contractData),
  }),
  resetContract: () => request('/api/contract/reset', { method: 'POST' }),

  // Builds & Executions
  getBuilds: () => request('/api/builds'),
  getBuild: (buildId) => request(`/api/builds/${encodeURIComponent(buildId)}`),
  startBuild: () => request('/api/builds', { method: 'POST' }),
  triggerRegression: () => request('/api/builds/regress', { method: 'POST' }),
  cancelBuild: (buildId) => request(`/api/builds/${encodeURIComponent(buildId)}/cancel`, { method: 'POST' }),

  // Change Impact Intelligence
  analyzeImpact: async (prompt, baselineBuildId = null) => {
    const res = await request('/api/impact/analyze', {
      method: 'POST',
      body: JSON.stringify({ change_prompt: prompt, baseline_build_id: baselineBuildId }),
    });
    return res.plan || res;
  },
  applyImpact: (plan, runBuild = true) => request('/api/impact/apply', {
    method: 'POST',
    body: JSON.stringify({
      plan,
      run_build: runBuild,
      change_prompt: plan?.raw_prompt || '',
    }),
  }),

  // Releases & Continuous Delivery
  getReleases: () => request('/api/releases'),
  promoteRelease: (buildId, notes = '') => request(`/api/releases/promote/${encodeURIComponent(buildId)}`, {
    method: 'POST',
    body: JSON.stringify({ notes }),
  }),

  // Autonomous ADK Agent
  getAgentActivity: () => request('/api/agent/activity'),
  getAgentMode: () => request('/api/agent/mode'),
  repairBuild: (buildId) => request(`/api/repair/${encodeURIComponent(buildId)}`, { method: 'POST' }),

  // Observability & Grafana Telemetry
  getTelemetryOverview: () => request('/api/telemetry/overview'),
  getTelemetryLogs: (eventType = null) => {
    const q = eventType && eventType !== 'all' ? `?event_type=${encodeURIComponent(eventType)}` : '';
    return request(`/api/telemetry/logs${q}`);
  },
  getTelemetryTraces: (buildId) => request(`/api/telemetry/traces/${encodeURIComponent(buildId)}`),
  queryPromql: (query) => request('/api/telemetry/query/promql', {
    method: 'POST',
    body: JSON.stringify({ query }),
  }),
  queryLogql: (query) => request('/api/telemetry/query/logql', {
    method: 'POST',
    body: JSON.stringify({ query }),
  }),
  simulateAlert: (payload = {}) => request('/api/telemetry/alert/simulate', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
  getDashboardUrl: () => request('/api/telemetry/dashboard'),
};
