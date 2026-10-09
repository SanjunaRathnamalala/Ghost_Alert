"""
Registers the demo nodes (replaces the admin pages for the 2-day demo).

  radio 1    GA-LS-001   real landslide node (ADXL362 + soil sensor)
  radio 101-103 GA-LS-V01..V03  VIRTUAL neighbours (simulated, always labelled)
  (V04 is added by tools/simulate.py; the PIR node was dropped)

Run from the backend folder:  python -m scripts.seed_demo
Change LAT / LON to where you want the demo slope to appear on the map.
"""
import math

from sqlalchemy import text

from app import db
from app.config import load_settings

LAT, LON = 6.79690, 79.90180          # demo location (University of Moratuwa area)
M_PER_DEG = 111_320.0                 # metres per degree of latitude (approx.)

NODES = [
    # radio, name, type, north_m, east_m, virtual
    (1, "GA-LS-001", "landslide", 0, 0, False),
    (101, "GA-LS-V01", "landslide", 20, 10, True),
    (102, "GA-LS-V02", "landslide", -15, 25, True),
    (103, "GA-LS-V03", "landslide", 30, -20, True),
]


def main():
    s = load_settings()
    engine = db.make_engine(s.pg_url)
    db.apply_schema(engine)
    with engine.begin() as c:
        zid = c.execute(text("""INSERT INTO zones (name, description, center_lat, center_lon, radius_m)
                                VALUES ('Demo slope', 'Bench prototype + virtual neighbours', :lat, :lon, 80)
                                ON CONFLICT (name) DO UPDATE SET center_lat = :lat, center_lon = :lon
                                RETURNING id"""), {"lat": LAT, "lon": LON}).scalar_one()
        for radio, name, kind, north, east, virtual in NODES:
            lat = LAT + north / M_PER_DEG
            lon = LON + east / (M_PER_DEG * math.cos(math.radians(LAT)))
            c.execute(text("""
                INSERT INTO sensor_nodes (radio_id, name, node_type, zone_id, latitude, longitude, is_virtual,
                                          lifecycle, notes)
                VALUES (:r, :n, :k, :z, :lat, :lon, :v, :life, :notes)
                ON CONFLICT (radio_id) DO UPDATE SET name = :n, node_type = :k, zone_id = :z,
                    latitude = :lat, longitude = :lon, is_virtual = :v"""),
                {"r": radio, "n": name, "k": kind, "z": zid, "lat": lat, "lon": lon, "v": virtual,
                 "life": "active" if virtual else "registered",
                 "notes": "SIMULATED node for the demo" if virtual else "bench prototype"})
            print(f"  {name:11s} radio {radio:<4d} {kind:9s} {'VIRTUAL' if virtual else 'real':7s} "
                  f"{lat:.6f}, {lon:.6f}")
    print("Done.")


if __name__ == "__main__":
    main()
