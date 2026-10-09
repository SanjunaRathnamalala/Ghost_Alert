import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { LiveProvider } from './live';
import TopBar from './components/TopBar';
import { StaleBanner, CriticalBanner } from './components/Banners';
import Home from './pages/Home';
import Dashboard from './pages/Dashboard';
import NodePage from './pages/NodePage';
import EventPage from './pages/EventPage';
import EventsPage from './pages/EventsPage';

function Shell() {
  const { pathname } = useLocation();
  const home = pathname === '/';
  return (
    <div className={home ? 'shell shell-home' : 'shell'}>
      <TopBar />
      {!home && <StaleBanner />}
      <CriticalBanner />
      <main className="main">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/map" element={<Navigate to="/dashboard" replace />} />
          <Route path="/nodes/:id" element={<NodePage />} />
          <Route path="/events" element={<EventsPage />} />
          <Route path="/events/:id" element={<EventPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <LiveProvider>
        <Shell />
      </LiveProvider>
    </BrowserRouter>
  );
}
