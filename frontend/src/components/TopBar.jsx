import { NavLink, Link } from 'react-router-dom';
import { useLive, useNow } from '../live';
import { TIERS, ago } from '../format';

const ORDER = ['critical', 'warning', 'watch', 'stand_down', 'normal', 'no_data'];

export default function TopBar() {
  const { nodes, lastOk, operator, setOperator, soundOn, setSoundOn } = useLive();
  const now = useNow(1000);
  const counts = {};
  for (const n of nodes) {
    if (n.node_type !== 'landslide') continue;
    const t = n.tier === 'unreliable' ? 'no_data' : n.tier || 'no_data';
    counts[t] = (counts[t] || 0) + 1;
  }
  return (
    <header className="topbar">
      <Link to="/" className="brand">
        <img src="/ghost.png" alt="" onError={(e) => { e.currentTarget.style.display = 'none'; }} />
        <span>GHOST ALERT</span>
      </Link>
      <nav className="nav">
        <NavLink to="/dashboard">Dashboard</NavLink>
        <NavLink to="/events">Alerts</NavLink>
      </nav>
      <div className="counts" aria-label="Nodes per tier">
        {ORDER.filter((t) => counts[t]).map((t) => (
          <span key={t} className="count-pill" title={TIERS[t].help}>
            <span className="dot" style={{ background: TIERS[t].color }} />
            {TIERS[t].label} {counts[t]}
          </span>
        ))}
      </div>
      <div className="topbar-right">
        <span className="muted small">{lastOk ? `Updated ${ago(lastOk, now)}` : 'Connecting...'}</span>
        <label className="operator">
          <span className="muted small">Operator</span>
          <input value={operator} placeholder="your name" maxLength={40}
                 onChange={(e) => setOperator(e.target.value)} />
        </label>
        <button className={`btn btn-sm ${soundOn ? 'btn-on' : ''}`} onClick={() => setSoundOn(!soundOn)}
                title="Beep while a critical alert is not acknowledged">
          Sound {soundOn ? 'on' : 'off'}
        </button>
      </div>
    </header>
  );
}
