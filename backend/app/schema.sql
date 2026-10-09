-- Ghost_Alert v1 - demo subset of the design (topic 3b). Safe to run many times.
-- Cut for the demo: users, gateways, alert_recipients, notifications, audit_log.

CREATE TABLE IF NOT EXISTS zones (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    center_lat  DOUBLE PRECISION,
    center_lon  DOUBLE PRECISION,
    radius_m    DOUBLE PRECISION NOT NULL DEFAULT 200
);

-- Static data, set by the admin (decision 3.8).
CREATE TABLE IF NOT EXISTS sensor_nodes (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    radio_id          INTEGER NOT NULL UNIQUE CHECK (radio_id BETWEEN 1 AND 65535),
    name              TEXT NOT NULL UNIQUE,
    node_type         TEXT NOT NULL CHECK (node_type IN ('landslide', 'wildlife')),
    zone_id           INTEGER REFERENCES zones(id),
    latitude          DOUBLE PRECISION,
    longitude         DOUBLE PRECISION,
    moisture_dry_raw  INTEGER NOT NULL DEFAULT 620,
    moisture_wet_raw  INTEGER NOT NULL DEFAULT 280,
    lifecycle         TEXT NOT NULL DEFAULT 'registered'
                      CHECK (lifecycle IN ('registered', 'active', 'retired')),
    is_virtual        BOOLEAN NOT NULL DEFAULT FALSE,   -- simulated node, always labelled in the UI
    installed_at      TIMESTAMPTZ,
    notes             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Changing data, written by the system (decision 3.8).
CREATE TABLE IF NOT EXISTS node_status (
    node_id            UUID PRIMARY KEY REFERENCES sensor_nodes(id),
    last_seen_at       TIMESTAMPTZ,
    last_heartbeat_at  TIMESTAMPTZ,
    last_gateway_id    TEXT,
    online             BOOLEAN NOT NULL DEFAULT FALSE,
    battery_mv         INTEGER,
    rssi               INTEGER,
    snr                REAL,
    sensor_flags       INTEGER NOT NULL DEFAULT 0,
    firmware_version   INTEGER,
    last_reset_reason  INTEGER,
    boot_number        INTEGER,
    last_counter       INTEGER,
    packets_received   BIGINT NOT NULL DEFAULT 0,
    packets_lost       BIGINT NOT NULL DEFAULT 0,
    counting_since     TIMESTAMPTZ NOT NULL DEFAULT now(),
    tier               TEXT,
    moisture_pattern   TEXT,
    tilt_pattern       TEXT,
    reason             TEXT,
    evaluated_at       TIMESTAMPTZ,
    tier_since         TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS hazard_events (
    id                 BIGSERIAL PRIMARY KEY,
    node_id            UUID NOT NULL REFERENCES sensor_nodes(id),
    event_type         TEXT NOT NULL CHECK (event_type IN ('landslide', 'wildlife')),
    current_level      TEXT NOT NULL,
    peak_level         TEXT NOT NULL,
    state              TEXT NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'resolved')),
    opened_at          TIMESTAMPTZ NOT NULL,
    last_changed_at    TIMESTAMPTZ NOT NULL,
    lower_candidate    TEXT,
    lower_since        TIMESTAMPTZ,
    calm_since         TIMESTAMPTZ,
    ready_to_close_at  TIMESTAMPTZ,
    acknowledged_at    TIMESTAMPTZ,
    acknowledged_by    TEXT,
    last_notified_at   TIMESTAMPTZ,
    resolved_at        TIMESTAMPTZ,
    resolved_by        TEXT,
    resolve_note       TEXT,
    reason             TEXT,
    trigger_count      INTEGER NOT NULL DEFAULT 0,
    last_trigger_at    TIMESTAMPTZ
);
-- Decision 4.10: at most one OPEN event per node and type.
CREATE UNIQUE INDEX IF NOT EXISTS one_open_event_per_node
    ON hazard_events (node_id, event_type) WHERE state = 'open';

CREATE TABLE IF NOT EXISTS event_log (
    id          BIGSERIAL PRIMARY KEY,
    event_id    BIGINT NOT NULL REFERENCES hazard_events(id),
    at          TIMESTAMPTZ NOT NULL,
    action      TEXT NOT NULL,
    from_level  TEXT,
    to_level    TEXT,
    actor       TEXT NOT NULL DEFAULT 'system',
    note        TEXT
);
CREATE INDEX IF NOT EXISTS event_log_event ON event_log (event_id, at);

CREATE TABLE IF NOT EXISTS tier_history (
    id         BIGSERIAL PRIMARY KEY,
    node_id    UUID NOT NULL REFERENCES sensor_nodes(id),
    at         TIMESTAMPTZ NOT NULL,
    from_tier  TEXT,
    to_tier    TEXT NOT NULL,
    reason     TEXT
);
CREATE INDEX IF NOT EXISTS tier_history_node ON tier_history (node_id, at);

-- Decision 1.5: unknown radio IDs are logged, not silently dropped.
CREATE TABLE IF NOT EXISTS unknown_packets (
    radio_id          INTEGER PRIMARY KEY,
    last_gateway_id   TEXT,
    first_seen_at     TIMESTAMPTZ NOT NULL,
    last_seen_at      TIMESTAMPTZ NOT NULL,
    times_seen        INTEGER NOT NULL DEFAULT 1,
    last_payload_hex  TEXT
);
