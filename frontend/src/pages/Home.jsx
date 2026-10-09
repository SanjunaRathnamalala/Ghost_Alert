import { Link } from 'react-router-dom';

const FEATURES = [
  ['Tilt + soil moisture', 'ADXL362 accelerometer and a capacitive soil sensor on each node.'],
  ['Pattern-classified detection', '9 moisture and 8 tilt patterns, decided by the PCHA matrix.'],
  ['Neighbour confirmation', 'Critical only when 3 or more nodes within 50 m also show movement.'],
  ['Fault-aware', 'A faulty sensor never hides a landslide; a silent node shows "no data", never "safe".'],
  ['Reliable link', 'Packet counters find lost and repeated packets; the gateway stamps the time.'],
  ['Alerts', 'Live map and Telegram. Up at once, down only after a hold time; operators acknowledge and close.'],
];

export default function Home() {
  return (
    <div className="home">
      <div className="hero">
        <div>
          <h1>EARLY <span className="accent">HAZARD</span> WARNING</h1>
          <p className="lead">Low-cost IoT landslide early warning: sensor nodes, LoRa, and pattern-classified hazard assessment.</p>
          <div className="hero-actions">
            <Link to="/dashboard" className="btn btn-primary btn-lg">Open dashboard</Link>
            <Link to="/events" className="btn btn-lg">Alert history</Link>
          </div>
        </div>
        <img className="hero-icon" src="/ghost.png" alt="" onError={(e) => { e.currentTarget.style.display = 'none'; }} />
      </div>
      <div className="features">
        {FEATURES.map(([t, d]) => (
          <div key={t} className="feature">
            <h3>{t}</h3>
            <p>{d}</p>
          </div>
        ))}
      </div>
      <p className="small muted">Prototype system - not an official warning. Follow NBRO and DMC advice.</p>
    </div>
  );
}
