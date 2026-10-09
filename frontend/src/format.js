// Time formatting (always Sri Lanka time, decision 2.12), tiers, patterns and flags.
export const TZ = 'Asia/Colombo';

const timeFmt = new Intl.DateTimeFormat('en-GB', {
  timeZone: TZ, hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
});
const hmFmt = new Intl.DateTimeFormat('en-GB', { timeZone: TZ, hour: '2-digit', minute: '2-digit', hour12: false });
const dtFmt = new Intl.DateTimeFormat('en-GB', {
  timeZone: TZ, day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
});

export const fmtTime = (v) => (v ? timeFmt.format(new Date(v)) : '—');
export const fmtHM = (v) => (v ? hmFmt.format(new Date(v)) : '—');
export const fmtDateTime = (v) => (v ? dtFmt.format(new Date(v)) : '—');

export function ago(v, now = Date.now()) {
  if (!v) return 'never';
  const s = Math.max(0, Math.round((now - new Date(v).getTime()) / 1000));
  if (s < 60) return `${s} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${(s / 3600).toFixed(1)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

// Severity colours: validated for colour-blind separation on the dark surface,
// and ALWAYS shown together with the tier word (never colour alone).
export const TIERS = {
  critical: { label: 'Critical', color: '#d62f2f', ink: '#fff', rank: 4,
    help: 'Strong movement pattern, confirmed by 3 or more neighbours within 50 m.' },
  warning: { label: 'Warning', color: '#f0912e', ink: '#1b1205', rank: 3,
    help: 'A dangerous pattern on this node. A person should look.' },
  watch: { label: 'Watch', color: '#f7df8b', ink: '#2a2205', rank: 2,
    help: 'Something to keep an eye on (for example steady rain). No alert is sent.' },
  stand_down: { label: 'Stand down', color: '#58a6ff', ink: '#06182c', rank: 1,
    help: 'Movement has stopped and the soil is not getting wetter.' },
  normal: { label: 'Normal', color: '#2ea043', ink: '#fff', rank: 0,
    help: 'No hazard pattern.' },
  unreliable: { label: 'Unreliable', color: '#8b949e', ink: '#111', rank: -1,
    help: 'Both sensors look faulty. The node needs service.' },
  no_data: { label: 'No data', color: '#8b949e', ink: '#111', rank: -1,
    help: 'Not enough recent data. A silent node is never shown as safe.' },
};

export function tierMeta(t) {
  return TIERS[t] || { label: 'Not checked', color: '#57606a', ink: '#fff', rank: -2, help: 'No PCHA result yet.' };
}

export const MOISTURE_PATTERNS = {
  dry_flat: ['Dry, steady', 'Soil is not wet and not changing.'],
  brief_shower: ['Brief shower', 'Quick rise in the last 15 min only.'],
  sustained_wetting: ['Sustained wetting', 'Soil has been getting wetter over the day.'],
  saturated_flat: ['Saturated', 'Soil was already wet and stays wet.'],
  rain_on_wet: ['Rain on wet soil', 'New rain on ground that was already wet - the riskiest case.'],
  draining: ['Draining', 'Soil is drying out.'],
  glitch: ['Glitch filtered', 'One bad reading was removed; trend not trusted this time.'],
  bouncing: ['Bouncing (faulty?)', 'Readings jump around more than normal - sensor may be faulty.'],
  dead: ['Dead sensor', 'Readings are stuck - the sensor is not working. Decided on tilt alone.'],
};

export const TILT_PATTERNS = {
  stable: ['Stable', 'No significant movement.'],
  primary_creep: ['Primary creep', 'Moving, but slowing down (settling).'],
  secondary_creep: ['Secondary creep', 'Moving at a steady rate.'],
  tertiary_creep: ['Tertiary creep', 'Moving and speeding up.'],
  near_failure: ['Near failure', 'Fast and speeding up (over 0.1 deg/h).'],
  knock: ['Knock (rejected)', 'A sudden spike, like a knock - not treated as ground movement.'],
  thermal: ['Quiet / thermal band', 'No coherent trend; small changes within its normal (temperature) band.'],
  stopped: ['Stopped', 'Was moving in the last 6 h, now stopped.'],
};

export function patternLabel(kind, p) {
  const table = kind === 'moisture' ? MOISTURE_PATTERNS : TILT_PATTERNS;
  return (table[p] || [p || '—', ''])[0];
}

export function patternHelp(kind, p) {
  const table = kind === 'moisture' ? MOISTURE_PATTERNS : TILT_PATTERNS;
  return (table[p] || ['', ''])[1];
}

// Patterns are only meaningful when the last check had enough data. A silent node must never
// show old "Dry, steady / Stable" text that reads like "safe".
export const hasPatterns = (n) => n.node_type === 'landslide' && !!n.tier && n.tier !== 'no_data';

export function decodeFlags(f) {
  if (!f) return [];
  const out = [];
  if (f & 1) out.push('Soil sensor error');
  if (f & 2) out.push('Accelerometer error');
  if (f & 4) out.push('Battery low');
  return out;
}

export const RESET_REASONS = { 0: 'unknown', 1: 'power on', 2: 'reset pin', 4: 'low voltage (brown-out)', 8: 'watchdog (crash)' };

export function shortName(name) {
  return (name || '').replace(/^GA-/, '');
}

export function needsService(n) {
  return n.online === false || n.tier === 'no_data' || n.tier === 'unreliable' || (n.sensor_flags || 0) !== 0;
}
