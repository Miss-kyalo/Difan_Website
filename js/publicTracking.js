document.addEventListener('DOMContentLoaded', () => {
  const status = document.getElementById('public-tracking-status');
  const content = document.getElementById('public-tracking-content');
  const token = new URLSearchParams(window.location.search).get('token');
  if (!token) {
    status.textContent = 'This tracking link is incomplete or has expired. Request a new link from your shipper.';
    status.dataset.state = 'error';
    return;
  }

  function displayDate(value) {
    return value ? new Date(value).toLocaleString() : 'Not yet scheduled';
  }

  async function refreshTracking() {
    try {
      const response = await fetch(`/api/shipments/public-tracking/${encodeURIComponent(token)}`, {
        cache: 'no-store',
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || 'Shipment status is unavailable.');
      const tracking = data.tracking;
      document.getElementById('public-tracking-company').textContent = tracking.company_name;
      document.getElementById('public-tracking-reference').textContent = tracking.tracking_number;
      document.getElementById('public-tracking-state').textContent =
        tracking.shipment_status.replaceAll('_', ' ');
      document.getElementById('public-tracking-origin').textContent = tracking.origin;
      document.getElementById('public-tracking-destination').textContent = tracking.destination;
      document.getElementById('public-tracking-deadline').textContent = displayDate(tracking.delivery_due_at);
      document.getElementById('public-tracking-updated').textContent = displayDate(tracking.last_updated_at);
      content.hidden = false;
      status.textContent = tracking.shipment_status === 'DELIVERED'
        ? `Delivery completed ${displayDate(tracking.arrived_at)}.`
        : 'Shipment status refreshes automatically every 30 seconds.';
    } catch (error) {
      status.textContent = error.message || 'Shipment status could not be loaded.';
      status.dataset.state = 'error';
    }
  }

  void refreshTracking();
  window.setInterval(refreshTracking, 30_000);
});
