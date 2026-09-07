from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timezone

# ==========================================
# 1. DATABASE CONFIGURATION
# ==========================================
PG_URL = "postgresql://ghost:1111@localhost:5432/ghost_alert_relational"

INFLUX_URL = "http://localhost:8086"
INFLUX_TOKEN = "ew0E0bEpcjbW-BbwIve5kwQg0VynvlkGbqJzIozGli9M2i3OG5bxzzMCwr67Hj5_qhgbYfYXocYfvL8NqZnBSQ=="
INFLUX_ORG = "ghost_alert_work"
INFLUX_BUCKET = "ghost_alert_raw"

# Initialize Database Connections
pg_engine = create_engine(PG_URL)
influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
write_api = influx_client.write_api(write_options=SYNCHRONOUS)
query_api = influx_client.query_api()

app = FastAPI(title="Ghost_Alert API")

# Allow React to talk to FastAPI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 2. DATA STRUCTURE (Like a C++ Struct)
# ==========================================
class TelemetryPayload(BaseModel):
    hardware_id: str
    moisture_pct: float
    accel_x: float
    accel_y: float
    accel_z: float
    tilt_variance: float
    battery_volts: float
    rssi: int
    pir_trigger: int = 0

# ==========================================
# 3. THE INGESTION ENDPOINT
# ==========================================
@app.post("/api/v1/telemetry")
async def receive_telemetry(data: TelemetryPayload):
    
    # --- STEP A: Authenticate Node & Auto-Update Status ---
    with pg_engine.begin() as conn:
        query = text("SELECT id, zone_id, node_type FROM sensor_nodes WHERE hardware_id = :hw_id")
        result = conn.execute(query, {"hw_id": data.hardware_id}).fetchone()
        
        if not result:
            raise HTTPException(status_code=401, detail="Unauthorized Node")
            
        node_id = str(result[0])
        zone_id = str(result[1]) if result[1] else "unassigned"
        node_type = str(result[2]) 

        # Automatically set node to active and update heartbeat
        update_status = text("UPDATE sensor_nodes SET status = 'active', last_heartbeat = NOW() WHERE id = :nid")
        conn.execute(update_status, {"nid": node_id})


    # --- STEP B: Write Time-Series Data to InfluxDB ---
    # InfluxDB uses "Points" to construct the Line Protocol we designed
    point = (
        Point("node_telemetry")
        .tag("node_id", node_id)
        .tag("zone_id", zone_id)
        .field("moisture_pct", data.moisture_pct)
        .field("tilt_variance", data.tilt_variance)
        .field("battery_volts", data.battery_volts)
        .field("rssi", data.rssi)
        .field("pir_trigger", data.pir_trigger)
    )
    
    # Execute the write to the InfluxDB bucket
    write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)

    # --- STEP C: Evaluate Hazard Logic ---
    with pg_engine.begin() as conn:
        # Check if an unresolved hazard already exists for this node
        check_query = text("SELECT id FROM hazard_events WHERE node_id = :nid AND is_resolved = False")
        active_event = conn.execute(check_query, {"nid": node_id}).fetchone()

        if not active_event:
            hazard_type = None
            
            # Logic 1: Wildlife Intrusion
            if node_type == 'wildlife' and data.pir_trigger == 1:
                hazard_type = 'wildlife_detected'
                
            # Logic 2: Predictive Landslide
            elif node_type == 'landslide':
                # Query InfluxDB for the last 15 minutes of data for this specific node
                flux_query = f"""
                    from(bucket: "{INFLUX_BUCKET}")
                    |> range(start: -15m)
                    |> filter(fn: (r) => r["_measurement"] == "node_telemetry")
                    |> filter(fn: (r) => r["node_id"] == "{node_id}")
                    |> filter(fn: (r) => r["_field"] == "moisture_pct" or r["_field"] == "tilt_variance")
                """
                tables = query_api.query(flux_query, org=INFLUX_ORG)
                
                moisture_records = []
                tilt_records = []
                
                # Parse the Flux tables into Python lists
                for table in tables:
                    for record in table.records:
                        if record.get_field() == "moisture_pct":
                            moisture_records.append(record.get_value())
                        elif record.get_field() == "tilt_variance":
                            tilt_records.append(record.get_value())
                
                # We need at least 2 data points to calculate velocity/change
                if len(moisture_records) >= 2:
                    oldest_moisture = moisture_records[0]
                    current_moisture = moisture_records[-1]
                    moisture_roc = current_moisture - oldest_moisture
                    
                    max_tilt = max(tilt_records) if tilt_records else 0.0
                    
                    # THE PREDICTIVE TRIGGERS:
                    # Trigger A (Saturation Velocity): Rapid >10% moisture jump and soil is wet (>60%)
                    # Trigger B (Slope Creep): Sustained micro-tilt (>0.5 deg) and soil is wet (>60%)
                    if (moisture_roc > 10.0 and current_moisture > 60.0) or (max_tilt > 0.5 and current_moisture > 60.0):
                        hazard_type = 'landslide_imminent'
                
            # If a hazard condition is met, trigger the alert
            if hazard_type:
                insert_query = text("""
                    INSERT INTO hazard_events (node_id, zone_id, event_type, severity) 
                    VALUES (:nid, :zid, :htype, 'critical')
                """)
                conn.execute(insert_query, {"nid": node_id, "zid": zone_id, "htype": hazard_type})
                print(f"CRITICAL HAZARD ({hazard_type}) DETECTED ON NODE {node_id}!")
                
    return {"status": "success", "message": "Telemetry processed and stored"}



