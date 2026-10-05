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
  html: `<div style="background-color: #1b3b2b; color: #f8f6f0; padding: 8px; border-radius: 9999px; border: 2px solid white; box-shadow: 0 4px 12px rgba(27,59,43,0.25); display: flex; align-items: center; justify-content: center; font-size: 16px;">🚚</div>`,
  iconSize: [36, 36],
  iconAnchor: [18, 18],
});

const originIcon = L.divIcon({
  className: 'custom-origin-icon',
  html: `<div style="background-color: #2a5a3b; color: white; width: 16px; height: 16px; border-radius: 9999px; border: 3px solid white; box-shadow: 0 2px 6px rgba(27,59,43,0.2);"></div>`,
  iconSize: [16, 16],
  iconAnchor: [8, 8],
});

const destinationIcon = L.divIcon({
  className: 'custom-dest-icon',
  html: `<div style="background-color: #8b4a2b; color: white; width: 16px; height: 16px; border-radius: 9999px; border: 3px solid white; box-shadow: 0 2px 6px rgba(27,59,43,0.2);"></div>`,
  iconSize: [16, 16],
  iconAnchor: [8, 8],
});

function getRoutePosition(waypoints, progressPercentage) {
  const segmentDistances = waypoints.slice(1).map((point, index) => {
    const [lat1, lon1] = waypoints[index];
    const [lat2, lon2] = point;
    const toRadians = (degrees) => (degrees * Math.PI) / 180;
    const latitudeDelta = toRadians(lat2 - lat1);
    const longitudeDelta = toRadians(lon2 - lon1);
    const haversine =
      Math.sin(latitudeDelta / 2) ** 2 +
      Math.cos(toRadians(lat1)) * Math.cos(toRadians(lat2)) *
        Math.sin(longitudeDelta / 2) ** 2;
    return 6371 * 2 * Math.atan2(Math.sqrt(haversine), Math.sqrt(1 - haversine));
  });
  const routeDistance = segmentDistances.reduce((total, distance) => total + distance, 0);
  let distanceAlongRoute = (routeDistance * progressPercentage) / 100;

  for (let index = 0; index < segmentDistances.length; index += 1) {
    const segmentDistance = segmentDistances[index];
    if (distanceAlongRoute <= segmentDistance) {
      const segmentProgress = segmentDistance === 0 ? 0 : distanceAlongRoute / segmentDistance;
      const [startLat, startLon] = waypoints[index];
      const [endLat, endLon] = waypoints[index + 1];
      return [
        startLat + (endLat - startLat) * segmentProgress,
        startLon + (endLon - startLon) * segmentProgress,
      ];
    }
    distanceAlongRoute -= segmentDistance;
  }

  return waypoints[waypoints.length - 1];
}

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

