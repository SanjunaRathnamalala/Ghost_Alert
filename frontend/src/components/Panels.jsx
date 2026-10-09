import { Link } from 'react-router-dom';
import { useNow } from '../live';
import { ago, fmtTime, shortName, tierMeta, decodeFlags, needsService, patternLabel, hasPatterns } from '../format';
import { TierBadge, SimBadge, OfflineBadge } from './Badges';

export function AlertList({ events }) {
  const now = useNow(5000);
  const sorted = [...events].sort((a, b) =>
    tierMeta(b.current_level).rank - tierMeta(a.current_level).rank
    || new Date(b.last_changed_at) - new Date(a.last_changed_at));
  if (!sorted.length) {
    return <p className="empty">No open alerts. Warnings and criticals appear here.</p>;
  }
  return (
    <ul className="list">
      {sorted.map((e) => (
        <li key={e.id}>
          <Link to={`/events/${e.id}`} className="row-link">
            <div className="row-top">
              <TierBadge tier={e.current_level} size="sm" />
              <span className="row-name">
                {e.event_type === 'wildlife' ? 'Wildlife' : 'Landslide'} · {shortName(e.node_name)}
              </span>
              {e.is_virtual && <SimBadge />}
              <span className="row-time">{fmtTime(e.opened_at)}</span>
            </div>
            <div className="row-sub">
              {e.event_type === 'wildlife' ? `${e.trigger_count} trigger(s)` : e.reason}
            </div>
            <div className="row-sub muted">
              {e.acknowledged_at ? `Seen by ${e.acknowledged_by}` : 'Not acknowledged yet'}
              {e.peak_level !== e.current_level && ` · peak ${tierMeta(e.peak_level).label}`}
              {e.ready_to_close_at && ' · ready to close'}
              {' · '}changed {ago(e.last_changed_at, now)}
            </div>
          </Link>
        </li>
      ))}
    </ul>
  );
}

export function NodeList({ nodes }) {
  const now = useNow(5000);
  const sorted = [...nodes].sort((a, b) => tierMeta(b.tier).rank - tierMeta(a.tier).rank || a.name.localeCompare(b.name));
  return (
    <ul className="list">
      {sorted.map((n) => (
        <li key={n.id}>
          <Link to={`/nodes/${n.id}`} className="row-link">
            <div className="row-top">
              <TierBadge tier={n.tier} size="sm" />
              <span className="row-name">{n.name}</span>
              {n.is_virtual && <SimBadge />}
              {n.online === false && <OfflineBadge />}
              <span className="row-time">{ago(n.last_seen_at, now)}</span>
            </div>
            {hasPatterns(n) && (
              <div className="row-sub muted">
                {patternLabel('moisture', n.moisture_pattern)} · {patternLabel('tilt', n.tilt_pattern)}
              </div>
            )}
            {n.tier === 'no_data' && <div className="row-sub muted">No recent data - state unknown</div>}
          </Link>
        </li>
      ))}
    </ul>
  );
}

export function ServiceList({ nodes }) {
  const now = useNow(5000);
  const list = nodes.filter(needsService);
  if (!list.length) return <p className="empty">All nodes reporting normally.</p>;
  return (
    <ul className="list">
      {list.map((n) => {
        const why = [];
        if (n.online === false) why.push(`no packets since ${ago(n.last_seen_at, now)}`);
        if (n.tier === 'no_data') why.push('not enough recent data');
        if (n.tier === 'unreliable') why.push('both sensors look faulty');
        why.push(...decodeFlags(n.sensor_flags));
        return (
          <li key={n.id}>
            <Link to={`/nodes/${n.id}`} className="row-link">
              <div className="row-top">
                <span className="row-name">{n.name}</span>
                {n.is_virtual && <SimBadge />}
              </div>
              <div className="row-sub">{why.join(' · ')}</div>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
