import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { STALE_AFTER_MS, useLive, useNow } from '../live';
import { fmtTime, ago, shortName } from '../format';

// Decision 6.5: if the data stops updating, say so loudly. A stale screen must never look safe.
export function StaleBanner() {
  const { lastOk, error, health } = useLive();
  const now = useNow(2000);
  const stale = !lastOk || now - lastOk > STALE_AFTER_MS;
  const dbProblem = health && (health.postgres !== 'ok' || health.influx !== 'ok' || !health.worker_alive);
  if (!stale && !dbProblem) return null;
  return (
    <div className="banner banner-stale" role="alert">
      <strong>Data is not updating.</strong>{' '}
      {lastOk ? `Last good update ${fmtTime(lastOk)} (${ago(lastOk, now)}).` : 'No data received yet.'}{' '}
      {error && <span>Reason: {error}.</span>}
      {dbProblem && !stale && (
        <span> Backend problem: database {health.postgres}, time-series {health.influx},
          detector {health.worker_alive ? 'running' : 'STOPPED'}.</span>
      )}
      {' '}Do not treat this screen as "all clear".
    </div>
  );
}

// Decision 6.6: critical banner + sound until someone presses "I've seen it".
export function CriticalBanner() {
  const { events, operator, refresh, soundOn } = useLive();
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);
  const unacked = events.filter((e) => e.event_type === 'landslide' && e.current_level === 'critical' && !e.acknowledged_at);
  useAlarmSound(soundOn && unacked.length > 0);
  if (!unacked.length) return null;

  const ack = async (id) => {
    setBusy(id);
    setErr(null);
    try {
      await api.acknowledge(id, operator || 'operator');
      await refresh();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="banner banner-critical" role="alert">
      {unacked.map((e) => (
        <div key={e.id} className="banner-row">
          <span className="banner-title">CRITICAL</span>
          <span>
            <Link to={`/events/${e.id}`}>{shortName(e.node_name)}</Link>
            {e.is_virtual && <span className="sim-inline"> (simulated)</span>} since {fmtTime(e.opened_at)} -{' '}
            <span className="banner-reason">{e.reason}</span>
          </span>
          <button className="btn btn-light" disabled={busy === e.id} onClick={() => ack(e.id)}>
            {busy === e.id ? 'Saving...' : "I've seen it"}
          </button>
        </div>
      ))}
      {err && <div className="small">Could not save: {err}</div>}
    </div>
  );
}

// A short two-tone beep every 2 s. Browsers only allow sound after a click,
// which is why the "Sound" button exists.
function useAlarmSound(active) {
  const ctxRef = useRef(null);
  useEffect(() => {
    if (!active) return undefined;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return undefined;
    if (!ctxRef.current) ctxRef.current = new AC();
    const ctx = ctxRef.current;
    const beep = () => {
      [880, 660].forEach((f, i) => {
        const o = ctx.createOscillator();
        const g = ctx.createGain();
        o.frequency.value = f;
        g.gain.value = 0.08;
        o.connect(g).connect(ctx.destination);
        const t = ctx.currentTime + i * 0.18;
        o.start(t);
        o.stop(t + 0.15);
      });
    };
    beep();
    const t = setInterval(beep, 2000);
    return () => clearInterval(t);
  }, [active]);
}
