import { useEffect, useMemo, useRef } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Circle, useMap } from 'react-leaflet';
import L from 'leaflet';
import { Link } from 'react-router-dom';
import { tierMeta, patternLabel, hasPatterns, shortName, ago } from '../format';
import { TierBadge, SimBadge, OfflineBadge } from './Badges';

const DEFAULT_CENTER = [6.7969, 79.9018];

// Map background. CARTO dark tiles need a (free) key: put VITE_CARTO_KEY=... in frontend/.env.
// Without a key we use OpenStreetMap tiles and darken them with CSS (.tiles-dark in styles.css).
const CARTO_KEY = import.meta.env.VITE_CARTO_KEY;
const OSM_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const TILES = CARTO_KEY
  ? { url: `https://basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}.png?key=${CARTO_KEY}`,
      attribution: `${OSM_ATTR}, &copy; <a href="https://carto.com/attributions">CARTO</a>`, maxZoom: 20 }
  : { url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
      attribution: OSM_ATTR, maxZoom: 19, className: 'tiles-dark' };

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// Circle = landslide node, square = wildlife node; dashed ring = SIMULATED; grey ring = offline.
// Every marker carries its name and tier as text (never colour alone).
function markerIcon(n) {
  const m = tierMeta(n.tier);
  const shape = n.node_type === 'wildlife' ? 'mk-square' : 'mk-circle';
  const cls = ['mk', shape, n.is_virtual ? 'mk-virtual' : '', n.online === false ? 'mk-offline' : ''].join(' ');
  const label = `${shortName(n.name)} · ${n.online === false ? 'Offline' : m.label}`;
  return L.divIcon({
    className: 'mk-wrap',
    html: `<div class="${cls}" style="--c:${m.color}"></div><div class="mk-label">${esc(label)}</div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
    popupAnchor: [0, -10],
  });
}

function FitToNodes({ nodes }) {
  const map = useMap();
  const done = useRef(false);
  useEffect(() => {
    const pts = nodes.filter((n) => n.latitude != null).map((n) => [n.latitude, n.longitude]);
    if (done.current || !pts.length) return;
    done.current = true;
    if (pts.length === 1) map.setView(pts[0], 18);
    else map.fitBounds(pts, { padding: [60, 60], maxZoom: 19 });
  }, [nodes, map]);
  return null;
}

export default function NodeMap({ nodes, events, height = '100%' }) {
  const located = nodes.filter((n) => n.latitude != null && n.longitude != null);
  const byId = useMemo(() => Object.fromEntries(nodes.map((n) => [n.id, n])), [nodes]);
  // Decision 6.4: 50 m hazard circles only for OPEN warning / critical landslide events.
  const hazards = events.filter((e) => e.event_type === 'landslide' && ['warning', 'critical'].includes(e.current_level));

  return (
    <MapContainer center={DEFAULT_CENTER} zoom={17} style={{ height, width: '100%' }} className="map">
            <TileLayer {...TILES} />
      <FitToNodes nodes={located} />
      {hazards.map((e) => {
        const n = byId[e.node_id];
        if (!n || n.latitude == null) return null;
        const c = tierMeta(e.current_level).color;
        return (
          <Circle key={`hz-${e.id}`} center={[n.latitude, n.longitude]} radius={50}
                  pathOptions={{ color: c, fillColor: c, fillOpacity: 0.12, weight: 1.5, dashArray: '4 4' }} />
        );
      })}
      {located.map((n) => (
        <Marker key={n.id} position={[n.latitude, n.longitude]} icon={markerIcon(n)}>
          <Popup>
            <div className="popup">
              <div className="popup-title">
                {n.name} {n.is_virtual && <SimBadge />} {n.online === false && <OfflineBadge />}
              </div>
              <div><TierBadge tier={n.tier} size="sm" /></div>
              {hasPatterns(n) && (
                <div className="small">
                  Moisture: {patternLabel('moisture', n.moisture_pattern)}<br />
                  Tilt: {patternLabel('tilt', n.tilt_pattern)}
                </div>
              )}
              {n.reason && <div className="small muted">{n.reason}</div>}
              <div className="small muted">Last seen {ago(n.last_seen_at)}</div>
              <Link to={`/nodes/${n.id}`}>Open node page</Link>
            </div>
          </Popup>
        </Marker>
      ))}
    </MapContainer>
  );
}
