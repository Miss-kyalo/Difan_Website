import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer, useMap } from 'react-leaflet';
import ShipmentTrackingPage from '../js/shipmentTracking.js';
import 'leaflet/dist/leaflet.css';

const DEFAULT_CENTER = [-1.2864, 36.8172];
const LOCATIONS = [
  { name: 'Athi River', terms: ['athi river'], position: [-1.4503, 36.9806] },
  { name: 'Kisumu', terms: ['kisumu'], position: [-0.1022, 34.7617] },
  { name: 'Nairobi', terms: ['nairobi'], position: [-1.2864, 36.8172] },
  { name: 'Mombasa', terms: ['mombasa'], position: [-4.0435, 39.6682] },
  { name: 'Nakuru', terms: ['nakuru'], position: [-0.3031, 36.08] },
  { name: 'Eldoret', terms: ['eldoret'], position: [0.5143, 35.2698] },
  { name: 'Malaba', terms: ['malaba'], position: [0.635, 34.273] },
];

function resolveLocation(value = '') {
  const normalized = value.toLowerCase();
  return LOCATIONS.find((location) => location.terms.some((term) => normalized.includes(term))) || null;
}

function MapViewport({ origin, destination }) {
  const map = useMap();

  useEffect(() => {
    if (origin && destination) {
      map.fitBounds([origin.position, destination.position], { padding: [36, 36] });
    } else {
      map.setView(origin?.position || destination?.position || DEFAULT_CENTER, 7);
    }
  }, [map, origin, destination]);

  useEffect(() => {
    const observer = new ResizeObserver(() => map.invalidateSize({ pan: false }));
    observer.observe(map.getContainer());
    return () => observer.disconnect();
  }, [map]);

  return null;
}

function ShipmentRouteMap() {
  const [shipment, setShipment] = useState(null);

  useEffect(() => {
    const handleShipmentLoaded = (event) => setShipment(event.detail);
    document.addEventListener('shipment:loaded', handleShipmentLoaded);
    return () => document.removeEventListener('shipment:loaded', handleShipmentLoaded);
  }, []);

  const origin = shipment ? resolveLocation(shipment.origin) : null;
  const destination = shipment ? resolveLocation(shipment.destination) : null;
  const route = origin && destination ? [origin.position, destination.position] : null;

  return (
    <section className="shipment-map-section" aria-label="Shipment route map">
      <div className="shipment-map-heading">
        <h4>Route Preview</h4>
        <span>{shipment?.tracking_number || 'Waiting for shipment'}</span>
      </div>
      <MapContainer center={DEFAULT_CENTER} zoom={6} scrollWheelZoom className="shipment-map">
        <MapViewport origin={origin} destination={destination} />
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {route && <Polyline positions={route} pathOptions={{ color: '#16805d', weight: 4 }} />}
        {origin && (
          <CircleMarker center={origin.position} radius={8} pathOptions={{ color: '#126044', fillOpacity: 1 }}>
            <Popup>Origin: {origin.name}</Popup>
          </CircleMarker>
        )}
        {destination && (
          <CircleMarker center={destination.position} radius={8} pathOptions={{ color: '#b42318', fillOpacity: 1 }}>
            <Popup>Destination: {destination.name}</Popup>
          </CircleMarker>
        )}
      </MapContainer>
      <p className="shipment-map-note">
        {route
          ? `Approximate route from ${origin.name} to ${destination.name}. This is not a live vehicle position.`
          : 'Route coordinates are unavailable for this shipment. Live GPS is not connected.'}
      </p>
    </section>
  );
}

const mapRoot = document.getElementById('shipment-map-root');
const trackingNumber = document.getElementById('shipment-tracking-number')?.value.trim() || 'DL-8801';
if (mapRoot) createRoot(mapRoot).render(<ShipmentTrackingPage trackingNumber={trackingNumber} />);