import { Link } from 'react-router-dom';

export default function Home() {
    return (
        <div style={{ 
            backgroundColor: '#070b10', 
            color: '#e0e6ed', 
            minHeight: '100vh', 
            fontFamily: "'Segoe UI', Tahoma, Geneva, Verdana, sans-serif",
            padding: '20px'
        }}>
            
            {/* Top Navigation */}
            <nav style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #1a2634', paddingBottom: '15px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <img src="/ghost.png" alt="Ghost Icon" style={{ width: '32px', height: '32px', filter: 'brightness(1.1)' }} />
                    <h2 style={{ margin: 0, color: '#64925b', letterSpacing: '2px', fontSize: '1.2rem' }}>GHOST ALERT</h2>
                </div>
                <div style={{ display: 'flex', gap: '20px', fontSize: '0.9rem', color: '#8a99a8' }}>
                    <span style={{ color: '#64925b', borderBottom: '2px solid #64925b', paddingBottom: '5px' }}>Overview</span>
                    <span>Solution</span>
                    <span>Docs</span>
                </div>
            </nav>

            {/* Hero Section */}
            <div style={{ marginTop: '60px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0 20px' }}>
                <div style={{ maxWidth: '600px' }}>
                    <h1 style={{ fontSize: '3.5rem', margin: '0 0 10px 0', color: '#ffffff' }}>
                        EARLY <span style={{ color: '#64925b' }}>HAZARD</span>
                    </h1>
                    <p style={{ fontSize: '1.2rem', color: '#8a99a8', marginBottom: '30px' }}>
                        Advanced Environmental Monitoring. Sensing network for predictive safety.
                    </p>
                    
                    <div style={{ display: 'flex', gap: '15px' }}>
                        <Link to="/map" style={{ textDecoration: 'none' }}>
                            <button style={{ 
                                padding: '12px 30px', 
                                backgroundColor: '#64925b', 
                                color: '#070b10', 
                                border: 'none', 
                                borderRadius: '4px',
                                fontWeight: 'bold',
                                cursor: 'pointer',
                                boxShadow: '0 0 15px rgba(100, 146, 91, 0.4)'
                            }}>
                                EXPLORE MAP
                            </button>
                        </Link>
                        
                        <Link to="/portal" style={{ textDecoration: 'none' }}>
                            <button style={{ 
                                padding: '12px 30px', 
                                backgroundColor: 'transparent', 
                                color: '#e0e6ed', 
                                border: '1px solid #64925b', 
                                borderRadius: '4px',
                                fontWeight: 'bold',
                                cursor: 'pointer'
                            }}>
                                USER PORTAL
                            </button>
                        </Link>
                    </div>
                </div>
                
                {/* Hero Icon (Ghost representation) */}
                <div style={{ filter: 'drop-shadow(0 0 40px rgba(100, 146, 91, 0.6))' }}>
                    <img src="/ghost.png" alt="Ghost Icon" style={{ width: '150px', height: '150px' }} />
                </div>
            </div>

            {/* Features Section */}
            <div style={{ marginTop: '80px', padding: '0 20px' }}>
                <h3 style={{ color: '#ffffff', fontSize: '1.5rem', marginBottom: '20px' }}>OUR SOLUTION</h3>
                
                <div style={{ display: 'flex', gap: '20px' }}>
                    {/* Glowing Card 1 */}
                    <div style={{ 
                        flex: 1, 
                        height: '150px', 
                        backgroundColor: '#0c151e', 
                        borderRadius: '8px',
                        border: '1px solid #64925b',
                        boxShadow: '0 0 20px rgba(100, 146, 91, 0.15) inset',
                        display: 'flex',
                        flexDirection: 'column',
                        justifyContent: 'center',
                        alignItems: 'center'
                    }}>
                        <div style={{ fontSize: '30px', marginBottom: '10px' }}>📡</div>
                        <span style={{ color: '#8a99a8', fontSize: '0.9rem' }}>SMART SENSING</span>
                    </div>

                    {/* Glowing Card 2 (Active state) */}
                    <div style={{ 
                        flex: 1, 
                        height: '150px', 
                        backgroundColor: '#0c151e', 
                        borderRadius: '8px',
                        border: '1px solid #64925b',
                        boxShadow: '0 0 20px rgba(100, 146, 91, 0.15) inset',
                        display: 'flex',
                        flexDirection: 'column',
                        justifyContent: 'center',
                        alignItems: 'center'
                    }}>
                        <div style={{ fontSize: '30px', marginBottom: '10px' }}>⚡</div>
                        <span style={{ color: '#64925b', fontSize: '0.9rem', fontWeight: 'bold' }}>SIGNAL RECOVERY</span>
                    </div>
                </div>
            </div>

        </div>
    );
}