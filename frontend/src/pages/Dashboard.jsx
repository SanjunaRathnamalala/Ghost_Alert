import { useLive } from '../live';
import NodeMap from '../components/NodeMap';
import { AlertList, NodeList, ServiceList } from '../components/Panels';
import { needsService } from '../format';

export default function Dashboard() {
  const { nodes, events } = useLive();
  const anyVirtual = nodes.some((n) => n.is_virtual);
  const service = nodes.filter(needsService).length;
  return (
    <div className="dash">
      <section className="dash-map">
        <NodeMap nodes={nodes} events={events} />
        <div className="map-legend small">
          <span><i className="lg lg-circle" /> landslide node</span>
          <span><i className="lg lg-dashed" /> simulated</span>
          <span><i className="lg lg-off" /> offline</span>
          <span><i className="lg lg-zone" /> 50 m hazard zone</span>
        </div>
      </section>
      <aside className="dash-side">
        {anyVirtual && (
          <p className="note">
            Nodes marked SIMULATED are virtual neighbours driven by the simulator. GA-LS-001 is the real bench node.
          </p>
        )}
        <h2>Open alerts <span className="muted">({events.length})</span></h2>
        <AlertList events={events} />
        <h2>Needs service <span className="muted">({service})</span></h2>
        <ServiceList nodes={nodes} />
        <h2>Nodes <span className="muted">({nodes.length})</span></h2>
        <NodeList nodes={nodes} />
      </aside>
    </div>
  );
}
