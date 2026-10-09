// Live data shared by every page: nodes, open events and backend health, refreshed every 10 s.
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { api } from './api';

const REFRESH_MS = 10000;
export const STALE_AFTER_MS = 30000;   // decision 6.5: a stale screen must never look safe

const LiveContext = createContext(null);

export function LiveProvider({ children }) {
  const [state, setState] = useState({ nodes: [], events: [], health: null, lastOk: null, error: null });
  const busy = useRef(false);
  const [operator, setOperator] = useOperator();
  const [soundOn, setSoundOn] = useState(false);

  const refresh = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    try {
      const [nodes, events, health] = await Promise.all([api.nodes(), api.events('open'), api.health()]);
      setState({ nodes, events, health, lastOk: Date.now(), error: null });
    } catch (e) {
      setState((s) => ({ ...s, error: e.message || 'backend not reachable' }));
    } finally {
      busy.current = false;
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, REFRESH_MS);
    return () => clearInterval(t);
  }, [refresh]);

  return (
    <LiveContext.Provider value={{ ...state, refresh, operator, setOperator, soundOn, setSoundOn }}>
      {children}
    </LiveContext.Provider>
  );
}

export function useLive() {
  return useContext(LiveContext);
}

// Re-render every `ms` (for "12 s ago" texts) without refreshing data.
export function useNow(ms = 1000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

// Poll one API call (used by the node and event pages).
export function usePoll(fn, ms, deps = []) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const load = useCallback(async () => {
    try {
      setData(await fnRef.current());
      setError(null);
    } catch (e) {
      setError(e.message || 'failed');
    }
  }, []);
  useEffect(() => {
    load();
    const t = setInterval(load, ms);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load, ms, ...deps]);
  return { data, error, reload: load };
}

// Operator name, remembered in this browser only (no login in the demo).
function useOperator() {
  const [name, setName] = useState(() => {
    try { return localStorage.getItem('ga_operator') || ''; } catch { return ''; }
  });
  const save = (v) => {
    setName(v);
    try { localStorage.setItem('ga_operator', v); } catch { /* private mode */ }
  };
  return [name, save];
}
