(function () {
  const form = document.getElementById('shipment-track-form');
  if (!form) return;

  const trackingInput = document.getElementById('shipment-tracking-number');
  const submitButton = document.getElementById('shipment-track-submit');
  const statusMessage = document.getElementById('shipment-track-status');
  const details = document.getElementById('shipment-track-details');
  const navLink = document.querySelector('[data-target-tab="tracking"]');
  let hasLoadedInitialShipment = false;

  function setStatus(message, state) {
    statusMessage.textContent = message;
    statusMessage.dataset.state = state;
  }

  function setText(id, value) {
    document.getElementById(id).textContent = value;
  }

  async function loadShipment(trackingNumber) {
    submitButton.disabled = true;
    details.hidden = true;
    setStatus(`Looking up ${trackingNumber}...`, 'info');

    try {
      const response = await fetch(
        `http://localhost:5000/api/shipments/track/${encodeURIComponent(trackingNumber)}`
      );
      const data = await response.json();
      if (!response.ok || data.status !== 'success' || !data.shipment) {
        throw new Error(data.message || 'Shipment lookup failed.');
      }

      const shipment = data.shipment;
      setText('shipment-track-id', shipment.tracking_number);
      setText('shipment-track-shipment-status', shipment.status || 'Status unavailable');
      setText('shipment-track-origin', shipment.origin || 'Not provided');
      setText('shipment-track-destination', shipment.destination || 'Not provided');
      setText('shipment-track-cargo', shipment.cargo_type || 'Not provided');
      setText('shipment-track-tonnage', `${shipment.tonnage ?? 0} tonnes`);
      details.hidden = false;
      document.dispatchEvent(new CustomEvent('shipment:loaded', { detail: shipment }));
      setStatus(`Shipment ${shipment.tracking_number} found.`, 'success');
    } catch (error) {
      setStatus(error.message || 'Unable to reach the shipment service.', 'error');
    } finally {
      submitButton.disabled = false;
    }
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const trackingNumber = trackingInput.value.trim();
    if (trackingNumber) loadShipment(trackingNumber);
  });

  if (navLink) {
    navLink.addEventListener('click', () => {
      if (!hasLoadedInitialShipment) {
        hasLoadedInitialShipment = true;
        loadShipment(trackingInput.value.trim());
      }
    });
  }
})();