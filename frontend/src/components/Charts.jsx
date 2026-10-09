import {
  ResponsiveContainer, ComposedChart, Line, Scatter, XAxis, YAxis, CartesianGrid, Tooltip,
} from 'recharts';
import { fmtHM, fmtTime, tierMeta } from '../format';

const LINE = '#9ecbff';        // one neutral series colour (status colours stay reserved for tiers)
const EVENT = '#e6edf3';
const GRID = '#1f2a37';
const AXIS = '#7d8a99';

// Average into at most `max` buckets so long ranges stay fast and readable.
function downsample(points, max = 600) {
  if (points.length <= max) return points;
  const size = Math.ceil(points.length / max);
  const out = [];
  for (let i = 0; i < points.length; i += size) {
    const chunk = points.slice(i, i + size);
    out.push({ t: chunk[Math.floor(chunk.length / 2)].t, v: chunk.reduce((s, p) => s + p.v, 0) / chunk.length });
  }
  return out;
}

const toPoints = (series) => (series || []).map(([t, v]) => ({ t: new Date(t).getTime(), v }));

function ChartTooltip({ active, payload, unit, digits }) {
  if (!active || !payload || !payload.length) return null;
  const p = payload[0].payload;
  const isEvent = payload[0].name === 'Motion burst';
  return (
    <div className="chart-tip">
      <div className="muted">{fmtTime(p.t)}</div>
      <div><strong>{p.v.toFixed(digits)}</strong> {unit}{isEvent ? ' (motion burst)' : ''}</div>
    </div>
  );
}

export function TimeSeriesChart({ title, unit, series, events, domain, digits = 1, yDomain, height = 170, note }) {
  const pts = downsample(toPoints(series));
  const evs = toPoints(events);
  return (
    <figure className="chart">
      <figcaption>
        <span className="chart-title">{title}</span>
        <span className="muted small">{unit}{note ? ` · ${note}` : ''}</span>
      </figcaption>
      {pts.length === 0 && evs.length === 0 ? (
        <div className="chart-empty">No readings in this period.</div>
      ) : (
        <ResponsiveContainer width="100%" height={height}>
          <ComposedChart margin={{ top: 6, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="t" type="number" scale="time" domain={domain} tickFormatter={fmtHM}
                   stroke={AXIS} tick={{ fontSize: 11 }} minTickGap={40} allowDataOverflow />
            <YAxis dataKey="v" stroke={AXIS} tick={{ fontSize: 11 }} width={46}
                   domain={yDomain || ['auto', 'auto']} tickFormatter={(v) => Number(v).toFixed(digits)} />
            <Tooltip content={<ChartTooltip unit={unit} digits={digits} />}
                     cursor={{ stroke: AXIS, strokeDasharray: '3 3' }} />
            <Line data={pts} dataKey="v" name={title} stroke={LINE} strokeWidth={2} dot={false}
                  isAnimationActive={false} />
            {evs.length > 0 && (
              <Scatter data={evs} dataKey="v" name="Motion burst" fill={EVENT} shape="diamond"
                       isAnimationActive={false} />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </figure>
  );
}

// Coloured strip of the node's tier over time (from tier_history), with the tier word inside.
export function TierStrip({ history, currentTier, from, to }) {
  const segs = [];
  const sorted = [...(history || [])].sort((a, b) => new Date(a.at) - new Date(b.at));
  let tier = sorted.length ? sorted[0].from_tier : currentTier;
  let start = from;
  for (const h of sorted) {
    const at = new Date(h.at).getTime();
    if (at > start) segs.push({ tier, start, end: Math.min(at, to) });
    tier = h.to_tier;
    start = Math.max(at, from);
  }
  if (to > start) segs.push({ tier: tier || currentTier, start, end: to });
  const span = to - from || 1;
  return (
    <div className="tier-strip-wrap">
      <div className="small muted">Tier over time</div>
      <div className="tier-strip" role="img" aria-label="Tier history">
        {segs.filter((s) => s.end > s.start).map((s, i) => {
          const m = tierMeta(s.tier);
          const pct = ((s.end - s.start) / span) * 100;
          return (
            <div key={i} className="tier-seg" style={{ width: `${pct}%`, background: m.color, color: m.ink }}
                 title={`${m.label}: ${fmtTime(s.start)} - ${fmtTime(s.end)}`}>
              {pct > 9 ? m.label : ''}
            </div>
          );
        })}
      </div>
      <div className="tier-strip-axis small muted"><span>{fmtHM(from)}</span><span>{fmtHM(to)}</span></div>
    </div>
  );
}
