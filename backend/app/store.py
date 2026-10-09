"""
Time-series storage (topic 3a).

Measurement "node_telemetry", one tag "node_id" (the PostgreSQL UUID).
Readings with a bad gateway clock go to "node_telemetry_untimed" (decision 3.5).

Two implementations with the same behaviour:
  InfluxStore  - the real one
  MemoryStore  - for tests and fast simulation
Range rule in both: start <= time < stop (like InfluxDB).
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

MEASUREMENT = "node_telemetry"
MEASUREMENT_UNTIMED = "node_telemetry_untimed"

ALLOWED_FIELDS = {
    "moisture_index", "moisture_raw", "tilt_deg", "tilt_event",
    "accel_x", "accel_y", "accel_z", "temp_c",
    "battery_mv", "rssi", "snr",
    "burst_peak_mg", "burst_duration_s", "pir_triggers",
}


@dataclass
class Reading:
    node_id: str
    time: datetime
    fields: dict = field(default_factory=dict)
    measurement: str = MEASUREMENT


def _check(node_id, fields, measurement):
    # Values that end up inside a query string are validated first (decision 7.8).
    uuid.UUID(str(node_id))
    bad = set(fields) - ALLOWED_FIELDS
    if bad:
        raise ValueError(f"unknown fields: {sorted(bad)}")
    if measurement not in (MEASUREMENT, MEASUREMENT_UNTIMED):
        raise ValueError(f"unknown measurement {measurement}")


def _utc(t: datetime) -> datetime:
    if t.tzinfo is None:
        raise ValueError("times must be timezone-aware (UTC)")
    return t.astimezone(timezone.utc)


class MemoryStore:
    def __init__(self):
        # (measurement, node_id, field, time) -> value. Same key = overwrite, like InfluxDB.
        self._data = {}

    def write(self, readings):
        for r in readings:
            _check(r.node_id, r.fields, r.measurement)
            for f, v in r.fields.items():
                if v is not None:
                    self._data[(r.measurement, str(r.node_id), f, _utc(r.time))] = float(v)

    def fetch(self, node_id, fields, start, stop, measurement=MEASUREMENT):
        _check(node_id, fields, measurement)
        start, stop, fields, nid = _utc(start), _utc(stop), set(fields), str(node_id)
        out = [{"time": t, "field": f, "value": v}
               for (m, n, f, t), v in self._data.items()
               if m == measurement and n == nid and f in fields and start <= t < stop]
        return sorted(out, key=lambda r: (r["time"], r["field"]))

    def delete_node(self, node_id, start, stop):
        nid = str(node_id)
        self._data = {k: v for k, v in self._data.items()
                      if not (k[1] == nid and _utc(start) <= k[3] < _utc(stop))}

    def ping(self):
        return True


class InfluxStore:
    def __init__(self, url, token, org, bucket):
        from influxdb_client import InfluxDBClient
        from influxdb_client.client.write_api import SYNCHRONOUS
        self.org, self.bucket = org, bucket
        self.client = InfluxDBClient(url=url, token=token, org=org, timeout=10_000)
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
        self.query_api = self.client.query_api()

    def write(self, readings):
        from influxdb_client import Point, WritePrecision
        points = []
        for r in readings:
            _check(r.node_id, r.fields, r.measurement)
            p = Point(r.measurement).tag("node_id", str(r.node_id)).time(_utc(r.time), WritePrecision.MS)
            n = 0
            for f, v in r.fields.items():
                if v is not None:
                    p = p.field(f, float(v))   # always float: avoids InfluxDB field-type conflicts
                    n += 1
            if n:
                points.append(p)
        if points:
            self.write_api.write(bucket=self.bucket, org=self.org, record=points)

    def fetch(self, node_id, fields, start, stop, measurement=MEASUREMENT):
        _check(node_id, fields, measurement)
        field_set = ", ".join(f'"{f}"' for f in sorted(set(fields)))
        flux = f'''
            from(bucket: "{self.bucket}")
            |> range(start: {_utc(start).isoformat()}, stop: {_utc(stop).isoformat()})
            |> filter(fn: (r) => r["_measurement"] == "{measurement}")
            |> filter(fn: (r) => r["node_id"] == "{uuid.UUID(str(node_id))}")
            |> filter(fn: (r) => contains(value: r["_field"], set: [{field_set}]))
        '''
        tables = self.query_api.query(flux, org=self.org)
        out = [{"time": rec.get_time(), "field": rec.get_field(), "value": rec.get_value()}
               for t in tables for rec in t.records]
        return sorted(out, key=lambda r: (r["time"], r["field"]))

    def delete_node(self, node_id, start, stop):
        """Removes one node's readings (used by the simulator's --fresh option)."""
        self.client.delete_api().delete(
            _utc(start), _utc(stop), f'node_id="{uuid.UUID(str(node_id))}"',
            bucket=self.bucket, org=self.org)

    def ping(self):
        return self.client.ping()
