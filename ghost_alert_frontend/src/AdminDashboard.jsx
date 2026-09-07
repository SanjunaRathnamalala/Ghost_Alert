import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import MapDashboard from './MapDashboard';

export default function AdminDashboard() {
    const [isAuthenticated, setIsAuthenticated] = useState(false);
    const [password, setPassword] = useState('');
    const [activeTab, setActiveTab] = useState('nodes'); // 'nodes', 'hazards', 'map'
    const [hazards, setHazards] = useState([]);
    const [nodeList, setNodeList] = useState([]);
    const [formData, setFormData] = useState({
        hardware_id: '',
        zone_id: '11111111-1111-1111-1111-111111111111',
        node_type: 'landslide',
        latitude: '',
        longitude: ''
    });
    const [statusMsg, setStatusMsg] = useState('');

    const handleLogin = (e) => {
        e.preventDefault();
        if (password === 'ghostadmin2026') setIsAuthenticated(true);
    };

    // Fetch hazards when the 'hazards' tab is clicked
    const fetchHazards = async () => {
        try {
            const response = await axios.get('http://localhost:8000/api/v1/hazards/active');
            setHazards(response.data.active_hazards);
        } catch (error) {
            console.error("Error fetching hazards:", error);
        }
    };

    // Fetch nodes for the management table
    const fetchNodes = async () => {
        try {
            const response = await axios.get('http://localhost:8000/api/v1/nodes');
            setNodeList(response.data.nodes);
        } catch (error) {
            console.error("Error fetching nodes:", error);
        }
    };

    // Trigger the fetch whenever the active tab changes
    useEffect(() => {
        if (activeTab === 'hazards') {
            fetchHazards();
        } else if (activeTab === 'nodes') {
            fetchNodes();
        }
    }, [activeTab]);

    // The function to resolve a hazard
    const handleResolve = async (hazardId) => {
        try {
            await axios.put(`http://localhost:8000/api/v1/hazards/${hazardId}/resolve`);
            // Refresh the list after successful resolution
            fetchHazards();
        } catch (error) {
            console.error("Error resolving hazard:", error);
        }
    };

    // Handle node deletion with a safety confirmation
    const handleDeleteNode = async (nodeId) => {
        if (window.confirm("Are you sure you want to decommission this node? This will wipe its history.")) {
            try {
                await axios.delete(`http://localhost:8000/api/v1/nodes/${nodeId}`);
                setStatusMsg("Node successfully decommissioned.");
                fetchNodes(); // Refresh the table
            } catch (error) {
                console.error("Error deleting node:", error);
                setStatusMsg("Error: Could not decommission node.");
            }
        }
    };

    // Form handlers
    const handleChange = (e) => {
        setFormData({ ...formData, [e.target.name]: e.target.value });
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        try {
            const payload = {
                ...formData,
                latitude: parseFloat(formData.latitude),
                longitude: parseFloat(formData.longitude)
            };
            const response = await axios.post('http://localhost:8000/api/v1/nodes', payload);
            
            setStatusMsg(`Success! Node registered. ID: ${response.data.node_id}`);
            setFormData({ ...formData, hardware_id: '', latitude: '', longitude: '' });
            fetchNodes(); // Refresh the table
        } catch (error) {
            console.error("Registration error:", error);
            setStatusMsg("Error registering node. Check console.");
        }
    };

    // Reusable Styles
    const inputStyle = {
        width: '100%', 
        padding: '12px', 
        backgroundColor: '#070b10', 
        border: '1px solid #1a2634', 
        color: '#e0e6ed', 
        borderRadius: '4px',
        boxSizing: 'border-box',
        outline: 'none'
    };

    const buttonStyle = {
        padding: '12px 30px', 
        backgroundColor: '#64925b', 
        color: '#070b10', 
        border: 'none', 
        borderRadius: '4px',
        fontWeight: 'bold',
        cursor: 'pointer',
        boxShadow: '0 0 15px rgba(100, 146, 91, 0.4)',
        width: '100%',
        marginTop: '10px'
    };

    const navButtonStyle = (tabName) => ({
        padding: '15px 20px',
        backgroundColor: activeTab === tabName ? '#0c151e' : 'transparent',
        color: activeTab === tabName ? '#64925b' : '#8a99a8',
        border: 'none',
        borderLeft: activeTab === tabName ? '4px solid #64925b' : '4px solid transparent',
        textAlign: 'left',
        cursor: 'pointer',
        fontWeight: 'bold',
        fontSize: '1rem',
        transition: 'all 0.2s'
    });

    if (!isAuthenticated) {
        return (
            /* ... (Keep your existing dark-themed login prompt here) ... */
            <div style={{ backgroundColor: '#070b10', minHeight: '100vh', display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
                <form onSubmit={handleLogin} style={{ backgroundColor: '#0c151e', padding: '40px', borderRadius: '8px', border: '1px solid #64925b' }}>
                    <h2 style={{ color: '#fff', marginBottom: '20px' }}>ADMIN <span style={{color: '#64925b'}}>LOGIN</span></h2>
                    <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} style={{ padding: '10px', width: '100%', marginBottom: '15px', backgroundColor: '#070b10', color: '#fff', border: '1px solid #1a2634' }} />
                    <button type="submit" style={{ padding: '10px', width: '100%', backgroundColor: '#64925b', color: '#000', fontWeight: 'bold', border: 'none', cursor: 'pointer' }}>AUTHENTICATE</button>
                </form>
            </div>
        );
    }

    return (
        <div style={{ display: 'flex', minHeight: '100vh', backgroundColor: '#070b10', color: '#e0e6ed', fontFamily: "'Segoe UI', sans-serif" }}>
            
            {/* Sidebar Navigation */}
            <div style={{ width: '250px', backgroundColor: '#070b10', borderRight: '1px solid #1a2634', display: 'flex', flexDirection: 'column', paddingTop: '30px' }}>
                <div style={{ padding: '0 20px', marginBottom: '40px' }}>
                    <h2 style={{ margin: 0, color: '#64925b', letterSpacing: '2px', fontSize: '1.2rem' }}>GHOST ADMIN</h2>
                </div>
                
                <button onClick={() => setActiveTab('nodes')} style={navButtonStyle('nodes')}>Node Management</button>
                <button onClick={() => setActiveTab('hazards')} style={navButtonStyle('hazards')}>Hazard Control</button>
                <button onClick={() => setActiveTab('map')} style={navButtonStyle('map')}>System Map Overview</button>
                
                <div style={{ marginTop: 'auto', padding: '20px' }}>
                    <Link to="/" style={{ color: '#8a99a8', textDecoration: 'none', fontSize: '0.9rem' }}>← Exit System</Link>
                </div>
            </div>

            {/* Main Content Area */}
            <div style={{ flex: 1, padding: '40px', overflowY: 'auto' }}>
                
                {activeTab === 'nodes' && (
                    <div>
                        <h2 style={{ color: '#fff', marginBottom: '20px' }}>Node Lifecycle Management</h2>
                        
                        {/* THE REGISTRATION FORM */}
                        <div style={{ backgroundColor: '#0c151e', padding: '30px', borderRadius: '8px', border: '1px solid #1a2634', marginBottom: '40px' }}>
                            <h3 style={{ margin: '0 0 20px 0', color: '#8a99a8', fontSize: '1.1rem' }}>Deploy New Hardware</h3>
                            
                            {statusMsg && (
                                <div style={{ padding: '15px', backgroundColor: statusMsg.includes('Error') ? '#3a1111' : '#0e2612', color: statusMsg.includes('Error') ? '#ff4d4d' : '#39ff14', border: `1px solid ${statusMsg.includes('Error') ? '#ff4d4d' : '#39ff14'}`, borderRadius: '4px', marginBottom: '20px' }}>
                                    {statusMsg}
                                </div>
                            )}

                            <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
                                <div style={{ display: 'flex', gap: '15px' }}>
                                    <label style={{ display: 'flex', flexDirection: 'column', gap: '5px', color: '#8a99a8', flex: 1 }}>
                                        Hardware ID:
                                        <input type="text" name="hardware_id" value={formData.hardware_id} onChange={handleChange} required style={inputStyle} />
                                    </label>
                                    <label style={{ display: 'flex', flexDirection: 'column', gap: '5px', color: '#8a99a8', flex: 1 }}>
                                        Node Type:
                                        <select name="node_type" value={formData.node_type} onChange={handleChange} style={inputStyle}>
                                            <option value="landslide">Landslide (Moisture/Tilt)</option>
                                            <option value="wildlife">Wildlife (PIR/Motion)</option>
                                            <option value="track_intrusion">Track Intrusion</option>
                                        </select>
                                    </label>
                                </div>

                                <div style={{ display: 'flex', gap: '15px' }}>
                                    <label style={{ display: 'flex', flexDirection: 'column', gap: '5px', color: '#8a99a8', flex: 1 }}>
                                        Latitude:
                                        <input type="number" step="any" name="latitude" value={formData.latitude} onChange={handleChange} required style={inputStyle} />
                                    </label>
                                    <label style={{ display: 'flex', flexDirection: 'column', gap: '5px', color: '#8a99a8', flex: 1 }}>
                                        Longitude:
                                        <input type="number" step="any" name="longitude" value={formData.longitude} onChange={handleChange} required style={inputStyle} />
                                    </label>
                                </div>
                                <button type="submit" style={buttonStyle}>REGISTER SENSOR NODE</button>
                            </form>
                        </div>

                        {/* THE NODE FLEET TABLE */}
                        <h3 style={{ margin: '0 0 20px 0', color: '#fff', fontSize: '1.1rem' }}>Active Fleet Status</h3>
                        <div style={{ backgroundColor: '#0c151e', borderRadius: '8px', border: '1px solid #1a2634', overflow: 'hidden' }}>
                            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                                <thead>
                                    <tr style={{ backgroundColor: '#1a2634', color: '#8a99a8' }}>
                                        <th style={{ padding: '15px' }}>Hardware ID</th>
                                        <th style={{ padding: '15px' }}>Type</th>
                                        <th style={{ padding: '15px' }}>Battery</th>
                                        <th style={{ padding: '15px' }}>Status</th>
                                        <th style={{ padding: '15px' }}>Action</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {nodeList.map((node) => (
                                        <tr key={node.id} style={{ borderBottom: '1px solid #1a2634' }}>
                                            <td style={{ padding: '15px', color: '#e0e6ed', fontWeight: 'bold' }}>{node.hardware_id}</td>
                                            <td style={{ padding: '15px', color: '#8a99a8' }}>{node.node_type}</td>
                                            <td style={{ padding: '15px', color: node.battery_voltage < 3.2 ? '#ff4d4d' : '#39ff14' }}>
                                                {node.battery_voltage ? `${node.battery_voltage}V` : 'N/A'}
                                            </td>
                                            <td style={{ padding: '15px' }}>
                                                <span style={{ 
                                                    padding: '4px 8px', 
                                                    borderRadius: '12px', 
                                                    fontSize: '0.8rem',
                                                    backgroundColor: node.status === 'active' ? 'rgba(100, 146, 91, 0.2)' : 'rgba(255, 77, 77, 0.2)',
                                                    color: node.status === 'active' ? '#64925b' : '#ff4d4d'
                                                }}>
                                                    {node.status.toUpperCase()}
                                                </span>
                                            </td>
                                            <td style={{ padding: '15px' }}>
                                                <button 
                                                    onClick={() => handleDeleteNode(node.id)}
                                                    style={{
                                                        backgroundColor: 'transparent', color: '#ff4d4d', border: '1px solid #ff4d4d', padding: '6px 12px', borderRadius: '4px', cursor: 'pointer', transition: 'background 0.2s'
                                                    }}
                                                    onMouseOver={(e) => e.target.style.backgroundColor = 'rgba(255, 77, 77, 0.1)'}
                                                    onMouseOut={(e) => e.target.style.backgroundColor = 'transparent'}
                                                >
                                                    DELETE
                                                </button>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                )}

                {activeTab === 'hazards' && (
                    <div>
                        <h2 style={{ color: '#fff', marginBottom: '30px' }}>Active Hazard Control</h2>
                        
                        {hazards.length === 0 ? (
                            <div style={{ padding: '20px', backgroundColor: '#0c151e', border: '1px solid #1a2634', color: '#64925b', textAlign: 'center', borderRadius: '8px' }}>
                                ✔ All systems nominal. No active hazards detected.
                            </div>
                        ) : (
                            <div style={{ backgroundColor: '#0c151e', borderRadius: '8px', border: '1px solid #1a2634', overflow: 'hidden' }}>
                                <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                                    <thead>
                                        <tr style={{ backgroundColor: '#1a2634', color: '#8a99a8' }}>
                                            <th style={{ padding: '15px' }}>Event Type</th>
                                            <th style={{ padding: '15px' }}>Severity</th>
                                            <th style={{ padding: '15px' }}>Time Triggered</th>
                                            <th style={{ padding: '15px' }}>Action</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {hazards.map((hazard) => (
                                            <tr key={hazard.id} style={{ borderBottom: '1px solid #1a2634' }}>
                                                <td style={{ padding: '15px', color: '#ff4d4d', fontWeight: 'bold' }}>{hazard.event_type}</td>
                                                <td style={{ padding: '15px' }}>{hazard.severity}</td>
                                                <td style={{ padding: '15px', color: '#8a99a8' }}>{new Date(hazard.triggered_at).toLocaleString()}</td>
                                                <td style={{ padding: '15px' }}>
                                                    <button 
                                                        onClick={() => handleResolve(hazard.id)}
                                                        style={{
                                                            backgroundColor: 'transparent',
                                                            color: '#64925b',
                                                            border: '1px solid #64925b',
                                                            padding: '8px 15px',
                                                            borderRadius: '4px',
                                                            cursor: 'pointer',
                                                            fontWeight: 'bold',
                                                            transition: 'background 0.2s'
                                                        }}
                                                        onMouseOver={(e) => e.target.style.backgroundColor = 'rgba(100, 146, 91, 0.1)'}
                                                        onMouseOut={(e) => e.target.style.backgroundColor = 'transparent'}
                                                    >
                                                        MARK RESOLVED
                                                    </button>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                )}

                {activeTab === 'map' && (
                    <div>
                        <h2 style={{ color: '#fff', marginBottom: '30px' }}>System Map Overview</h2>

                        {/* The container determines the size of the embedded map */}
                        <div style={{ height: '600px', width: '100%', borderRadius: '8px', overflow: 'hidden', border: '1px solid #1a2634' }}>
                            <MapDashboard isEmbedded={true} />
                        </div>
                    </div>
                )}
                
            </div>
        </div>
    );
}


// OLD

// import { useState } from 'react';
// import { Link } from 'react-router-dom';
// import axios from 'axios';

// export default function AdminDashboard() {
//     // Authentication State
//     const [isAuthenticated, setIsAuthenticated] = useState(false);
//     const [password, setPassword] = useState('');
//     const [authError, setAuthError] = useState('');

//     // Form State
//     const [formData, setFormData] = useState({
//         hardware_id: '',
//         zone_id: '11111111-1111-1111-1111-111111111111', 
//         node_type: 'landslide',
//         latitude: '',
//         longitude: ''
//     });
//     const [statusMsg, setStatusMsg] = useState('');

//     const handleLogin = (e) => {
//         e.preventDefault();
//         // For prototype purposes, we hardcode the master password here.
//         if (password === 'ghostadmin2026') {
//             setIsAuthenticated(true);
//             setAuthError('');
//         } else {
//             setAuthError('Access Denied. Invalid credentials.');
//         }
//     };

//     const handleChange = (e) => {
//         setFormData({ ...formData, [e.target.name]: e.target.value });
//     };

//     const handleSubmit = async (e) => {
//         e.preventDefault();
//         try {
//             const payload = {
//                 ...formData,
//                 latitude: parseFloat(formData.latitude),
//                 longitude: parseFloat(formData.longitude)
//             };
//             const response = await axios.post('http://localhost:8000/api/v1/nodes', payload);
            
//             setStatusMsg(`Success! Node registered. ID: ${response.data.node_id}`);
//             setFormData({ ...formData, hardware_id: '', latitude: '', longitude: '' });
//         } catch (error) {
//             console.error("Registration error:", error);
//             setStatusMsg("Error registering node. Check console.");
//         }
//     };

//     // Reusable styles to match your Home.jsx theme
//     const inputStyle = {
//         width: '100%', 
//         padding: '12px', 
//         backgroundColor: '#0c151e', 
//         border: '1px solid #1a2634', 
//         color: '#e0e6ed', 
//         borderRadius: '4px',
//         boxSizing: 'border-box',
//         outline: 'none'
//     };

//     const buttonStyle = {
//         padding: '12px 30px', 
//         backgroundColor: '#64925b', 
//         color: '#070b10', 
//         border: 'none', 
//         borderRadius: '4px',
//         fontWeight: 'bold',
//         cursor: 'pointer',
//         boxShadow: '0 0 15px rgba(100, 146, 91, 0.4)',
//         width: '100%',
//         marginTop: '10px'
//     };

//     // --- VIEW 1: LOGIN PROMPT ---
//     if (!isAuthenticated) {
//         return (
//             <div style={{ backgroundColor: '#070b10', minHeight: '100vh', display: 'flex', justifyContent: 'center', alignItems: 'center', fontFamily: "'Segoe UI', sans-serif" }}>
//                 <div style={{ backgroundColor: '#0c151e', padding: '40px', borderRadius: '8px', border: '1px solid #64925b', boxShadow: '0 0 20px rgba(100, 146, 91, 0.15)', width: '100%', maxWidth: '400px' }}>
//                     <h2 style={{ color: '#ffffff', textAlign: 'center', margin: '0 0 20px 0', letterSpacing: '2px' }}>
//                         SYSTEM <span style={{ color: '#64925b' }}>ADMIN</span>
//                     </h2>
                    
//                     {authError && <div style={{ color: '#ff4d4d', marginBottom: '15px', textAlign: 'center', fontSize: '0.9rem' }}>{authError}</div>}
                    
//                     <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
//                         <input 
//                             type="password" 
//                             placeholder="Enter Master Password" 
//                             value={password} 
//                             onChange={(e) => setPassword(e.target.value)} 
//                             style={inputStyle} 
//                             required 
//                         />
//                         <button type="submit" style={buttonStyle}>AUTHENTICATE</button>
//                     </form>
//                     <div style={{ textAlign: 'center', marginTop: '20px' }}>
//                         <Link to="/" style={{ color: '#8a99a8', textDecoration: 'none', fontSize: '0.9rem' }}>Return to Home</Link>
//                     </div>
//                 </div>
//             </div>
//         );
//     }

//     // --- VIEW 2: ADMIN DASHBOARD ---
//     return (
//         <div style={{ backgroundColor: '#070b10', color: '#e0e6ed', minHeight: '100vh', fontFamily: "'Segoe UI', sans-serif", padding: '40px 20px' }}>
//             <div style={{ maxWidth: '600px', margin: '0 auto' }}>
                
//                 <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #1a2634', paddingBottom: '15px', marginBottom: '30px' }}>
//                     <h2 style={{ margin: 0, color: '#ffffff', letterSpacing: '1px' }}>
//                         NODE <span style={{ color: '#64925b' }}>DEPLOYMENT</span>
//                     </h2>
//                     <Link to="/" style={{ color: '#64925b', textDecoration: 'none', fontWeight: 'bold' }}>Exit Admin</Link>
//                 </div>
                
//                 {statusMsg && (
//                     <div style={{ padding: '15px', backgroundColor: statusMsg.includes('Error') ? '#3a1111' : '#0e2612', color: statusMsg.includes('Error') ? '#ff4d4d' : '#39ff14', border: `1px solid ${statusMsg.includes('Error') ? '#ff4d4d' : '#39ff14'}`, borderRadius: '4px', marginBottom: '20px' }}>
//                         {statusMsg}
//                     </div>
//                 )}

//                 <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '15px', backgroundColor: '#0c151e', padding: '30px', borderRadius: '8px', border: '1px solid #1a2634' }}>
                    
//                     <label style={{ display: 'flex', flexDirection: 'column', gap: '5px', color: '#8a99a8' }}>
//                         Hardware ID (Pre-shared key):
//                         <input type="text" name="hardware_id" value={formData.hardware_id} onChange={handleChange} required style={inputStyle} />
//                     </label>
                    
//                     <label style={{ display: 'flex', flexDirection: 'column', gap: '5px', color: '#8a99a8' }}>
//                         Node Type:
//                         <select name="node_type" value={formData.node_type} onChange={handleChange} style={inputStyle}>
//                             <option value="landslide">Landslide (Moisture/Tilt)</option>
//                             <option value="wildlife">Wildlife (PIR/Motion)</option>
//                             <option value="track_intrusion">Track Intrusion</option>
//                         </select>
//                     </label>

//                     <div style={{ display: 'flex', gap: '15px' }}>
//                         <label style={{ display: 'flex', flexDirection: 'column', gap: '5px', color: '#8a99a8', flex: 1 }}>
//                             Latitude:
//                             <input type="number" step="any" name="latitude" value={formData.latitude} onChange={handleChange} required style={inputStyle} />
//                         </label>

//                         <label style={{ display: 'flex', flexDirection: 'column', gap: '5px', color: '#8a99a8', flex: 1 }}>
//                             Longitude:
//                             <input type="number" step="any" name="longitude" value={formData.longitude} onChange={handleChange} required style={inputStyle} />
//                         </label>
//                     </div>

//                     <button type="submit" style={buttonStyle}>
//                         REGISTER SENSOR NODE
//                     </button>
//                 </form>

//             </div>
//         </div>
//     );
// }

