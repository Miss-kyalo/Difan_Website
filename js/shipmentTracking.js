import React, { useState, useEffect } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Polyline, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

// Fix for default Leaflet marker icon paths in React/Webpack
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

// Custom Icons for Truck, Origin, and Destination
const truckIcon = L.divIcon({
  className: 'custom-truck-icon',
  html: `<div style="background-color: #2563eb; color: white; padding: 8px; border-radius: 9999px; border: 2px solid white; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3); display: flex; align-items: center; justify-content: center; font-size: 16px;">🚚</div>`,
  iconSize: [36, 36],
  iconAnchor: [18, 18],
});

const originIcon = L.divIcon({
  className: 'custom-origin-icon',
  html: `<div style="background-color: #10b981; color: white; width: 16px; height: 16px; border-radius: 9999px; border: 3px solid white; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.2);"></div>`,
  iconSize: [16, 16],
  iconAnchor: [8, 8],
});

const destinationIcon = L.divIcon({
  className: 'custom-dest-icon',
  html: `<div style="background-color: #ef4444; color: white; width: 16px; height: 16px; border-radius: 9999px; border: 3px solid white; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.2);"></div>`,
  iconSize: [16, 16],
  iconAnchor: [8, 8],
});

// Helper component to auto-recenter the map when driver coordinates update
function RecenterMap({ position }) {
  const map = useMap();
  useEffect(() => {
    if (position) {
      map.panTo(position, { animate: true });
    }
  }, [position, map]);

  useEffect(() => {
    const mapContainer = map.getContainer().parentElement;
    if (!mapContainer) return undefined;

    const observer = new ResizeObserver(() => map.invalidateSize({ pan: false }));
    observer.observe(mapContainer);
    return () => observer.disconnect();
  }, [map]);
  return null;
}

// Protrack API Config
const PROTRACK_CONFIG = {
  baseUrl: import.meta.env.VITE_PROTRACK_URL || 'https://api.protrack365.com',
  account: import.meta.env.VITE_PROTRACK_ACCOUNT || '',
};

