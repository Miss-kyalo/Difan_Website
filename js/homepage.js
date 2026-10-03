import React, { useState, useEffect } from 'react';

export default function Homepage({ user = {}, onNavigate = () => {} }) {
  const safeUser = {
    company_name: 'Partner',
    role: 'client',
    ...user,
  };

  const handleNavigate = (screen) => {
    if (typeof onNavigate === 'function') {
      onNavigate(screen);
    }
  };

  const [stats, setStats] = useState({
    activeShipments: 12,
    deliveredThisMonth: 48,
    pendingQuotes: 3,
    fleetAlerts: 1,
  });

  const [activeShipment, setActiveShipment] = useState(null);
  const [loading, setLoading] = useState(true);

  // Fetch live tracking data for the main featured load
  useEffect(() => {
    if (typeof fetch !== 'function') {
      setLoading(false);
      return;
    }

    fetch('http://localhost:5000/api/shipments/track/DL-8801')
      .then((res) => res.json())
      .then((data) => {
        if (data && data.status === 'success') {
          setActiveShipment(data.shipment);
        }
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6">
      {/* Welcome Banner */}
      <div className="bg-slate-900 text-white rounded-xl p-6 shadow-md border border-slate-800 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            Welcome back, <span className="text-blue-400">{safeUser.company_name}</span>
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            Role: <span className="text-slate-200 capitalize font-medium">{safeUser.role}</span> | Real-time logistics telematics dashboard
          </p>
        </div>
        <button
          onClick={() => handleNavigate('booking')}
          className="bg-blue-600 hover:bg-blue-500 text-white text-sm font-semibold px-4 py-2.5 rounded-lg shadow transition"
        >
          + Request New Truck
        </button>
      </div>

      {/* KPI Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm space-y-1">
          <p className="text-xs font-semibold uppercase text-slate-500 tracking-wider">Active Loads</p>
          <div className="flex justify-between items-baseline">
            <span className="text-3xl font-extrabold text-slate-800">{stats.activeShipments}</span>
            <span className="text-xs font-medium text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded">Live</span>
          </div>
        </div>

        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm space-y-1">
          <p className="text-xs font-semibold uppercase text-slate-500 tracking-wider">Completed (Month)</p>
          <div className="flex justify-between items-baseline">
            <span className="text-3xl font-extrabold text-slate-800">{stats.deliveredThisMonth}</span>
            <span className="text-xs font-medium text-blue-600 bg-blue-50 px-2 py-0.5 rounded">+12% vs last month</span>
          </div>
        </div>

        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm space-y-1">
          <p className="text-xs font-semibold uppercase text-slate-500 tracking-wider">Pending Quotes</p>
          <div className="flex justify-between items-baseline">
            <span className="text-3xl font-extrabold text-slate-800">{stats.pendingQuotes}</span>
            <span className="text-xs font-medium text-amber-600 bg-amber-50 px-2 py-0.5 rounded">Action required</span>
          </div>
        </div>

        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm space-y-1">
          <p className="text-xs font-semibold uppercase text-slate-500 tracking-wider">Fleet Alerts</p>
          <div className="flex justify-between items-baseline">
            <span className="text-3xl font-extrabold text-red-600">{stats.fleetAlerts}</span>
            <span className="text-xs font-medium text-red-600 bg-red-50 px-2 py-0.5 rounded">Mechanical delay</span>
          </div>
        </div>
      </div>

      {/* Main Content Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* Active Featured Shipment Tracker (2 Columns wide) */}
        <div className="lg:col-span-2 bg-white rounded-xl border border-slate-200 shadow-sm p-6 space-y-4">
          <div className="flex justify-between items-center border-b border-slate-100 pb-3">
            <h2 className="text-lg font-bold text-slate-800">Featured Active Shipment</h2>
            <button
              onClick={() => handleNavigate('track')}
              className="text-xs font-semibold text-blue-600 hover:text-blue-700 transition"
            >
              View Full Telematics →
            </button>
          </div>

          {loading ? (
            <div className="py-8 text-center text-slate-400 text-sm">Fetching telemetry stream...</div>
          ) : activeShipment ? (
            <div className="space-y-4">
              <div className="flex flex-wrap justify-between items-center bg-slate-50 p-4 rounded-lg border border-slate-200/80 text-sm">
                <div>
                  <p className="text-xs text-slate-500">Tracking Reference</p>
                  <p className="font-mono font-bold text-slate-800 text-base">{activeShipment.tracking_number}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Cargo & Weight</p>
                  <p className="font-semibold text-slate-800">{activeShipment.cargo_type} ({activeShipment.tonnage} Tons)</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Status</p>
                  <span className="inline-block bg-amber-100 text-amber-800 font-semibold text-xs px-2.5 py-1 rounded-full mt-0.5">
                    {activeShipment.status}
                  </span>
                </div>
              </div>

              {/* Breakdown Warning Card */}
              {activeShipment.breakdown_alert && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex items-start gap-3 text-sm text-red-800">
                  <span className="text-lg">⚠️</span>
                  <div>
                    <p className="font-semibold">Relief Unit Dispatched</p>
                    <p className="text-xs text-red-700 mt-0.5">
                      Engine overheating flagged at Salama Corridor. Secondary truck dispatched for cargo swap. Estimated delay: 45 minutes.
                    </p>
                  </div>
                </div>
              )}

              {/* Progress Route */}
              <div className="p-4 bg-slate-900 text-white rounded-lg space-y-3">
                <div className="flex justify-between text-xs text-slate-300">
                  <span>Origin: <strong className="text-white">{activeShipment.origin}</strong></span>
                  <span>Destination: <strong className="text-white">{activeShipment.destination}</strong></span>
                </div>
                <div className="w-full bg-slate-700 h-2 rounded-full overflow-hidden">
                  <div className="bg-blue-500 h-full w-2/3 rounded-full animate-pulse"></div>
                </div>
                <div className="flex justify-between text-xs text-slate-400">
                  <span>Dispatch: 06:30 AM</span>
                  <span>Progress: 65%</span>
                  <span>ETA: 04:15 PM</span>
                </div>
              </div>
            </div>
          ) : (
            <p className="text-slate-500 text-sm">No active shipment data found.</p>
          )}
        </div>

        {/* Quick Actions & Recent Orders Sidebar (1 Column wide) */}
        <div className="space-y-6">
          {/* Quick Actions */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 space-y-3">
            <h3 className="font-bold text-slate-800 text-sm uppercase tracking-wider">Quick Actions</h3>
            <div className="space-y-2">
              <button
                onClick={() => handleNavigate('booking')}
                className="w-full text-left bg-slate-50 hover:bg-blue-50 hover:text-blue-600 border border-slate-200 rounded-lg p-3 text-xs font-semibold transition text-slate-700 flex justify-between items-center"
              >
                <span>🚛 Request On-Demand Truck</span>
                <span>→</span>
              </button>
              <button
                onClick={() => handleNavigate('track')}
                className="w-full text-left bg-slate-50 hover:bg-blue-50 hover:text-blue-600 border border-slate-200 rounded-lg p-3 text-xs font-semibold transition text-slate-700 flex justify-between items-center"
              >
                <span>📍 Search Tracking ID</span>
                <span>→</span>
              </button>
              {safeUser.role === 'admin' && (
                <button
                  onClick={() => handleNavigate('admin')}
                  className="w-full text-left bg-slate-50 hover:bg-blue-50 hover:text-blue-600 border border-slate-200 rounded-lg p-3 text-xs font-semibold transition text-slate-700 flex justify-between items-center"
                >
                  <span>👤 Provision New Accounts</span>
                  <span>→</span>
                </button>
              )}
            </div>
          </div>

          {/* Activity Log */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 space-y-3">
            <h3 className="font-bold text-slate-800 text-sm uppercase tracking-wider">Recent Activity</h3>
            <div className="space-y-3 text-xs">
              <div className="border-l-2 border-blue-500 pl-3 space-y-0.5">
                <p className="font-semibold text-slate-800">Quote #1042 Approved</p>
                <p className="text-slate-500">28T Cement route to Kisumu</p>
                <span className="text-[10px] text-slate-400">2 hours ago</span>
              </div>
              <div className="border-l-2 border-emerald-500 pl-3 space-y-0.5">
                <p className="font-semibold text-slate-800">DL-8799 Delivered</p>
                <p className="text-slate-500">Mombasa Port to Nairobi HQ</p>
                <span className="text-[10px] text-slate-400">Yesterday at 5:40 PM</span>
              </div>
            </div>
          </div>

        </div>

      </div>
    </div>
  );
}