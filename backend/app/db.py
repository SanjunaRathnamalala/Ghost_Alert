"""PostgreSQL helpers. All SQL uses parameters, never pasted values (decision 7.8)."""
from pathlib import Path

from sqlalchemy import create_engine, text

SCHEMA = Path(__file__).with_name("schema.sql")

NODE_COLS = """n.id, n.radio_id, n.name, n.node_type, n.zone_id, n.latitude, n.longitude,
               n.moisture_dry_raw, n.moisture_wet_raw, n.lifecycle, n.is_virtual"""


def make_engine(url):
    return create_engine(url, pool_pre_ping=True, future=True)


def apply_schema(engine):
    with engine.begin() as conn:
        conn.exec_driver_sql(SCHEMA.read_text())


def node_by_radio(conn, radio_id):
    return conn.execute(text(f"SELECT {NODE_COLS} FROM sensor_nodes n WHERE n.radio_id = :r"),
                        {"r": radio_id}).mappings().first()


def node_by_id(conn, node_id):
    return conn.execute(text(f"SELECT {NODE_COLS} FROM sensor_nodes n WHERE n.id = :i"),
                        {"i": str(node_id)}).mappings().first()


def landslide_candidates(conn):
    """Neighbour candidates for corroboration: retired nodes never count (decision 3.15)."""
    return [dict(r) for r in conn.execute(text("""
        SELECT id, latitude, longitude FROM sensor_nodes
        WHERE node_type = 'landslide' AND lifecycle <> 'retired'
          AND latitude IS NOT NULL AND longitude IS NOT NULL""")).mappings()]


def ensure_status_row(conn, node_id):
    conn.execute(text("INSERT INTO node_status (node_id) VALUES (:i) ON CONFLICT (node_id) DO NOTHING"),
                 {"i": str(node_id)})


def log_event(conn, event_id, at, action, from_level=None, to_level=None, actor="system", note=None):
    conn.execute(text("""INSERT INTO event_log (event_id, at, action, from_level, to_level, actor, note)
                         VALUES (:e, :at, :a, :f, :t, :actor, :note)"""),
                 {"e": event_id, "at": at, "a": action, "f": from_level, "t": to_level,
                  "actor": actor, "note": note})
