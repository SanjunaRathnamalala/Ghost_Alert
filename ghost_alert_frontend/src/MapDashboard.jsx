import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { MapContainer, TileLayer, Marker, Popup, Circle } from 'react-leaflet';
import axios from 'axios';
import L from 'leaflet'; 

// Fix for Vite breaking Leaflet's default marker icons
import icon from 'leaflet/dist/images/marker-icon.png';
import iconShadow from 'leaflet/dist/images/marker-shadow.png';
let DefaultIcon = L.icon({
    iconUrl: icon,
    shadowUrl: iconShadow,
    iconAnchor: [12, 41],
    popupAnchor: [1, -34],
});
L.Marker.prototype.options.icon = DefaultIcon;

// Function that generates a dynamic SVG icon
const createStatusIcon = (status) => {
    // Set color based on status: Blue for active, Red for anything else (offline/warning)
    const markerColor = status === 'active' ? '#3274A3' : '#CB2B3E'; 

    // The raw SVG code for a standard map pin
    const svgString = `
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="32" height="32">
            <!-- The Drop Shadow -->
            <ellipse cx="12" cy="22" rx="6" ry="2" fill="rgba(0,0,0,0.3)" />
            <!-- The Map Pin Shape -->
            <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z" fill="${markerColor}" stroke="#ffffff" stroke-width="1.5" />
            <!-- The Inner White Circle -->
            <circle cx="12" cy="9" r="3" fill="#ffffff" />
        </svg>
    `;

    return L.divIcon({
        className: "custom-svg-icon", // Remove default Leaflet CSS backgrounds
        html: svgString,
        iconSize: [32, 32],
        iconAnchor: [16, 32], // Anchor the bottom center of the pin to the coordinates
        popupAnchor: [0, -32] // Anchor the popup to appear above the pin
    });
};

export default function MapDashboard({ isEmbedded = false }) {
    const [nodes, setNodes] = useState([]);
    const [hazards, setHazards] = useState([]);

    useEffect(() => {
        // We use Promise.all to fetch both endpoints simultaneously
        const fetchData = async () => {
            try {
                const [nodesRes, hazardsRes] = await Promise.all([
                    axios.get('http://localhost:8000/api/v1/nodes'),
                    axios.get('http://localhost:8000/api/v1/hazards/active')
                ]);
                
                setNodes(nodesRes.data.nodes);
                setHazards(hazardsRes.data.active_hazards);
            } catch (error) {
                console.error("Error fetching data:", error);
            }
        };

        fetchData();
        
        // Refresh everything every 10 seconds
        const interval = setInterval(fetchData, 10000);
        return () => clearInterval(interval);
    }, []);

    return (
        <div style={{ 
            height: isEmbedded ? '100%' : '100vh', 
            width: isEmbedded ? '100%' : '100vw',
            position: 'relative'
        }}>
            {/* Floating Map Navigation */}
            {!isEmbedded && (
                <div style={{ 
                    position: 'absolute', 
                    top: '20px', 
                    left: '50%', 
                    transform: 'translateX(-50%)', 
                    zIndex: 1000, 
                    display: 'flex', 
                    gap: '10px', 
                    backgroundColor: 'rgba(12, 21, 30, 0.8)', 
                    padding: '12px 30px', 
                    borderRadius: '30px', 
                    border: '1px solid #64925b',
                    backdropFilter: 'blur(10px)',
                    boxShadow: '0 4px 15px rgba(0,0,0,0.5)'
                }}>
                    <Link to="/" style={{ textDecoration: 'none' }}>
                            <button style={{ 
                                padding: '4px 10px', 
                                backgroundColor: '#64925b', 
                                color: '#070b10', 
                                border: 'none', 
                                borderRadius: '4px',
                                fontWeight: 'bold',
                                cursor: 'pointer',
                                boxShadow: '0 0 15px rgba(100, 146, 91, 0.4)'
                            }}>
                                HOME
                            </button>
                    </Link>
                    <span style={{ 
                        color: '#64925b', 
                        fontWeight: 'bold',
                        display: 'inline-block',
                        verticalAlign: 'middle'
                    }}>
                        |
                    </span>
                    <Link to="/portal" style={{ textDecoration: 'none' }}>
                            <button style={{ 
                                padding: '4px 10px', 
                                backgroundColor: '#64925b', 
                                color: '#070b10', 
                                border: 'none', 
                                borderRadius: '4px',
                                fontWeight: 'bold',
                                cursor: 'pointer',
                                boxShadow: '0 0 15px rgba(100, 146, 91, 0.4)'
                            }}>
                                USER PORTAL
                            </button>
                    </Link>
                </div>
            )}

            <MapContainer center={[6.7969, 79.9018]} zoom={13} style={{ height: '100%', width: '100%' }}>
                
                <TileLayer
                    attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                    url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                />

                {/* 1. Render the active hazard zones (drawn UNDER the markers) */}
                {hazards.map(hazard => {
                    // Match the hazard to the physical node to get its GPS coordinates
                    const affectedNode = nodes.find(n => n.id === hazard.node_id);
                    if (!affectedNode) return null; // Safety check if data is out of sync

                    return (
                        <Circle
                            key={`hazard-${hazard.id}`}
                            center={[affectedNode.latitude, affectedNode.longitude]}
                            radius={50} // 50-meter radius representing the danger zone
                            pathOptions={{ 
                                color: '#ff0000', 
                                fillColor: '#ff0000', 
                                fillOpacity: 0.4,
                                weight: 2 // border thickness
                            }}
                        >
                            <Popup>
                                <strong style={{color: 'red'}}>CRITICAL HAZARD</strong> <br/>
                                <strong>Event:</strong> {hazard.event_type} <br/>
                                <strong>Triggered:</strong> {new Date(hazard.triggered_at).toLocaleTimeString()}
                            </Popup>
                        </Circle>
                    );
                })}

                {/* 2. Render the physical node markers with dynamic icons */}
                {nodes.map(node => (
                    <Marker 
                        key={node.id} 
                        position={[node.latitude, node.longitude]}
                        icon={createStatusIcon(node.status)}
                    >
                        <Popup>
                            <strong>Node ID:</strong> {node.hardware_id} <br/>
                            <strong>Type:</strong> {node.node_type} <br/>
                            <strong>Status:</strong> {node.status} <br/>
                            <strong>Battery:</strong> {node.battery_voltage ? `${node.battery_voltage}V` : 'N/A'}
                        </Popup>
                    </Marker>
                ))}

            </MapContainer>
        </div>
    );
}