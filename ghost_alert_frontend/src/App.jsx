import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Home from './Home';
import MapDashboard from './MapDashboard';
import AdminDashboard from './AdminDashboard';

function App() {
  return (
    <Router>
      <Routes>
        {/* The Landing Page */}
        <Route path="/" element={<Home />} />
        
        {/* The Interactive Map */}
        <Route path="/map" element={<MapDashboard />} />
        
        {/* Placeholder for the User Portal */}
        <Route path="/portal" element={<div style={{ color: 'white', padding: '50px' }}>User Portal Coming Soon...</div>} />
        
        {/* 
          The Hidden Admin Route 
          To access this, you must manually type http://localhost:5173/sys-admin-deploy 
          in the browser URL bar. There are no buttons leading here.
        */}
        <Route path="/admin" element={<AdminDashboard />} />
      </Routes>
    </Router>
  );
}

export default App;