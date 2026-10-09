import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { usePoll } from '../live';
import { fmtDateTime, shortName } from '../format';
import { TierBadge, SimBadge } from '../components/Badges';

export default function EventsPage() {
  const [state, setState] = useState('all');
  const list = usePoll(() => api.events(state, 200), 15000, [state]);
  const rows = list.data || [];
  return (
    <div className="page">
      <div className="page-head">
        <h1>Alerts</h1>
        {['all', 'open', 'resolved'].map((s) => (
          <button key={s} className={`btn btn-sm ${s === state ? 'btn-on' : ''}`} onClick={() => setState(s)}>
            {s === 'resolved' ? 'closed' : s}
          </button>
        ))}
      </div>
      {list.error && <p className="error">Could not load alerts: {list.error}</p>}
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr><th>#</th><th>Type</th><th>Node</th><th>Now</th><th>Highest</th><th>State</th><th>Opened</th><th>Seen by</th><th>Closed / note</th></tr>
          </thead>
          <tbody>
            {rows.map((e) => (
              <tr key={e.id}>
                <td><Link to={`/events/${e.id}`}>{e.id}</Link></td>
                <td>{e.event_type}</td>
                <td>{shortName(e.node_name)} {e.is_virtual && <SimBadge />}</td>
                <td><TierBadge tier={e.current_level} size="sm" /></td>
                <td><TierBadge tier={e.peak_level} size="sm" /></td>
                <td>{e.state === 'open' ? 'open' : 'closed'}</td>
                <td>{fmtDateTime(e.opened_at)}</td>
                <td>{e.acknowledged_by || '—'}</td>
                <td className="small">{e.resolved_at ? `${fmtDateTime(e.resolved_at)} · ${e.resolve_note}` : '—'}</td>
              </tr>
            ))}
            {!rows.length && <tr><td colSpan={9} className="empty">No alerts yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