const MAPS_API_URL = import.meta.env.VITE_MAPS_API_URL || 'http://localhost:8000';

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
    companyName: '',
    deliveries: [],
    destinationVerified: false,
    tonnage: 15,
    progressPercentage: 45,
    speedKmH: 68,
    distanceRemainingKm: 185,
    etaMinutes: 165,
    currentCoords: getRoutePosition(routeWaypoints, 45),
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

  const [isProtrackConnected, setIsProtrackConnected] = useState(false);
  const [protrackConfigured, setProtrackConfigured] = useState(false);
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
        companyName: record.company_name || '',
        assignedDriverName: record.assigned_driver_name || '',
        deliveries: record.deliveries || [],
        destinationVerified: record.destination_verified === true,
        tonnage: record.tonnage ?? previous.tonnage,
        imei: record.imei || previous.imei,
      }));
    };

    document.addEventListener('shipment:loaded', handleShipmentLoaded);
    return () => document.removeEventListener('shipment:loaded', handleShipmentLoaded);
  }, []);

  useEffect(() => {
    let isMounted = true;

    fetch(`${MAPS_API_URL}/health`)
      .then((response) => {
        if (!response.ok) throw new Error('GPS service health check failed.');
        return response.json();
      })
      .then((data) => {
        if (isMounted) setProtrackConfigured(data.protrack_configured === true);
      })
      .catch((error) => {
        if (isMounted) {
          console.warn('Maps service is unavailable. Showing the simulated route.', error);
          setProtrackConfigured(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    const fetchTelemetry = async () => {
      if (protrackConfigured) {
        try {
          const response = await fetch(
            `${MAPS_API_URL}/api/protrack/track?imeis=${encodeURIComponent(shipment.imei)}`,
            {
              headers: {
                Authorization: `Bearer ${localStorage.getItem('jwt_token') || ''}`,
              },
            }
          );
          const positions = await response.json();

          if (!response.ok) {
            throw new Error(positions.detail || 'GPS service request failed.');
          }

          const gps = Array.isArray(positions) ? positions[0] : null;
          if (gps?.online) {
            setIsProtrackConnected(true);
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
          setIsProtrackConnected(false);
        } catch (error) {
          console.warn('GPS telemetry failed. Switching to the simulated route.', error);
          setProtrackConfigured(false);
          setIsProtrackConnected(false);
        }
      } else {
        setIsProtrackConnected(false);
      }

      // Use the existing simulated route when GPS credentials or service are unavailable.
      setShipment((prev) => {
        if (prev.progressPercentage >= 98) return prev;
        const newProgress = Math.min(100, prev.progressPercentage + 1);
        const newDist = Math.max(0, prev.distanceRemainingKm - 2);
        const newEta = Math.max(0, prev.etaMinutes - 2);

        return {
          ...prev,
          progressPercentage: newProgress,
          distanceRemainingKm: newDist,
          etaMinutes: newEta,
          currentCoords: getRoutePosition(routeWaypoints, newProgress),
          speedKmH: Math.floor(62 + Math.random() * 10),
          lastUpdated: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        };
      });
    };

    const interval = setInterval(fetchTelemetry, 4000);
    return () => clearInterval(interval);
  }, [shipment.imei, protrackConfigured]);

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
    <div className="tracking-page">
      
      {/* Top Header & Telemetry Summary */}
      <div className="tracking-overview">
        <div>
          <div className="flex items-center gap-3">
            {onBack && (
              <button
                onClick={onBack}
                className="tracking-back-button"
              >
                ← Back
              </button>
            )}
            <span
              className={`tracking-connection-status text-xs font-extrabold uppercase tracking-widest px-3 py-1 rounded-full border flex items-center gap-1.5 ${
                isProtrackConnected
                  ? 'text-emerald-400 bg-emerald-950 border-emerald-800'
                  : 'text-blue-400 bg-blue-950 border-blue-800'
              }`}
            >
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
              {isProtrackConnected ? 'Protrack Live Map' : 'Protrack Simulated Route'}
            </span>
          </div>
          <h1 className="mt-2 tracking-tight">
            Shipment #{shipment.id}
          </h1>
          <p className="text-xs mt-0.5">
            {shipment.origin} ➔ {shipment.destination}
          </p>
          {shipment.companyName && (
            <p className="text-xs mt-0.5">
              Company: {shipment.companyName}
              {shipment.assignedDriverName ? ` · Driver: ${shipment.assignedDriverName}` : ''}
            </p>
          )}
          {shipment.destinationVerified && (
            <p className="tracking-ocr-validation">Destination verified against uploaded delivery documents</p>
          )}
        </div>

      </div>

      {shipment.deliveries?.length > 0 && (
        <details className="tracking-disclosure" open>
          <summary className="tracking-summary">
            <span>Goods and deliveries</span>
            <span className="tracking-summary-hint">{shipment.deliveries.length} delivery reference(s), read by OCR</span>
          </summary>
          <div className="tracking-delivery-list">
            {shipment.deliveries.map((delivery) => (
              <article className="tracking-delivery-card" key={`${shipment.id}-${delivery.delivery_number}`}>
                <h3>{delivery.delivery_number}</h3>
                <p><strong>Goods:</strong> {delivery.goods_description || 'Not detected on scan'}</p>
                <p><strong>Destination:</strong> {delivery.destination || shipment.destination}</p>
                <p><strong>Customer:</strong> {delivery.customer_name || 'Not detected on scan'}</p>
              </article>
            ))}
          </div>
        </details>
      )}

      <details className="tracking-disclosure">
        <summary className="tracking-summary">
          <span>Trip metrics</span>
          <span className="tracking-summary-hint">ETA, distance and speed</span>
        </summary>
        <div className="tracking-metrics">
          <div className="tracking-metric">
            <p>ETA remaining</p>
            <p>{Math.floor(shipment.etaMinutes / 60)}h {shipment.etaMinutes % 60}m</p>
          </div>
          <div className="tracking-metric">
            <p>Distance remaining</p>
            <p>{shipment.distanceRemainingKm} km</p>
          </div>
          <div className="tracking-metric">
            <p>Current speed</p>
            <p>{shipment.speedKmH} km/h</p>
          </div>
        </div>
      </details>

      {/* Route map remains visible; optional shipment information is grouped in disclosures below. */}
      <div className="tracking-main-column">

          {/* Interactive Map Card */}
          <div className="tracking-map-card">
            
            <div className="tracking-map-header">
              <div>
                <h2>Shipment route</h2>
                <p>{isProtrackConnected ? 'Live GPS location' : 'Simulated route'} · Last update {shipment.lastUpdated}</p>
              </div>
            </div>

            {/* Live Leaflet Map Viewport */}
            <div className="tracking-map-canvas">
                <MapContainer
                  center={shipment.currentCoords}
                  zoom={8}
                  scrollWheelZoom={true}
                  style={{ height: '100%', width: '100%' }}
                >
                  <TileLayer
                    attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                    url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                  />

                  {/* Dynamic Map Recenter */}
                  <RecenterMap position={shipment.currentCoords} />

                  {/* Planned Route Line */}
                  <Polyline
                    positions={routeWaypoints}
                    color="#1b3b2b"
                    weight={5}
                    opacity={0.75}
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

            </div>
            <div className="tracking-map-progress">
              <div className="tracking-map-progress-label">
                <span>Route progress</span>
                <span>{shipment.progressPercentage}%</span>
              </div>
              <div className="tracking-progress-track">
                <div
                  className="tracking-progress-fill"
                  style={{ width: `${shipment.progressPercentage}%` }}
                />
              </div>
            </div>
          </div>

          <details className="tracking-disclosure">
            <summary className="tracking-summary">
              <span>Shipment details</span>
              <span className="tracking-summary-hint">Cargo and tracking device</span>
            </summary>
            <dl className="tracking-detail-grid">
              <div><dt>Cargo</dt><dd>{shipment.cargoType}</dd></div>
              <div><dt>Weight</dt><dd>{shipment.tonnage} metric tons</dd></div>
              <div><dt>Tracker IMEI</dt><dd>{shipment.imei}</dd></div>
              <div><dt>Map provider</dt><dd>OpenStreetMap</dd></div>
            </dl>
          </details>

          <details className="tracking-disclosure">
            <summary className="tracking-summary">
              <span>Contact driver</span>
              <span className="tracking-summary-hint">Call or send a dispatch message</span>
            </summary>
          <div className="tracking-contact-content">
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
                className="tracking-action-button"
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
                  className="tracking-action-button tracking-action-secondary"
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
                  className="tracking-action-button"
                >
                  Send
                </button>
              </form>
            </div>
          </div>
          </details>

          <details className="tracking-disclosure">
            <summary className="tracking-summary">
              <span>Shipment status</span>
              <span className="tracking-summary-hint">Progress updates and delivery protection</span>
            </summary>
          <div className="tracking-timeline-content">
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
          </details>

      </div>
    </div>
  );
}