# ==========================================
# 4. FRONTEND API MODELS
# ==========================================
class NewNodeRequest(BaseModel):
    hardware_id: str
    zone_id: str
    node_type: str
    latitude: float
    longitude: float

# ==========================================
# 5. FRONTEND DATA PIPELINE ENDPOINTS
# ==========================================

@app.get("/api/v1/nodes")
async def get_all_nodes():
    """Fetches all sensor nodes for the React map."""
    with pg_engine.connect() as conn:
        query = text("""
            SELECT id, hardware_id, zone_id, node_type, latitude, longitude, status, battery_voltage 
            FROM sensor_nodes
        """)
        results = conn.execute(query).fetchall()
        
        # Convert the SQL rows into a list of Python dictionaries for JSON output
        nodes = []
        for row in results:
            nodes.append({
                "id": str(row[0]),
                "hardware_id": row[1],
                "zone_id": str(row[2]) if row[2] else None,
                "node_type": row[3],
                "latitude": float(row[4]),
                "longitude": float(row[5]),
                "status": row[6],
                "battery_voltage": float(row[7]) if row[7] else None
            })
        return {"nodes": nodes}

@app.get("/api/v1/hazards/active")
async def get_active_hazards():
    """Fetches all unresolved hazards to highlight on the map."""
    with pg_engine.connect() as conn:
        query = text("""
            SELECT id, node_id, zone_id, event_type, severity, triggered_at 
            FROM hazard_events 
            WHERE is_resolved = False
        """)
        results = conn.execute(query).fetchall()
        
        hazards = []
        for row in results:
            hazards.append({
                "id": str(row[0]),
                "node_id": str(row[1]),
                "zone_id": str(row[2]) if row[2] else None,
                "event_type": row[3],
                "severity": row[4],
                "triggered_at": row[5].isoformat()
            })
        return {"active_hazards": hazards}

@app.post("/api/v1/nodes")
async def register_new_node(node: NewNodeRequest):
    """Admin endpoint to add a new physical node to the database."""
    with pg_engine.begin() as conn:
        insert_query = text("""
            INSERT INTO sensor_nodes (hardware_id, zone_id, node_type, latitude, longitude, status) 
            VALUES (:hw_id, :z_id, :n_type, :lat, :lon, 'offline')
            RETURNING id
        """)
        
        result = conn.execute(insert_query, {
            "hw_id": node.hardware_id,
            "z_id": node.zone_id,
            "n_type": node.node_type,
            "lat": node.latitude,
            "lon": node.longitude
        })
        
        new_node_id = result.fetchone()[0]
        
        # Also create a default threshold profile for this new node
        threshold_query = text("""
            INSERT INTO node_thresholds (node_id) VALUES (:nid)
        """)
        conn.execute(threshold_query, {"nid": new_node_id})

    return {"status": "success", "message": f"Node {node.hardware_id} registered.", "node_id": str(new_node_id)}

@app.put("/api/v1/hazards/{hazard_id}/resolve")
async def resolve_hazard(hazard_id: str):
    """Marks an active hazard as resolved and clears it from the map."""
    with pg_engine.begin() as conn:
        update_query = text("""
            UPDATE hazard_events 
            SET is_resolved = True, resolved_at = :now 
            WHERE id = :h_id AND is_resolved = False
            RETURNING id
        """)
        
        result = conn.execute(update_query, {
            "h_id": hazard_id,
            "now": datetime.now(timezone.utc)
        })
        
        if not result.fetchone():
            raise HTTPException(status_code=404, detail="Active hazard not found")
            
    return {"status": "success", "message": f"Hazard {hazard_id} resolved."}


@app.delete("/api/v1/nodes/{node_id}")
async def delete_node(node_id: str):
    """Decommissions a sensor node and cleans up its data."""
    with pg_engine.begin() as conn:
        delete_query = text("DELETE FROM sensor_nodes WHERE id = :nid RETURNING id")
        result = conn.execute(delete_query, {"nid": node_id})
        
        if not result.fetchone():
            raise HTTPException(status_code=404, detail="Node not found")
            
    return {"status": "success", "message": f"Node {node_id} successfully decommissioned."}

