document.addEventListener('DOMContentLoaded', () => {
  const requestPanel = document.getElementById('shipment-request-panel');
  const requestForm = document.getElementById('shipment-request-form');
  const quoteButton = document.getElementById('request-quote-button');
  const quoteSummary = document.getElementById('request-quote-summary');
  const quoteAcceptance = document.getElementById('request-quote-acceptance');
  const quoteAccepted = document.getElementById('request-quote-accepted');
  const submitRequest = document.getElementById('submit-shipment-request');
  const requestStatus = document.getElementById('shipment-request-status');
  const destinationPanel = document.getElementById('destination-change-panel');
  const destinationForm = document.getElementById('destination-change-form');
  const destinationShipment = document.getElementById('destination-change-shipment');
  const destinationStatus = document.getElementById('destination-change-status');
  const destinationDecision = document.getElementById('destination-change-decision');
  const destinationSubmit = document.getElementById('destination-change-submit');
  const pickupAtInput = document.getElementById('request-pickup-at');
  const deliveryDueAtInput = document.getElementById('request-delivery-due-at');
  if (!requestPanel || !requestForm || !destinationForm) return;

  let currentQuote = null;
  let pendingDestinationChange = null;
  let clientShipments = [];
  const now = new Date();
  pickupAtInput.min = new Date(now.getTime() - now.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 16);
  pickupAtInput.addEventListener('change', () => {
    deliveryDueAtInput.min = pickupAtInput.value;
    if (deliveryDueAtInput.value && deliveryDueAtInput.value <= pickupAtInput.value) {
      deliveryDueAtInput.value = '';
    }
  });

  function tokenHeaders() {
    const token = localStorage.getItem('jwt_token');
    if (!token) throw new Error('Sign in to your client account to request a truck.');
    return { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
  }

  async function apiRequest(path, options = {}) {
    const response = await fetch(`http://localhost:5000${path}`, {
      ...options,
      headers: { ...tokenHeaders(), ...options.headers },
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.message || 'The request could not be completed.');
    return data;
  }

  function updateClientTools() {
    const isClient = window.DifanApp?.state?.currentUser?.role === 'client';
    requestPanel.hidden = !isClient;
    destinationPanel.hidden = !isClient;
    if (isClient) refreshClientShipments();
  }

  function requestPayload() {
    return {
      origin: document.getElementById('request-origin').value,
      destination: document.getElementById('request-destination').value,
      truck_type: document.getElementById('request-truck-type').value,
      cargo_type: document.getElementById('request-cargo').value.trim(),
      tonnage: Number(document.getElementById('request-tonnage').value),
    };
  }

  function clearQuote() {
    currentQuote = null;
    quoteAccepted.checked = false;
    quoteSummary.hidden = true;
    quoteAcceptance.hidden = true;
    submitRequest.hidden = true;
  }

  function formatKes(amount) {
    return `KES ${Number(amount).toLocaleString('en-KE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }

  function renderDestinationDecision(trackingNumber, change, previousRate) {
    pendingDestinationChange = trackingNumber;
    const difference = change.quoted_amount_kes - previousRate;
    destinationStatus.textContent =
      `Original estimated total: ${formatKes(previousRate)}. ` +
      `Revised estimated total: ${formatKes(change.quoted_amount_kes)} ` +
      `(${difference >= 0 ? 'increase' : 'decrease'} of ${formatKes(Math.abs(difference))}).`;
    destinationDecision.replaceChildren();
    const accept = document.createElement('button');
    accept.type = 'button';
    accept.className = 'btn btn-primary';
    accept.textContent = 'Accept revised destination and rate';
    const reject = document.createElement('button');
    reject.type = 'button';
    reject.className = 'btn btn-secondary';
    reject.textContent = 'Keep original destination';
    accept.addEventListener('click', () => decideDestinationChange(true));
    reject.addEventListener('click', () => decideDestinationChange(false));
    destinationDecision.append(accept, reject);
    destinationDecision.hidden = false;
  }

  quoteButton.addEventListener('click', async () => {
    clearQuote();
    quoteButton.disabled = true;
    requestStatus.textContent = 'Calculating a truck rate...';
    try {
      const data = await apiRequest('/api/shipments/quote', {
        method: 'POST',
        body: JSON.stringify(requestPayload()),
      });
      currentQuote = data.quote;
      quoteSummary.textContent =
        `${currentQuote.truck_name} · approx. ${currentQuote.distance_km} km · ` +
        `${currentQuote.tonnage} tonnes · before VAT ${formatKes(currentQuote.subtotal_kes)} · ` +
        `estimated VAT ${formatKes(currentQuote.vat_kes)} · estimated total ${formatKes(currentQuote.total_kes)} · ` +
        `${currentQuote.pricing_source === 'uploaded_destination_rate' ? 'applied destination rate' : 'standard estimate'}.`;
      quoteSummary.hidden = false;
      quoteAcceptance.hidden = false;
      submitRequest.hidden = false;
      requestStatus.textContent = 'Review and accept the estimate to submit your truck request.';
    } catch (error) {
      requestStatus.textContent = error.message || 'Unable to calculate a truck rate.';
    } finally {
      quoteButton.disabled = false;
    }
  });

  requestForm.addEventListener('input', (event) => {
    if (event.target !== quoteAccepted) clearQuote();
  });
  requestForm.addEventListener('change', (event) => {
    if (event.target !== quoteAccepted) clearQuote();
  });
  requestForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!currentQuote || !quoteAccepted.checked) {
      requestStatus.textContent = 'Calculate the rate and accept it before requesting a truck.';
      return;
    }
    submitRequest.disabled = true;
    requestStatus.textContent = 'Submitting your truck request...';
    try {
      const pickupLocal = document.getElementById('request-pickup-at').value;
      const data = await apiRequest('/api/shipments/requests', {
        method: 'POST',
        body: JSON.stringify({
          ...requestPayload(),
          pickup_address: document.getElementById('request-pickup-address').value.trim(),
          pickup_at: new Date(pickupLocal).toISOString(),
          delivery_due_at: new Date(deliveryDueAtInput.value).toISOString(),
          end_customer_name: document.getElementById('request-customer-name').value.trim(),
          end_customer_phone: document.getElementById('request-customer-phone').value.trim(),
          end_customer_address: document.getElementById('request-customer-address').value.trim(),
        }),
      });
      requestStatus.textContent =
        `${data.message} Reference: ${data.shipment.tracking_number}. ` +
        `Estimated total including VAT: ${formatKes(data.quote.total_kes)}.`;
      requestForm.reset();
      clearQuote();
      await refreshClientShipments();
    } catch (error) {
      requestStatus.textContent = error.message || 'Unable to submit the truck request.';
    } finally {
      submitRequest.disabled = false;
    }
  });

  async function refreshClientShipments() {
    try {
      const data = await apiRequest('/api/shipments');
      clientShipments = data.shipments;
      destinationShipment.replaceChildren();
      const eligible = data.shipments.filter((shipment) =>
        ['REQUESTED', 'PLANNED', 'ASSIGNED'].includes(shipment.status)
        && shipment.truck_type
      );
      eligible.forEach((shipment) => {
        const option = document.createElement('option');
        option.value = shipment.tracking_number;
        option.textContent = `${shipment.tracking_number} · ${shipment.origin} → ${shipment.destination}${shipment.destination_change_pending ? ' (change awaiting decision)' : ''}`;
        destinationShipment.appendChild(option);
      });
      if (!eligible.length) {
        const option = document.createElement('option');
        option.value = '';
        option.textContent = 'No eligible shipments yet';
        destinationShipment.appendChild(option);
        destinationSubmit.disabled = true;
        pendingDestinationChange = null;
        destinationDecision.hidden = true;
      } else {
        destinationSubmit.disabled = false;
        showSelectedDestinationChange();
      }
    } catch (error) {
      destinationStatus.textContent = error.message || 'Unable to load your shipments.';
    }
  }

  function showSelectedDestinationChange() {
    const shipment = clientShipments.find(
      (item) => item.tracking_number === destinationShipment.value,
    );
    destinationSubmit.disabled = Boolean(shipment?.destination_change_pending);
    if (shipment?.destination_change) {
      renderDestinationDecision(
        shipment.tracking_number,
        shipment.destination_change,
        shipment.quoted_amount_kes,
      );
    } else {
      pendingDestinationChange = null;
      destinationDecision.hidden = true;
      destinationStatus.textContent = '';
    }
  }

  destinationShipment.addEventListener('change', showSelectedDestinationChange);

  destinationForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    destinationSubmit.disabled = true;
    destinationStatus.textContent = 'Calculating the revised destination rate...';
    destinationDecision.hidden = true;
    try {
      const trackingNumber = destinationShipment.value;
      if (!trackingNumber) throw new Error('Select an eligible shipment.');
      const data = await apiRequest(
        `/api/shipments/${encodeURIComponent(trackingNumber)}/destination-change`,
        {
          method: 'POST',
          body: JSON.stringify({
            destination: document.getElementById('destination-change-hub').value,
            end_customer_address: document.getElementById('destination-change-address').value.trim(),
          }),
        },
      );
      pendingDestinationChange = trackingNumber;
      renderDestinationDecision(trackingNumber, data.change, data.previous_quote_kes);
    } catch (error) {
      destinationStatus.textContent = error.message || 'Unable to calculate the revised rate.';
      destinationSubmit.disabled = false;
    }
  });

  async function decideDestinationChange(accept) {
    if (!pendingDestinationChange) return;
    destinationStatus.textContent = accept ? 'Applying the revised destination and rate...' : 'Keeping the original destination...';
    destinationDecision.querySelectorAll('button').forEach((button) => { button.disabled = true; });
    try {
      const data = await apiRequest(
        `/api/shipments/${encodeURIComponent(pendingDestinationChange)}/destination-change/decision`,
        { method: 'POST', body: JSON.stringify({ accept }) },
      );
      destinationStatus.textContent = data.message;
      pendingDestinationChange = null;
      destinationDecision.hidden = true;
      destinationForm.reset();
      destinationSubmit.disabled = false;
      await refreshClientShipments();
    } catch (error) {
      destinationStatus.textContent = error.message || 'Unable to save your decision.';
      destinationDecision.querySelectorAll('button').forEach((button) => { button.disabled = false; });
    }
  }

  window.addEventListener('difan:session-ready', updateClientTools);
});
