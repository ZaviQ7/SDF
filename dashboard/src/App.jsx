import React, { useState, useEffect } from 'react';
import { 
  TrendingUp, 
  Activity, 
  Calendar, 
  RefreshCw, 
  MapPin, 
  ShieldAlert, 
  CheckCircle, 
  XCircle, 
  Search, 
  SlidersHorizontal,
  ChevronRight,
  TrendingDown,
  Percent,
  Coins
} from 'lucide-react';

const API_BASE = 'http://127.0.0.1:8000';

function App() {
  const [edges, setEdges] = useState([]);
  const [settled, setSettled] = useState([]);
  const [lastScan, setLastScan] = useState(null);
  const [selectedEdge, setSelectedEdge] = useState(null);
  const [activeTab, setActiveTab] = useState('edges'); // 'edges' or 'settled'
  
  // Filtering and Searching
  const [searchTerm, setSearchTerm] = useState('');
  const [filterDate, setFilterDate] = useState('all'); // 'all', 'today', 'tomorrow'
  const [filterType, setFilterType] = useState('all'); // 'all', 'high', 'low'

  // Scan states
  const [scanState, setScanState] = useState({
    status: 'idle',
    progress: '',
    error: null,
    last_completed: null
  });

  // Fetch edges and settled trades
  const fetchEdges = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/edges`);
      if (res.ok) {
        const data = await res.json();
        setEdges(data.edges || []);
        setLastScan(data.last_scan);
      }
    } catch (err) {
      console.error("Failed to fetch edges:", err);
    }
  };

  const fetchSettled = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/settled`);
      if (res.ok) {
        const data = await res.json();
        setSettled(data.trades || []);
      }
    } catch (err) {
      console.error("Failed to fetch settled trades:", err);
    }
  };

  const checkStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/status`);
      if (res.ok) {
        const data = await res.json();
        setScanState(data);
        
        // If it transitioned from scanning to idle, refresh edges
        if (data.status === 'idle') {
          fetchEdges();
          fetchSettled();
        }
      }
    } catch (err) {
      console.error("Failed to check status:", err);
    }
  };

  const triggerScan = async () => {
    if (scanState.status === 'scanning') return;
    
    setScanState(prev => ({ ...prev, status: 'scanning', progress: 'Triggering scan...' }));
    try {
      const res = await fetch(`${API_BASE}/api/scan`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        checkStatus();
      }
    } catch (err) {
      setScanState(prev => ({ ...prev, status: 'idle', error: 'Failed to start scan.' }));
    }
  };

  // Initial load
  useEffect(() => {
    fetchEdges();
    fetchSettled();
    checkStatus();
  }, []);

  // Poll status when scanning is active
  useEffect(() => {
    let interval = null;
    if (scanState.status === 'scanning') {
      interval = setInterval(checkStatus, 2000);
    } else {
      if (interval) clearInterval(interval);
    }
    return () => {
      if (interval) clearInterval(interval);
    };
  }, [scanState.status]);

  // Handle row selection
  const handleSelectEdge = (edge) => {
    setSelectedEdge(edge);
  };

  // Format Date helpers
  const formatDateTime = (isoString) => {
    if (!isoString) return 'Never';
    const date = new Date(isoString);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) + ' ' + date.toLocaleDateString();
  };

  const isToday = (dateStr) => {
    const today = new Date().toISOString().split('T')[0];
    return dateStr === today;
  };

  // Filter edges
  const filteredEdges = edges.filter(edge => {
    // Search filter
    const matchesSearch = edge.city.toLowerCase().includes(searchTerm.toLowerCase()) || 
                          edge.ticker.toLowerCase().includes(searchTerm.toLowerCase());
    
    // Date filter
    let matchesDate = true;
    if (filterDate === 'today') {
      matchesDate = isToday(edge.date);
    } else if (filterDate === 'tomorrow') {
      matchesDate = !isToday(edge.date);
    }

    // Type filter
    let matchesType = true;
    if (filterType === 'high') {
      matchesType = edge.temp_type === 'HIGH';
    } else if (filterType === 'low') {
      matchesType = edge.temp_type === 'LOW';
    }

    return matchesSearch && matchesDate && matchesType;
  });

  // Stats calculations
  const totalSimulatedBankroll = 15.00; // From config settings.yaml
  const maxEvPlay = edges.length > 0 ? Math.max(...edges.map(e => e.net_ev)) : 0;
  const lockedPlaysCount = edges.filter(e => e.model_prob >= 0.98).length;

  return (
    <div className="dashboard-container">
      {/* HEADER SECTION */}
      <header className="header glass-panel">
        <div className="logo-section">
          <TrendingUp className="logo-icon" size={32} />
          <div>
            <h1 className="logo-text">Antigravity Weather</h1>
            <p className="detail-subtitle">Kalshi Weather Arbitrage Scanner</p>
          </div>
          <span className="logo-badge">Live Sim</span>
        </div>

        <div className="controls-section">
          <div className="detail-subtitle" style={{ textAlign: 'right' }}>
            <div>Last Scan: <strong style={{ color: '#fff' }}>{formatDateTime(lastScan)}</strong></div>
            {scanState.status === 'scanning' && (
              <div style={{ color: 'hsl(var(--primary))', display: 'flex', alignItems: 'center', gap: '6px', justifyContent: 'flex-end' }}>
                <span className="spinner" style={{ width: '12px', height: '12px' }}></span>
                {scanState.progress}
              </div>
            )}
          </div>
          
          <button 
            className={`btn btn-primary ${scanState.status === 'scanning' ? '' : 'pulse'}`}
            onClick={triggerScan}
            disabled={scanState.status === 'scanning'}
          >
            {scanState.status === 'scanning' ? (
              <>
                <RefreshCw className="spinner" size={18} />
                Scanning...
              </>
            ) : (
              <>
                <RefreshCw size={18} />
                Run Live Scan
              </>
            )}
          </button>
        </div>
      </header>

      {/* STATS OVERVIEW SECTION */}
      <section className="stats-grid">
        <div className="stat-card glass-panel">
          <div className="stat-icon-wrapper" style={{ background: 'rgba(6, 182, 212, 0.1)', color: 'hsl(var(--primary))' }}>
            <Activity size={24} />
          </div>
          <div className="stat-info">
            <span className="stat-label">Active Edges</span>
            <span className="stat-value">{edges.length}</span>
          </div>
        </div>

        <div className="stat-card glass-panel">
          <div className="stat-icon-wrapper" style={{ background: 'rgba(245, 158, 11, 0.1)', color: 'hsl(var(--warning))' }}>
            <TrendingUp size={24} />
          </div>
          <div className="stat-info">
            <span className="stat-label">Highest EV Play</span>
            <span className="stat-value">{(maxEvPlay * 100).toFixed(1)}%</span>
          </div>
        </div>

        <div className="stat-card glass-panel">
          <div className="stat-icon-wrapper" style={{ background: 'rgba(16, 185, 129, 0.1)', color: 'hsl(var(--success))' }}>
            <Coins size={24} />
          </div>
          <div className="stat-info">
            <span className="stat-label">Locked-In Plays</span>
            <span className="stat-value">{lockedPlaysCount}</span>
          </div>
        </div>

        <div className="stat-card glass-panel">
          <div className="stat-icon-wrapper" style={{ background: 'rgba(255, 255, 255, 0.05)', color: 'hsl(var(--text-main))' }}>
            <Calendar size={24} />
          </div>
          <div className="stat-info">
            <span className="stat-label">Sim Bankroll</span>
            <span className="stat-value">${totalSimulatedBankroll.toFixed(2)}</span>
          </div>
        </div>
      </section>

      {/* TAB HEADER */}
      <div className="tabs-header">
        <button 
          className={`tab-btn ${activeTab === 'edges' ? 'active' : ''}`}
          onClick={() => setActiveTab('edges')}
        >
          Active Edges
        </button>
        <button 
          className={`tab-btn ${activeTab === 'settled' ? 'active' : ''}`}
          onClick={() => setActiveTab('settled')}
        >
          Settled Trades History
        </button>
      </div>

      {/* MAIN SCREEN PANELS */}
      <div className="main-grid">
        {/* TAB 1: ACTIVE EDGES */}
        {activeTab === 'edges' && (
          <>
            {/* LEFT EDGE TABLE PANEL */}
            <div className="glass-panel">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px', marginBottom: '16px' }}>
                <h2 style={{ fontSize: '1.4rem' }}>Discovered Edges</h2>
                
                {/* Filters Row */}
                <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
                  {/* Search input */}
                  <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                    <Search size={16} style={{ position: 'absolute', left: '12px', color: 'hsl(var(--text-muted))' }} />
                    <input 
                      type="text" 
                      placeholder="Search city/ticker..." 
                      value={searchTerm}
                      onChange={(e) => setSearchTerm(e.target.value)}
                      style={{
                        background: 'rgba(255,255,255,0.03)',
                        border: '1px solid rgba(255,255,255,0.08)',
                        borderRadius: '10px',
                        padding: '8px 12px 8px 36px',
                        color: '#fff',
                        fontSize: '0.9rem',
                        outline: 'none',
                        width: '200px'
                      }}
                    />
                  </div>

                  {/* Date filter select */}
                  <select 
                    value={filterDate}
                    onChange={(e) => setFilterDate(e.target.value)}
                    style={{
                      background: 'rgba(255,255,255,0.03)',
                      border: '1px solid rgba(255,255,255,0.08)',
                      borderRadius: '10px',
                      padding: '8px 12px',
                      color: '#fff',
                      fontSize: '0.9rem',
                      outline: 'none',
                      cursor: 'pointer'
                    }}
                  >
                    <option value="all" style={{background: '#13151a'}}>All Dates</option>
                    <option value="today" style={{background: '#13151a'}}>Today Only</option>
                    <option value="tomorrow" style={{background: '#13151a'}}>Tomorrow Only</option>
                  </select>

                  {/* Type filter select */}
                  <select 
                    value={filterType}
                    onChange={(e) => setFilterType(e.target.value)}
                    style={{
                      background: 'rgba(255,255,255,0.03)',
                      border: '1px solid rgba(255,255,255,0.08)',
                      borderRadius: '10px',
                      padding: '8px 12px',
                      color: '#fff',
                      fontSize: '0.9rem',
                      outline: 'none',
                      cursor: 'pointer'
                    }}
                  >
                    <option value="all" style={{background: '#13151a'}}>Highs & Lows</option>
                    <option value="high" style={{background: '#13151a'}}>Highs Only</option>
                    <option value="low" style={{background: '#13151a'}}>Lows Only</option>
                  </select>
                </div>
              </div>

              {filteredEdges.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '64px 0', color: 'hsl(var(--text-muted))' }}>
                  No active positive EV edges found matching the search/filter criteria.
                </div>
              ) : (
                <div className="table-container">
                  <table>
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>City / Prefix</th>
                        <th>Type</th>
                        <th>Play</th>
                        <th>Price</th>
                        <th>Model%</th>
                        <th>Net EV</th>
                        <th>Size</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredEdges.map((edge, idx) => (
                        <tr 
                          key={idx} 
                          className="table-row-hover"
                          onClick={() => handleSelectEdge(edge)}
                          style={{
                            background: selectedEdge?.ticker === edge.ticker ? 'rgba(6, 182, 212, 0.05)' : ''
                          }}
                        >
                          <td style={{ fontWeight: '500' }}>
                            {edge.date === new Date().toISOString().split('T')[0] ? (
                              <span style={{ color: 'hsl(var(--primary))' }}>Today</span>
                            ) : 'Tomorrow'}
                          </td>
                          <td>
                            <div style={{ fontWeight: '600' }}>{edge.city}</div>
                            <div className="ticker-label">{edge.ticker}</div>
                          </td>
                          <td style={{ fontWeight: '500', color: edge.temp_type === 'HIGH' ? '#f59e0b' : '#38bdf8' }}>
                            {edge.temp_type}
                          </td>
                          <td>
                            <span className={`play-badge ${edge.play === 'YES' ? 'play-yes' : 'play-no'}`}>
                              {edge.play}
                            </span>
                          </td>
                          <td style={{ fontWeight: '600' }}>{edge.price}¢</td>
                          <td style={{ fontWeight: '500' }}>{(edge.model_prob * 100).toFixed(0)}%</td>
                          <td>
                            <span className="ev-badge">
                              {edge.net_ev > 0 ? `+${(edge.net_ev * 100).toFixed(1)}%` : `${(edge.net_ev * 100).toFixed(1)}%`}
                            </span>
                          </td>
                          <td style={{ fontWeight: '600' }}>{edge.suggested_size}</td>
                          <td>
                            <ChevronRight size={18} style={{ color: 'hsl(var(--text-muted))' }} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* RIGHT DETAILS PANEL */}
            <div className="glass-panel detail-card">
              {selectedEdge ? (
                <>
                  <div className="detail-header">
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                      <MapPin size={16} style={{ color: 'hsl(var(--primary))' }} />
                      <span style={{ fontSize: '0.85rem', color: 'hsl(var(--text-muted))', textTransform: 'uppercase', fontWeight: '600' }}>
                        {selectedEdge.date} • {selectedEdge.temp_type}
                      </span>
                    </div>
                    <h3 className="detail-city">{selectedEdge.city}</h3>
                    <p className="ticker-label">{selectedEdge.ticker}</p>
                  </div>

                  <div className="detail-metric">
                    <div className="detail-metric-label">Contract Description</div>
                    <div style={{ fontSize: '1rem', fontWeight: '500' }}>{selectedEdge.title}</div>
                  </div>

                  <div className="detail-metric">
                    <div className="detail-metric-label">Our Model Play</div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                      <span className={`play-badge ${selectedEdge.play === 'YES' ? 'play-yes' : 'play-no'}`} style={{ padding: '6px 14px', fontSize: '0.9rem' }}>
                        Buy {selectedEdge.play}
                      </span>
                      <span className="ev-badge" style={{ fontSize: '1.25rem' }}>
                        +{(selectedEdge.net_ev * 100).toFixed(1)}% EV
                      </span>
                    </div>
                  </div>

                  <div className="detail-metric">
                    <div className="detail-metric-label">Model Probability</div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontSize: '1.2rem', fontWeight: '600' }}>{(selectedEdge.model_prob * 100).toFixed(1)}%</span>
                      <span className="detail-subtitle">Market: {selectedEdge.play === 'YES' ? selectedEdge.price : (100 - selectedEdge.price)}%</span>
                    </div>
                    <div className="prob-bar-container">
                      <div 
                        className="prob-bar-fill" 
                        style={{ 
                          width: `${selectedEdge.model_prob * 100}%`,
                          background: selectedEdge.play === 'YES' ? 'hsl(var(--success))' : 'hsl(var(--danger))'
                        }}
                      ></div>
                    </div>
                  </div>

                  <div className="detail-metric">
                    <div className="detail-metric-label">Kalshi Live Orderbook</div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginTop: '6px' }}>
                      <div style={{ background: 'rgba(255,255,255,0.02)', padding: '10px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.05)' }}>
                        <div style={{ fontSize: '0.8rem', color: 'hsl(var(--text-muted))' }}>YES Ask (Buy Price)</div>
                        <div style={{ fontSize: '1.1rem', fontWeight: '700', color: 'hsl(var(--success))' }}>{selectedEdge.yes_ask}¢</div>
                        <div style={{ fontSize: '0.75rem', color: 'hsl(var(--text-muted))' }}>Bid: {selectedEdge.yes_bid}¢</div>
                      </div>
                      <div style={{ background: 'rgba(255,255,255,0.02)', padding: '10px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.05)' }}>
                        <div style={{ fontSize: '0.8rem', color: 'hsl(var(--text-muted))' }}>NO Ask (Buy Price)</div>
                        <div style={{ fontSize: '1.1rem', fontWeight: '700', color: 'hsl(var(--danger))' }}>{selectedEdge.no_ask}¢</div>
                        <div style={{ fontSize: '0.75rem', color: 'hsl(var(--text-muted))' }}>Bid: {selectedEdge.no_bid}¢</div>
                      </div>
                    </div>
                    {selectedEdge.spread > 5 && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'hsl(var(--danger))', fontSize: '0.8rem', marginTop: '8px' }}>
                        <ShieldAlert size={14} />
                        <span>Wide spread ({selectedEdge.spread}¢) exceeds standard 5¢ threshold. Trade manually.</span>
                      </div>
                    )}
                  </div>

                  <div className="detail-metric">
                    <div className="detail-metric-label">Forecast Breakdown</div>
                    <div style={{ background: 'rgba(255,255,255,0.02)', padding: '12px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.05)' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                        <span style={{ fontSize: '0.85rem', color: 'hsl(var(--text-muted))' }}>Model Mean Forecast:</span>
                        <span style={{ fontWeight: '600' }}>{selectedEdge.mean.toFixed(1)}°F</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span style={{ fontSize: '0.85rem', color: 'hsl(var(--text-muted))' }}>Model Spread (Std):</span>
                        <span style={{ fontWeight: '600' }}>±{selectedEdge.std.toFixed(1)}°F</span>
                      </div>
                    </div>
                  </div>
                </>
              ) : (
                <div style={{ textAlign: 'center', padding: '64px 0', color: 'hsl(var(--text-muted))' }}>
                  <TrendingUp size={48} style={{ color: 'rgba(255,255,255,0.05)', marginBottom: '16px' }} />
                  <p>Select a city row to inspect raw model forecasts, live spreads, and EV calculators.</p>
                </div>
              )}
            </div>
          </>
        )}

        {/* TAB 2: SETTLED TRADES */}
        {activeTab === 'settled' && (
          <div className="glass-panel" style={{ gridColumn: 'span 2' }}>
            <h2 style={{ fontSize: '1.4rem', marginBottom: '16px' }}>Settled Outcomes History</h2>
            
            {settled.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '64px 0', color: 'hsl(var(--text-muted))' }}>
                No settled trades history parsed from log.
              </div>
            ) : (
              <div className="table-container">
                <table>
                  <thead>
                    <tr>
                      <th>Target Date</th>
                      <th>Location / Ticker</th>
                      <th>Action / Play</th>
                      <th>Qty</th>
                      <th>Total Cost</th>
                      <th>True Prob</th>
                      <th>Net EV</th>
                      <th>Est. Payout</th>
                      <th>Status / Outcome</th>
                    </tr>
                  </thead>
                  <tbody>
                    {settled.map((trade, idx) => (
                      <tr key={idx}>
                        <td style={{ fontWeight: '500' }}>{trade.date}</td>
                        <td>
                          <div style={{ fontWeight: '600' }}>{trade.location}</div>
                          <div className="ticker-label">{trade.ticker}</div>
                        </td>
                        <td>
                          <span className={`play-badge ${trade.play.includes('YES') ? 'play-yes' : 'play-no'}`}>
                            {trade.play}
                          </span>
                        </td>
                        <td style={{ fontWeight: '600' }}>{trade.qty}</td>
                        <td>{trade.cost}</td>
                        <td>{trade.prob}</td>
                        <td style={{ fontWeight: '600', color: 'hsl(var(--warning))' }}>{trade.ev}</td>
                        <td style={{ fontWeight: '600' }}>{trade.payout}</td>
                        <td>
                          {trade.status.includes('Won') ? (
                            <span style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'hsl(var(--success))', fontWeight: '600' }}>
                              <CheckCircle size={14} />
                              {trade.status}
                            </span>
                          ) : (
                            <span style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'hsl(var(--danger))', fontWeight: '600' }}>
                              <XCircle size={14} />
                              {trade.status}
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default App;
