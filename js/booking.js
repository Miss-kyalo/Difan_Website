import React, { useState, useMemo } from 'react';

// Common Freight Hubs with coordinates for accurate distance calculation
const FREIGHT_HUBS = [
  { name: 'Athi River Industrial Zone', lat: -1.4583, lng: 36.9806 },
  { name: 'Nairobi Inland Container Depot (ICD)', lat: -1.3211, lng: 36.8783 },
  { name: 'Mombasa Port Terminal', lat: -4.0435, lng: 39.6682 },
  { name: 'Nakuru Freight Bypass', lat: -0.2833, lng: 36.0667 },
  { name: 'Eldoret Logistics Hub', lat: 0.5143, lng: 35.2698 },
  { name: 'Kisumu Central Warehouse', lat: -0.0917, lng: 34.7680 },
];

// Truck Pricing Models (Base fee + per Ton-Km rate)
const TRUCK_TYPES = [
  { id: '3_TON', name: '3-Ton Light Canter', capacity: 3, baseFee: 4500, ratePerTonKm: 18 },
  { id: '10_TON', name: '10-Ton Medium Rigid', capacity: 10, baseFee: 8500, ratePerTonKm: 14 },
  { id: '15_TON', name: '15-Ton Heavy Tipper / Flatbed', capacity: 15, baseFee: 12000, ratePerTonKm: 12 },
  { id: '30_TON', name: '30-Ton Multi-Axle Trailer', capacity: 30, baseFee: 22000, ratePerTonKm: 9.5 },
];

// Calculate Haversine distance in Kilometers
function calculateHaversineDistance(lat1, lon1, lat2, lon2) {
  const R = 6371; // Radius of the Earth in km
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLon / 2) *
      Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  const straightDistance = R * c;
  // Apply a 1.22 multiplier to estimate actual road distance vs straight-line flight distance
  return Math.round(straightDistance * 1.22);
}

