import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../api';
import { useLive, usePoll } from '../live';
import { fmtDateTime, fmtTime, tierMeta } from '../format';
import { TierBadge, SimBadge } from '../components/Badges';
import { TimeSeriesChart } from '../components/Charts';

const ACTION_TEXT = {
  open: 'Opened', raise: 'Raised', lower: 'Lowered', ready: 'Ready to close (calm for 6 h)',
  not_ready: 'Not ready any more (risk came back)', acknowledged: "Acknowledged (\"I've seen it\")",
  reminder: 'Reminder sent (not acknowledged)', closed: 'Closed',
};

export default function EventPage() {
  const { id } = useParams();
  const { operator, refresh, events: liveEvents } = useLive();
  const ev = usePoll(() => api.event(id), 10000, [id]);
  // Reload at once when the shared alert list shows a change (e.g. "I've seen it" pressed in the banner).
  const liveEv = liveEvents.find((x) => String(x.id) === String(id));
  const liveKey = liveEv ? `${liveEv.acknowledged_at}|${liveEv.current_level}|${liveEv.last_changed_at}` : 'gone';
  useEffect(() => { ev.reload(); }, [liveKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  const e = ev.data;
  const hours = e ? Math.min(168, Math.max(2, (Date.now() - new Date(e.opened_at).getTime()) / 3.6e6 + 2)) : 6;
  const tele = usePoll(
    () => (e ? api.telemetry(e.node_id, hours, ['moisture_index', 'tilt_deg', 'tilt_event', 'pir_triggers']) : Promise.resolve(null)),
    30000, [e?.node_id, Math.round(hours)],
  );

  if (ev.error) return <div className="page"><p className="error">Could not load alert: {ev.error}</p></div>;
  if (!e) return <div className="page"><p className="muted">Loading...</p></div>;

  const act = async (fn) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      await ev.reload();
      await refresh();
    } catch (err) {
      setMsg(err.message);
    } finally {
      setBusy(false);
    }
  };
  const by = operator || 'operator';
  const open = e.state === 'open';
  const to = Date.now();
  const from = to - hours * 3.6e6;
  const s = tele.data || {};

  return (
    <div className="page">
      <Link to="/dashboard" className="back">&larr; Dashboard</Link>
      <div className="page-head">
        <h1>{e.event_type === 'wildlife' ? 'Wildlife' : 'Landslide'} alert #{e.id}</h1>
        <TierBadge tier={e.current_level} />
        <span className={`state-pill ${open ? 'state-open' : 'state-closed'}`}>{open ? 'OPEN' : 'CLOSED'}</span>
        <span className="muted">node <Link to={`/nodes/${e.node_id}`}>{e.node_name}</Link></span>
        {e.is_virtual && <SimBadge />}
      </div>

      <div className="cards">
        <section className="card">
          <h2>Summary</h2>
          <div className="kv"><span>Now</span><span><TierBadge tier={e.current_level} size="sm" /> {tierMeta(e.current_level).help}</span></div>
          <div className="kv"><span>Highest</span><span><TierBadge tier={e.peak_level} size="sm" /> (never goes down)</span></div>
          <div className="kv"><span>Reason</span><span className="mono small">{e.reason}</span></div>
          {e.event_type === 'wildlife' && <div className="kv"><span>Triggers</span><span>{e.trigger_count}</span></div>}
          <div className="kv"><span>Opened</span><span>{fmtDateTime(e.opened_at)}</span></div>
          <div className="kv"><span>Last change</span><span>{fmtDateTime(e.last_changed_at)}</span></div>
          <div className="kv"><span>Seen by</span><span>{e.acknowledged_at ? `${e.acknowledged_by} at ${fmtTime(e.acknowledged_at)}` : 'nobody yet'}</span></div>
          {e.ready_to_close_at && <div className="kv"><span>Ready to close</span><span>since {fmtDateTime(e.ready_to_close_at)}</span></div>}
          {!open && <div className="kv"><span>Closed</span><span>{fmtDateTime(e.resolved_at)} by {e.resolved_by}: "{e.resolve_note}"</span></div>}
        </section>

        <section className="card">
          <h2>Actions</h2>
          {!open && <p className="muted">This alert is closed. If the detector still sees danger, a new alert opens by itself.</p>}
          {open && !e.acknowledged_at && (
            <button className="btn btn-primary" disabled={busy} onClick={() => act(() => api.acknowledge(e.id, by))}>
              I've seen it
            </button>
          )}
          {open && (
            <form className="close-form" onSubmit={(ev2) => {
              ev2.preventDefault();
              if (note.trim().length < 3) { setMsg('Write a short note first (what did you check?).'); return; }
              act(() => api.close(e.id, by, note.trim()));
            }}>
              <label htmlFor="note">Close with a note</label>
              <textarea id="note" rows={3} value={note} maxLength={500}
                        placeholder="Slope inspected, no cracks. / False alarm: node was knocked."
                        onChange={(x) => { setNote(x.target.value); setMsg(null); }} />
              <button className="btn" disabled={busy} type="submit">Close alert</button>
              <p className="small muted">Closing does not switch off the detector: if it still sees danger, a new alert opens.</p>
            </form>
          )}
          {msg && <p className="error small">{msg}</p>}
          <p className="small muted">Acting as: {by} (change it in the top bar)</p>
        </section>
      </div>

      <section className="card">
        <h2>Timeline</h2>
        <ol className="timeline">
          {e.log.map((l, i) => (
            <li key={i}>
              <span className="tl-time">{fmtDateTime(l.at)}</span>
              <span className="tl-what">
                <strong>{ACTION_TEXT[l.action] || l.action}</strong>
                {l.from_level && l.to_level && l.from_level !== l.to_level && ` ${tierMeta(l.from_level).label} → ${tierMeta(l.to_level).label}`}
                {!l.from_level && l.to_level && ` at ${tierMeta(l.to_level).label}`}
                {l.actor !== 'system' && ` by ${l.actor}`}
              </span>
              {l.note && <span className="tl-note small muted">{l.note}</span>}
            </li>
          ))}
        </ol>
      </section>

      {e.event_type === 'landslide' ? (
        <div className="charts">
          <TimeSeriesChart title="Tilt around this alert" unit="degrees" series={s.tilt_deg} events={s.tilt_event}
                           domain={[from, to]} digits={2} note="diamonds = motion bursts" />
          <TimeSeriesChart title="Soil moisture around this alert" unit="index 0-100" series={s.moisture_index}
                           domain={[from, to]} yDomain={[0, 100]} digits={0} />
        </div>
      ) : (
        <div className="charts">
          <TimeSeriesChart title="PIR triggers" unit="triggers per packet" series={s.pir_triggers}
                           domain={[from, to]} digits={0} />
        </div>
      )}
    </div>
  );
}