export default function ShipmentTrackingPage({
  trackingNumber = 'DL-8492',
  imei = '864201048291034',
  onBack,
}) {
  // Waypoint Coordinates (Athi River ➔ Nakuru ➔ Kisumu)
  const originCoords = [-1.4583, 36.9806];
  const destinationCoords = [-0.0917, 34.7680];
  const routeWaypoints = [
    originCoords,
    [-0.2833, 36.0667], // Nakuru Waypoint
    [-0.1022, 35.2833], // Kericho Waypoint
    destinationCoords,
  ];

  const [shipment, setShipment] = useState({
    id: trackingNumber,
    imei: imei,
    status: 'IN_TRANSIT',
    origin: 'Athi River Industrial Zone',
    destination: 'Kisumu Central Warehouse',
    cargoType: 'General Goods / FMCG',
    tonnage: 15,
    progressPercentage: 45,
    speedKmH: 68,
    distanceRemainingKm: 185,
    etaMinutes: 165,
    currentCoords: [-0.2833, 36.0667], // Live Lat/Lng
    lastUpdated: 'Just now',
    driver: {
      name: 'Samuel M.',
      phone: '+254 712 345 678',
      rating: 4.92,
      truckModel: 'Scania R500 (3-Axle Heavy)',
      plateNumber: 'KDC 849L',
      avatar: 'S',
    },
  });

  const [protrackToken, setProtrackToken] = useState(null);
  const [isProtrackConnected, setIsProtrackConnected] = useState(false);
  const [activeTab, setActiveTab] = useState('map');
  const [callStatus, setCallStatus] = useState(null);
  const [chatMessage, setChatMessage] = useState('');
  const [chatHistory, setChatHistory] = useState([
    { sender: 'driver', text: 'Cargo loaded securely. Protrack GPS lock active.', time: '08:30 AM' },
    { sender: 'driver', text: 'Passing Nakuru bypass, smooth transit speed.', time: '10:15 AM' },
  ]);

  useEffect(() => {
    const handleShipmentLoaded = (event) => {
      const record = event.detail;
      setShipment((previous) => ({
        ...previous,
        id: record.tracking_number || previous.id,
        status: record.status || previous.status,
        origin: record.origin || previous.origin,
        destination: record.destination || previous.destination,
        cargoType: record.cargo_type || previous.cargoType,
        tonnage: record.tonnage ?? previous.tonnage,
      }));
    };

    document.addEventListener('shipment:loaded', handleShipmentLoaded);
    return () => document.removeEventListener('shipment:loaded', handleShipmentLoaded);
  }, []);

  // Protrack Authenticate & Poll Telemetry
  useEffect(() => {
    const authenticateProtrack = async () => {
      if (!PROTRACK_CONFIG.account) {
        console.info('Protrack account is not configured. Showing the simulated route.');
        return;
      }

      try {
        const response = await fetch(`${PROTRACK_CONFIG.baseUrl}/api/authorization`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            account: PROTRACK_CONFIG.account,
            time: Math.floor(Date.now() / 1000),
          }),
        });
        const data = await response.json();
        if (data.code === 0 && data.record?.access_token) {
          setProtrackToken(data.record.access_token);
          setIsProtrackConnected(true);
        }
      } catch (err) {
        console.warn('Protrack is unavailable. Showing the simulated route.');
      }
    };

    authenticateProtrack();
  }, []);

  useEffect(() => {
    const fetchTelemetry = async () => {
      if (protrackToken && isProtrackConnected) {
        try {
          const res = await fetch(
            `${PROTRACK_CONFIG.baseUrl}/api/track?access_token=${protrackToken}&imeis=${shipment.imei}`
          );
          const data = await res.json();

          if (data.code === 0 && data.record && data.record.length > 0) {
            const gps = data.record[0];
            setShipment((prev) => ({
              ...prev,
              currentCoords: [gps.latitude, gps.longitude],
              speedKmH: Math.round(gps.speed || prev.speedKmH),
              lastUpdated: new Date(gps.gpstime * 1000).toLocaleTimeString([], {
                hour: '2-digit',
                minute: '2-digit',
              }),
            }));
            return;
          }
        } catch (e) {
          console.error('Error fetching Protrack telemetry:', e);
        }
      }

      // Live Simulation GPS Step
      setShipment((prev) => {
        if (prev.progressPercentage >= 98) return prev;
        const newProgress = Math.min(100, prev.progressPercentage + 1);
        const newDist = Math.max(0, prev.distanceRemainingKm - 2);
        const newEta = Math.max(0, prev.etaMinutes - 2);

        // Interpolate coordinates along route
        const lat = originCoords[0] + (destinationCoords[0] - originCoords[0]) * (newProgress / 100);
        const lng = originCoords[1] + (destinationCoords[1] - originCoords[1]) * (newProgress / 100);

        return {
          ...prev,
          progressPercentage: newProgress,
          distanceRemainingKm: newDist,
          etaMinutes: newEta,
          currentCoords: [lat, lng],
          speedKmH: Math.floor(62 + Math.random() * 10),
          lastUpdated: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        };
      });
    };

    const interval = setInterval(fetchTelemetry, 4000);
    return () => clearInterval(interval);
  }, [protrackToken, isProtrackConnected, shipment.imei]);

  const handleSendMessage = (e) => {
    e.preventDefault();
    if (!chatMessage.trim()) return;

    const newMsg = {
      sender: 'user',
      text: chatMessage,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };

    setChatHistory((prev) => [...prev, newMsg]);
    setChatMessage('');

    setTimeout(() => {
      setChatHistory((prev) => [
        ...prev,
        {
          sender: 'driver',
          text: 'Received! Continuing route as scheduled.',
          time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        },
      ]);
    }, 1500);
  };

  const timelineSteps = [
    { key: 'BOOKED', label: 'Order Confirmed', desc: 'Dispatch escrow locked', time: '07:45 AM', completed: true },
    { key: 'DRIVER_ASSIGNED', label: 'Driver Assigned', desc: `Protrack Tracker Paired (IMEI: ${shipment.imei.slice(-6)})`, time: '08:10 AM', completed: true },
    { key: 'IN_TRANSIT', label: 'In Transit', desc: 'En route via Protrack OpenStreetMap', time: '08:35 AM', completed: true, active: true },
    { key: 'ARRIVED_DESTINATION', label: 'Arrival at Dropoff', desc: 'Geofence trigger & offload', time: 'Est. 02:45 PM', completed: false },
    { key: 'COMPLETED', label: 'Delivery Signed', desc: 'E-POD signed & payout released', time: 'Pending', completed: false },
  ];

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      
      {/* Top Header & Telemetry Summary */}
      <div className="bg-slate-900 text-white rounded-2xl p-6 shadow-xl border border-slate-800 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <div className="flex items-center gap-3">
            {onBack && (
              <button
                onClick={onBack}
                className="text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 font-semibold px-3 py-1.5 rounded-lg border border-slate-700 transition"
              >
                ← Back
              </button>
            )}
            <span
              className={`text-xs font-extrabold uppercase tracking-widest px-3 py-1 rounded-full border flex items-center gap-1.5 ${
                isProtrackConnected
                  ? 'text-emerald-400 bg-emerald-950 border-emerald-800'
                  : 'text-blue-400 bg-blue-950 border-blue-800'
              }`}
            >
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
              {isProtrackConnected ? 'Protrack Live Map' : 'Protrack Simulated Route'}
            </span>
          </div>
          <h1 className="text-2xl font-black mt-2 tracking-tight">
            Shipment #{shipment.id}
          </h1>
          <p className="text-slate-400 text-xs mt-0.5">
            {shipment.origin} ➔ {shipment.destination}
          </p>
        </div>

        {/* Telemetry Snapshot Cards */}
        <div className="flex gap-3 bg-slate-800/80 p-3 rounded-xl border border-slate-700 text-center w-full sm:w-auto justify-around">
          <div>
            <p className="text-[10px] text-slate-400 uppercase font-semibold">ETA Remaining</p>
            <p className="text-lg font-black text-emerald-400 font-mono">
              {Math.floor(shipment.etaMinutes / 60)}h {shipment.etaMinutes % 60}m
            </p>
          </div>
          <div className="w-px bg-slate-700"></div>
          <div>
            <p className="text-[10px] text-slate-400 uppercase font-semibold">Distance</p>
            <p className="text-lg font-black text-blue-400 font-mono">{shipment.distanceRemainingKm} km</p>
          </div>
          <div className="w-px bg-slate-700"></div>
          <div>
            <p className="text-[10px] text-slate-400 uppercase font-semibold">Simulated Speed</p>
            <p className="text-lg font-black text-amber-400 font-mono">{shipment.speedKmH} km/h</p>
          </div>
        </div>
      </div>

      {/* Main Grid: Left Map + Contact (2 Cols) | Right Timeline & Details (1 Col) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

        {/* Left Column: Interactive Leaflet Map & Driver Contact Controls */}
        <div className="lg:col-span-2 space-y-6">

          {/* Interactive Map Card */}
          <div className="bg-slate-900 rounded-2xl border border-slate-800 shadow-xl overflow-hidden flex flex-col">
            
            {/* Header Controls */}
            <div className="p-4 border-b border-slate-800 flex justify-between items-center bg-slate-900/90">
              <div className="flex gap-2">
                <button
                  onClick={() => setActiveTab('map')}
                  className={`text-xs font-bold px-3 py-1.5 rounded-lg transition ${
                    activeTab === 'map' ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-400 hover:text-white'
                  }`}
                >
                  🗺️ Interactive Route Map
                </button>
                <button
                  onClick={() => setActiveTab('details')}
                  className={`text-xs font-bold px-3 py-1.5 rounded-lg transition ${
                    activeTab === 'details' ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-400 hover:text-white'
                  }`}
                >
                  📋 Manifest Details
                </button>
              </div>

              <span className="text-[11px] text-slate-400 font-mono">
                GPS Ping: <strong className="text-slate-200">{shipment.lastUpdated}</strong>
              </span>
            </div>

            {/* Live Leaflet Map Viewport */}
            {activeTab === 'map' ? (
              <div className="relative h-80 sm:h-96 w-full z-0" style={{ height: 'min(60vh, 420px)', minHeight: '320px', position: 'relative', width: '100%' }}>
                <MapContainer
                  center={shipment.currentCoords}
                  zoom={8}
                  scrollWheelZoom={true}
                  style={{ height: '100%', width: '100%' }}
                >
                  {/* CartoDB Dark Matter Tiles for Sleek Dark Theme */}
                  <TileLayer
                    attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
                    url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
                  />

                  {/* Dynamic Map Recenter */}
                  <RecenterMap position={shipment.currentCoords} />

                  {/* Planned Route Line */}
                  <Polyline
                    positions={routeWaypoints}
                    color="#3b82f6"
                    weight={4}
                    dashArray="8, 8"
                    opacity={0.8}
                  />

                  {/* Origin Marker */}
                  <Marker position={originCoords} icon={originIcon}>
                    <Popup className="text-xs">
                      <strong>Origin:</strong> {shipment.origin}
                    </Popup>
                  </Marker>

                  {/* Live Truck Marker */}
                  <Marker position={shipment.currentCoords} icon={truckIcon}>
                    <Popup className="text-xs">
                      <strong>Driver:</strong> {shipment.driver.name}<br />
                      <strong>Speed:</strong> {shipment.speedKmH} km/h<br />
                      <strong>Coordinates:</strong> {shipment.currentCoords[0].toFixed(4)}, {shipment.currentCoords[1].toFixed(4)}
                    </Popup>
                  </Marker>

                  {/* Destination Marker */}
                  <Marker position={destinationCoords} icon={destinationIcon}>
                    <Popup className="text-xs">
                      <strong>Destination:</strong> {shipment.destination}
                    </Popup>
                  </Marker>
                </MapContainer>

                {/* Overlaid Progress Banner */}
                <div className="absolute bottom-3 left-4 right-4 z-[500] bg-slate-900/90 border border-slate-800 rounded-xl p-3 backdrop-blur-md flex justify-between items-center text-xs">
                  <div>
                    <span className="text-slate-400 text-[11px]">Simulated Coordinates:</span>
                    <p className="font-mono text-slate-200 font-bold">
                      {shipment.currentCoords[0].toFixed(4)}°, {shipment.currentCoords[1].toFixed(4)}°
                    </p>
                  </div>
                  <div className="text-right">
                    <span className="text-slate-400 text-[11px]">Route Completion:</span>
                    <p className="font-mono text-blue-400 font-bold">{shipment.progressPercentage}%</p>
                  </div>
                </div>
              </div>
            ) : (
              /* Manifest Details */
              <div className="p-6 bg-slate-950 text-slate-300 space-y-4 text-xs">
                <h3 className="font-bold text-sm text-white border-b border-slate-800 pb-2">
                  Protrack Telematics & Cargo Specs
                </h3>
                <div className="grid grid-cols-2 gap-4">
                  <div className="bg-slate-900 p-3 rounded-xl border border-slate-800">
                    <p className="text-slate-500 uppercase font-semibold">Protrack IMEI</p>
                    <p className="text-sm font-bold text-blue-400 font-mono mt-1">{shipment.imei}</p>
                  </div>
                  <div className="bg-slate-900 p-3 rounded-xl border border-slate-800">
                    <p className="text-slate-500 uppercase font-semibold">Map Provider</p>
                    <p className="text-sm font-bold text-slate-200 mt-1">OpenStreetMap / Leaflet</p>
                  </div>
                  <div className="bg-slate-900 p-3 rounded-xl border border-slate-800">
                    <p className="text-slate-500 uppercase font-semibold">Cargo Type</p>
                    <p className="text-sm font-bold text-slate-200 mt-1">{shipment.cargoType}</p>
                  </div>
                  <div className="bg-slate-900 p-3 rounded-xl border border-slate-800">
                    <p className="text-slate-500 uppercase font-semibold">Tonnage</p>
                    <p className="text-sm font-bold text-slate-200 mt-1">{shipment.tonnage} Metric Tons</p>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Driver Contact & Live Dispatch Controls */}
          <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm space-y-5">
            <div className="flex justify-between items-center border-b border-slate-100 pb-4">
              <div className="flex items-center gap-3">
                <div className="w-12 h-12 rounded-full bg-blue-600 text-white font-black flex items-center justify-center text-lg shadow-md">
                  {shipment.driver.avatar}
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="font-extrabold text-slate-900">{shipment.driver.name}</h3>
                    <span className="text-xs font-bold text-amber-700 bg-amber-50 px-2 py-0.5 rounded border border-amber-200">
                      ★ {shipment.driver.rating}
                    </span>
                  </div>
                  <p className="text-xs text-slate-500 font-medium">
                    {shipment.driver.truckModel} • <span className="font-mono">{shipment.driver.plateNumber}</span>
                  </p>
                </div>
              </div>

              <button
                onClick={() => setCallStatus(callStatus ? null : 'calling')}
                className="bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold px-4 py-2.5 rounded-xl transition flex items-center gap-1.5 shadow"
              >
                <span>📞</span> Call Driver
              </button>
            </div>

            {callStatus && (
              <div className="bg-emerald-950 text-emerald-200 p-4 rounded-xl border border-emerald-600 flex justify-between items-center animate-pulse">
                <div className="flex items-center gap-3">
                  <span className="text-xl">🎙️</span>
                  <div>
                    <p className="text-xs font-bold text-white">Call Connected (00:12)</p>
                    <p className="text-[11px] text-emerald-400">{shipment.driver.phone}</p>
                  </div>
                </div>
                <button
                  onClick={() => setCallStatus(null)}
                  className="bg-red-600 hover:bg-red-500 text-white text-xs font-bold px-3 py-1.5 rounded-lg transition"
                >
                  End Call
                </button>
              </div>
            )}

            {/* Chat Box */}
            <div className="space-y-3">
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                Direct Dispatch Chat
              </h4>
              <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 h-40 overflow-y-auto space-y-2 text-xs">
                {chatHistory.map((msg, idx) => (
                  <div
                    key={idx}
                    className={`flex flex-col ${msg.sender === 'user' ? 'items-end' : 'items-start'}`}
                  >
                    <div
                      className={`max-w-[80%] rounded-xl px-3.5 py-2 ${
                        msg.sender === 'user'
                          ? 'bg-blue-600 text-white rounded-br-none'
                          : 'bg-white border border-slate-200 text-slate-800 shadow-sm rounded-bl-none'
                      }`}
                    >
                      <p>{msg.text}</p>
                    </div>
                    <span className="text-[10px] text-slate-400 mt-0.5 px-1">{msg.time}</span>
                  </div>
                ))}
              </div>

              <form onSubmit={handleSendMessage} className="flex gap-2">
                <input
                  type="text"
                  value={chatMessage}
                  onChange={(e) => setChatMessage(e.target.value)}
                  placeholder="Send message to driver..."
                  className="flex-grow px-4 py-2.5 bg-slate-50 border border-slate-300 rounded-xl text-xs font-medium focus:bg-white focus:ring-2 focus:ring-blue-500 focus:outline-none"
                />
                <button
                  type="submit"
                  className="bg-slate-900 hover:bg-slate-800 text-white font-bold px-4 py-2.5 rounded-xl text-xs transition"
                >
                  Send
                </button>
              </form>
            </div>
          </div>

        </div>

        {/* Right Column: Timeline */}
        <div className="space-y-6">
          <div className="bg-slate-900 text-white rounded-2xl p-6 shadow-xl border border-slate-800 space-y-6">
            <div className="border-b border-slate-800 pb-3 flex justify-between items-center">
              <div>
                <h3 className="text-base font-extrabold tracking-tight">Status Timeline</h3>
                <p className="text-xs text-slate-400">Route Status Preview</p>
              </div>
              <span className="text-[10px] font-bold text-blue-400 bg-blue-950 px-2 py-0.5 rounded border border-blue-800">
                MAP TRACKING
              </span>
            </div>

            <div className="relative border-l-2 border-slate-800 ml-3 space-y-6">
              {timelineSteps.map((step) => (
                <div key={step.key} className="relative pl-6">
                  <span
                    className={`absolute -left-[9px] top-0.5 w-4 h-4 rounded-full border-2 transition ${
                      step.active
                        ? 'bg-blue-500 border-white ring-4 ring-blue-500/30'
                        : step.completed
                        ? 'bg-emerald-500 border-emerald-950'
                        : 'bg-slate-800 border-slate-700'
                    }`}
                  ></span>
                  <div>
                    <div className="flex justify-between items-baseline">
                      <p
                        className={`text-xs font-bold ${
                          step.active
                            ? 'text-blue-400'
                            : step.completed
                            ? 'text-slate-200'
                            : 'text-slate-500'
                        }`}
                      >
                        {step.label}
                      </p>
                      <span className="text-[10px] text-slate-500 font-mono">{step.time}</span>
                    </div>
                    <p className="text-[11px] text-slate-400 mt-0.5">{step.desc}</p>
                  </div>
                </div>
              ))}
            </div>

            <div className="bg-slate-800/80 p-4 rounded-xl border border-slate-700/60 space-y-2 text-xs">
              <div className="flex justify-between text-slate-300 font-bold">
                <span>Escrow Protection:</span>
                <span className="text-amber-400 font-mono">50% Locked</span>
              </div>
              <p className="text-[11px] text-slate-400">
                Automated payout triggers upon reaching destination geofence coordinates.
              </p>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}