export default function ShipmentBookingQuotePage({ onProceedToBooking }) {
  const [originName, setOriginName] = useState(FREIGHT_HUBS[0].name);
  const [destinationName, setDestinationName] = useState(FREIGHT_HUBS[5].name);
  const [cargoType, setCargoType] = useState('General Commercial Cargo');
  const [tonnage, setTonnage] = useState(15);
  const [selectedTruckId, setSelectedTruckId] = useState('15_TON');
  const [isCalculated, setIsCalculated] = useState(false);

  // Retrieve Lat/Lng for selected hubs
  const originHub = FREIGHT_HUBS.find((h) => h.name === originName) || FREIGHT_HUBS[0];
  const destHub = FREIGHT_HUBS.find((h) => h.name === destinationName) || FREIGHT_HUBS[1];

  // Calculate Distance (Km)
  const calculatedDistance = useMemo(() => {
    if (originName === destinationName) return 0;
    return calculateHaversineDistance(
      originHub.lat,
      originHub.lng,
      destHub.lat,
      destHub.lng
    );
  }, [originHub, destHub, originName, destinationName]);

  // Selected Truck Config
  const selectedTruck = TRUCK_TYPES.find((t) => t.id === selectedTruckId) || TRUCK_TYPES[2];

  // Quote Calculation Formula
  const quoteDetails = useMemo(() => {
    if (calculatedDistance === 0) {
      return { totalNet: 0, costPerTon: 0, costPerKm: 0, vatEstimate: 0, totalWithVat: 0 };
    }

    // Formula: Base Fee + (Tonnage * Rate_per_Ton_Km * Distance_Km)
    const variableFreightFee = tonnage * selectedTruck.ratePerTonKm * calculatedDistance;
    const totalNetExcludingVAT = selectedTruck.baseFee + variableFreightFee;
    
    const costPerTon = totalNetExcludingVAT / tonnage;
    const costPerKm = totalNetExcludingVAT / calculatedDistance;
    const vatAmount = totalNetExcludingVAT * 0.16; // 16% Kenya VAT preview
    const totalGrossIncVAT = totalNetExcludingVAT + vatAmount;

    return {
      totalNet: Math.round(totalNetExcludingVAT),
      costPerTon: Math.round(costPerTon),
      costPerKm: Math.round(costPerKm),
      vatEstimate: Math.round(vatAmount),
      totalWithVat: Math.round(totalGrossIncVAT),
    };
  }, [calculatedDistance, tonnage, selectedTruck]);

  const handleCalculateQuote = (e) => {
    e.preventDefault();
    setIsCalculated(true);
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      
      {/* Header Banner */}
      <div className="bg-slate-900 text-white rounded-2xl p-6 shadow-xl border border-slate-800">
        <span className="text-xs font-black uppercase tracking-widest text-blue-400 bg-blue-950 px-3 py-1 rounded-full border border-blue-800">
          Instant Freight Estimator
        </span>
        <h1 className="text-2xl font-black mt-2 tracking-tight">
          Calculate Shipment Route & Tonnage Quote
        </h1>
        <p className="text-slate-400 text-xs mt-1">
          Select origin and destination to compute trip distance, truck tonnage specs, and haulage pricing.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">

        {/* Left Column (7 Cols): Route & Cargo Form */}
        <div className="lg:col-span-7 bg-white rounded-2xl border border-slate-200 p-6 shadow-sm space-y-6">
          <form onSubmit={handleCalculateQuote} className="space-y-5">
            <h3 className="font-extrabold text-sm text-slate-900 uppercase tracking-wider border-b border-slate-100 pb-2">
              1. Origin & Destination Route
            </h3>

            {/* From Origin Dropdown */}
            <div className="space-y-1.5">
              <label className="text-xs font-bold text-slate-700 flex justify-between">
                <span>From (Origin)</span>
                <span className="text-emerald-600 font-mono text-[11px]">Pickup Hub</span>
              </label>
              <select
                value={originName}
                onChange={(e) => {
                  setOriginName(e.target.value);
                  setIsCalculated(false);
                }}
                className="w-full px-4 py-2.5 bg-slate-50 border border-slate-300 rounded-xl text-xs font-bold text-slate-800 focus:bg-white focus:ring-2 focus:ring-blue-500 focus:outline-none"
              >
                {FREIGHT_HUBS.map((hub) => (
                  <option key={hub.name} value={hub.name}>
                    📍 {hub.name}
                  </option>
                ))}
              </select>
            </div>

            {/* To Destination Dropdown */}
            <div className="space-y-1.5">
              <label className="text-xs font-bold text-slate-700 flex justify-between">
                <span>To (Destination)</span>
                <span className="text-blue-600 font-mono text-[11px]">Dropoff Hub</span>
              </label>
              <select
                value={destinationName}
                onChange={(e) => {
                  setDestinationName(e.target.value);
                  setIsCalculated(false);
                }}
                className="w-full px-4 py-2.5 bg-slate-50 border border-slate-300 rounded-xl text-xs font-bold text-slate-800 focus:bg-white focus:ring-2 focus:ring-blue-500 focus:outline-none"
              >
                {FREIGHT_HUBS.map((hub) => (
                  <option key={hub.name} value={hub.name} disabled={hub.name === originName}>
                    🎯 {hub.name}
                  </option>
                ))}
              </select>
            </div>

            <h3 className="font-extrabold text-sm text-slate-900 uppercase tracking-wider border-b border-slate-100 pb-2 pt-3">
              2. Cargo Tonnage & Vehicle Class
            </h3>

            {/* Cargo Type & Tonnage Input */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <label className="text-xs font-bold text-slate-700">Cargo Description</label>
                <input
                  type="text"
                  value={cargoType}
                  onChange={(e) => setCargoType(e.target.value)}
                  placeholder="e.g. FMCG, Steel, Cement"
                  className="w-full px-4 py-2.5 bg-slate-50 border border-slate-300 rounded-xl text-xs font-bold text-slate-800 focus:bg-white focus:ring-2 focus:ring-blue-500 focus:outline-none"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-bold text-slate-700 flex justify-between">
                  <span>Cargo Net Tonnage</span>
                  <span className="text-blue-600 font-mono font-bold">{tonnage} Tons</span>
                </label>
                <input
                  type="number"
                  min="1"
                  max="35"
                  value={tonnage}
                  onChange={(e) => {
                    setTonnage(Number(e.target.value));
                    setIsCalculated(false);
                  }}
                  className="w-full px-4 py-2.5 bg-slate-50 border border-slate-300 rounded-xl text-xs font-bold text-slate-800 focus:bg-white focus:ring-2 focus:ring-blue-500 focus:outline-none"
                />
              </div>
            </div>

            {/* Vehicle Selection Cards */}
            <div className="space-y-2">
              <label className="text-xs font-bold text-slate-700">Select Truck Configuration</label>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                {TRUCK_TYPES.map((truck) => (
                  <button
                    type="button"
                    key={truck.id}
                    onClick={() => {
                      setSelectedTruckId(truck.id);
                      setIsCalculated(false);
                    }}
                    className={`p-3 rounded-xl border text-left transition flex flex-col justify-between ${
                      selectedTruckId === truck.id
                        ? 'border-blue-600 bg-blue-50/60 ring-2 ring-blue-500/20'
                        : 'border-slate-200 bg-slate-50 hover:bg-slate-100'
                    }`}
                  >
                    <div className="flex justify-between items-center w-full">
                      <span className="text-xs font-extrabold text-slate-900">{truck.name}</span>
                      <span className="text-[10px] font-bold text-blue-700 bg-blue-100 px-2 py-0.5 rounded">
                        Max {truck.capacity}T
                      </span>
                    </div>
                    <span className="text-[11px] text-slate-500 mt-1 font-mono">
                      Rate: KES {truck.ratePerTonKm}/Ton-Km
                    </span>
                  </button>
                ))}
              </div>
            </div>

            {/* Action Trigger Button */}
            <button
              type="submit"
              className="w-full bg-blue-600 hover:bg-blue-500 text-white font-extrabold py-3.5 px-6 rounded-xl text-xs transition shadow-lg flex items-center justify-center gap-2"
            >
              <span>🧮</span> Calculate Freight Quote & Distance
            </button>
          </form>
        </div>

        {/* Right Column (5 Cols): Live Quote Summary Card */}
        <div className="lg:col-span-5 space-y-6">
          <div className="bg-slate-900 text-white rounded-2xl p-6 shadow-xl border border-slate-800 space-y-5">
            
            <div className="border-b border-slate-800 pb-3 flex justify-between items-center">
              <div>
                <h3 className="text-base font-extrabold tracking-tight">Freight Quote Details</h3>
                <p className="text-xs text-slate-400">Tonnage & Mileage Breakout</p>
              </div>
              <span className="text-[10px] font-bold text-amber-400 bg-amber-950 px-2.5 py-1 rounded border border-amber-800 uppercase tracking-wide">
                VAT Exclusive
              </span>
            </div>

            {/* Distance Metric Display */}
            <div className="bg-slate-800/90 p-4 rounded-xl border border-slate-700/80 flex justify-between items-center">
              <div>
                <p className="text-[10px] uppercase font-bold text-slate-400">Calculated Route Distance</p>
                <p className="text-2xl font-black text-blue-400 font-mono mt-0.5">
                  {calculatedDistance} <span className="text-sm font-semibold">km</span>
                </p>
              </div>
              <div className="text-right">
                <p className="text-[10px] uppercase font-bold text-slate-400">Total Weight</p>
                <p className="text-xl font-extrabold text-slate-200 font-mono mt-0.5">
                  {tonnage} <span className="text-xs text-slate-400 font-semibold">Tons</span>
                </p>
              </div>
            </div>

            {/* Price Per Tonnage Breakdown Table */}
            <div className="space-y-2.5 text-xs">
              <div className="flex justify-between py-1.5 border-b border-slate-800">
                <span className="text-slate-400">Base Dispatch & Handling Fee</span>
                <span className="font-mono text-slate-200 font-bold">
                  KES {selectedTruck.baseFee.toLocaleString()}
                </span>
              </div>

              <div className="flex justify-between py-1.5 border-b border-slate-800">
                <span className="text-slate-400">
                  Freight Rate ({tonnage}T × {calculatedDistance}km @ KES {selectedTruck.ratePerTonKm})
                </span>
                <span className="font-mono text-slate-200 font-bold">
                  KES {(quoteDetails.totalNet - selectedTruck.baseFee).toLocaleString()}
                </span>
              </div>

              <div className="flex justify-between py-1.5 border-b border-slate-800">
                <span className="text-slate-300 font-bold">Effective Cost Per Ton</span>
                <span className="font-mono text-emerald-400 font-extrabold">
                  KES {quoteDetails.costPerTon.toLocaleString()} / Ton
                </span>
              </div>

              <div className="flex justify-between py-1.5 border-b border-slate-800">
                <span className="text-slate-300 font-bold">Effective Cost Per Km</span>
                <span className="font-mono text-blue-400 font-extrabold">
                  KES {quoteDetails.costPerKm.toLocaleString()} / Km
                </span>
              </div>
            </div>

            {/* Final Total Net Quote Box with Prominent VAT Exclusive Note */}
            <div className="bg-slate-950 p-4 rounded-xl border border-slate-800 space-y-2">
              <div className="flex justify-between items-baseline">
                <div>
                  <p className="text-[11px] font-black uppercase text-slate-400">Net Estimated Quote</p>
                  <p className="text-xs text-amber-400 font-bold mt-0.5">
                    ⚠️ Note: Quote is Exclusive of 16% VAT
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-2xl font-black text-emerald-400 font-mono">
                    KES {quoteDetails.totalNet.toLocaleString()}
                  </p>
                </div>
              </div>

              {/* VAT Breakdown Subtext */}
              <div className="pt-2 border-t border-slate-900 flex justify-between text-[11px] text-slate-500 font-mono">
                <span>Estimated 16% VAT: KES {quoteDetails.vatEstimate.toLocaleString()}</span>
                <span>Gross: KES {quoteDetails.totalWithVat.toLocaleString()}</span>
              </div>
            </div>

            {/* Notice Callout */}
            <div className="p-3 bg-amber-950/40 border border-amber-800/60 rounded-xl text-[11px] text-amber-200/90 leading-relaxed">
              <strong>Notice:</strong> Pricing is computed on a per-tonnage/kilometer matrix. Final invoice is <strong>exclusive of statutory VAT</strong>, which will be itemized separately at checkout upon escrow allocation.
            </div>

            {/* Booking Trigger */}
            <button
              onClick={() => onProceedToBooking && onProceedToBooking({ originName, destinationName, tonnage, quoteDetails })}
              disabled={calculatedDistance === 0}
              className="w-full bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-800 disabled:text-slate-600 text-white font-extrabold py-3.5 px-6 rounded-xl text-xs transition shadow-lg"
            >
              Confirm Route & Lock Escrow Quote →
            </button>

          </div>
        </div>

      </div>
    </div>
  );
}