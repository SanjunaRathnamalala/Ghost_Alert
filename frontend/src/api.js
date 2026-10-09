// The ONE file that talks to the backend (design decision 6.7).
const BASE = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '') + '/api/v1';

async function req(path, opts = {}) {
  // Only requests with a body send Content-Type (plain GETs then need no CORS preflight).
  const headers = opts.body ? { 'Content-Type': 'application/json' } : undefined;
  const res = await fetch(BASE + path, { ...opts, headers });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
    } catch { /* keep statusText */ }
    throw new Error(msg || `HTTP ${res.status}`);
  }
  return res.json();
}

export const api = {
  health: () => req('/health'),
  nodes: () => req('/nodes').then((d) => d.nodes),
  node: (id) => req(`/nodes/${id}`),
  telemetry: (id, hours, fields) =>
    req(`/nodes/${id}/telemetry?hours=${hours}&fields=${fields.join(',')}`).then((d) => d.series),
  tiers: (id, hours) => req(`/nodes/${id}/tiers?hours=${hours}`).then((d) => d.history),
  events: (state = 'open', limit = 100) => req(`/events?state=${state}&limit=${limit}`).then((d) => d.events),
  event: (id) => req(`/events/${id}`),
  acknowledge: (id, by) => req(`/events/${id}/acknowledge`, { method: 'POST', body: JSON.stringify({ by }) }),
  close: (id, by, note) => req(`/events/${id}/close`, { method: 'POST', body: JSON.stringify({ by, note }) }),
};
