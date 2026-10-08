document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('shipment-track-form');
  if (!form) return;

  const trackingInput = document.getElementById('shipment-tracking-number');
  const submitButton = document.getElementById('shipment-track-submit');
  const statusMessage = document.getElementById('shipment-track-status');
  const details = document.getElementById('shipment-track-details');
  const accessibleList = document.getElementById('shipment-accessible-list');
  const navLink = document.querySelector('[data-target-tab="tracking"]');
  const adminTools = document.getElementById('tracking-admin-tools');
  const assignmentForm = document.getElementById('shipment-assignment-form');
  const destinationRatesForm = document.getElementById('destination-rates-upload-form');
  const destinationRatesPreview = document.getElementById('destination-rates-preview');
  const destinationRatesImport = document.getElementById('destination-rates-import-button');
  const destinationRatesStatus = document.getElementById('destination-rates-status');
  const roleForm = document.getElementById('account-role-form');
  const adminStatus = document.getElementById('tracking-admin-status');
  const accountRole = document.getElementById('account-role-value');
  const driverNameField = document.getElementById('driver-name-field');
  const uploadForm = document.getElementById('shipment-document-upload-form');
  const uploadStatus = document.getElementById('document-upload-status');
  const documentPanel = document.getElementById('goods-document-access-panel');
  const uploadPanel = document.getElementById('goods-document-upload-panel');
  const documentSelect = document.getElementById('document-shipment-select');
  const uploadShipmentSelect = document.getElementById('upload-shipment-select');
  const documentList = document.getElementById('shipment-document-list');
  const goodsNavLink = document.getElementById('goods-navigation');
  const goodsCompanySelect = document.getElementById('goods-company-select');
  const goodsDeliverySelect = document.getElementById('goods-delivery-select');
  const goodsDeliveryDetails = document.getElementById('goods-delivery-details');
  const clientInTransitPanel = document.getElementById('client-in-transit-panel');
  const clientInTransitList = document.getElementById('client-in-transit-list');
  const podSignaturePanel = document.getElementById('client-pod-signature-panel');
  const podSignatureForm = document.getElementById('client-pod-signature-form');
  const podSignatureCanvas = document.getElementById('client-pod-signature-canvas');
  const podSignatureContext = podSignatureCanvas.getContext('2d');
  const podSignatureStatus = document.getElementById('client-pod-status');
  const podSignatureSummary = document.getElementById('client-pod-shipment-summary');
  const podSignatureSubmit = document.getElementById('client-pod-submit-signature');
  const podDownloadButton = document.getElementById('client-pod-download');
  let hasPodSignature = false;
  let shipments = [];
  let clientAccounts = [];
  let pendingRatePreview = null;
  let trackingPollTimer = null;

  function setStatus(message, state = 'info') {
    statusMessage.textContent = message;
    statusMessage.dataset.state = state;
  }

  function tokenHeaders() {
    const token = localStorage.getItem('jwt_token');
    if (!token) throw new Error('Please sign in to access shipment tracking.');
    return { Authorization: `Bearer ${token}` };
  }

  async function apiRequest(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      headers: {
        ...tokenHeaders(),
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...options.headers,
      },
    });
    const contentType = response.headers.get('Content-Type') || '';
    const data = contentType.includes('application/json')
      ? await response.json()
      : { message: 'The server returned an unexpected response.' };
    if (!response.ok) throw new Error(data.message || data.error || 'The request could not be completed.');
    return data;
  }

  function renderClientTransitGoods() {
    const isClient = window.DifanApp?.state?.currentUser?.role === 'client';
    clientInTransitPanel.hidden = !isClient;
    if (!isClient) return;

    clientInTransitList.replaceChildren();
    const currentLoads = shipments.filter((shipment) =>
      ['IN_TRANSIT', 'BREAKDOWN'].includes(shipment.status),
    );
    if (!currentLoads.length) {
      const empty = document.createElement('p');
      empty.className = 'workflow-empty';
      empty.textContent = 'There are no goods currently in transit for your account.';
      clientInTransitList.appendChild(empty);
      return;
    }

    currentLoads.forEach((shipment) => {
      const card = document.createElement('article');
      card.className = 'shipment-access-card';
      const details = document.createElement('div');
      const heading = document.createElement('strong');
      heading.textContent = `${shipment.cargo_type} · ${shipment.tonnage} tonnes`;
      details.appendChild(heading);

      const reference = document.createElement('p');
      reference.textContent = `${shipment.tracking_number} · ${shipment.status.replaceAll('_', ' ')}`;
      details.appendChild(reference);

      const route = document.createElement('p');
      route.textContent = `${shipment.origin} → ${shipment.destination}`;
      details.appendChild(route);

      const driver = document.createElement('p');
      driver.textContent = `Driver: ${shipment.assigned_driver_name || 'Assignment pending'} · Departed: ${shipment.departed_at ? new Date(shipment.departed_at).toLocaleString() : 'Not recorded'}`;
      details.appendChild(driver);

      if (shipment.delivery_due_at) {
        const deadline = document.createElement('p');
        deadline.textContent = `Delivery window: ${new Date(shipment.delivery_due_at).toLocaleString()}`;
        details.appendChild(deadline);
      }
      if (shipment.deliveries?.length) {
        const goodsList = document.createElement('ul');
        goodsList.className = 'shipment-delivery-summary';
        shipment.deliveries.forEach((delivery) => {
          const item = document.createElement('li');
          item.textContent = `${delivery.goods_description || 'Goods'} · ${delivery.destination || shipment.destination}${delivery.customer_name ? ` · ${delivery.customer_name}` : ''}`;
          goodsList.appendChild(item);
        });
        details.appendChild(goodsList);
      }

      const trackButton = document.createElement('button');
      trackButton.type = 'button';
      trackButton.className = 'btn btn-secondary';
      trackButton.textContent = 'Track load';
      trackButton.addEventListener('click', () => {
        trackingInput.value = shipment.tracking_number;
        loadShipment(shipment.tracking_number);
      });
      card.append(details, trackButton);
      clientInTransitList.appendChild(card);
    });
  }

  function renderAccessibleShipments() {
    accessibleList.replaceChildren();
    if (!shipments.length) {
      const empty = document.createElement('p');
      empty.className = 'workflow-empty';
      empty.textContent = 'No shipments are assigned to this account yet.';
      accessibleList.appendChild(empty);
      renderClientTransitGoods();
      return;
    }

    const heading = document.createElement('h3');
    heading.textContent = 'Shipments available to your account';
    accessibleList.appendChild(heading);
    shipments.forEach((shipment) => {
      const card = document.createElement('article');
      card.className = 'shipment-access-card';
      const info = document.createElement('div');
      const title = document.createElement('strong');
      title.textContent = `${shipment.tracking_number} · ${shipment.status.replaceAll('_', ' ')}`;
      info.appendChild(title);

      const goods = document.createElement('p');
      goods.textContent = `${shipment.cargo_type} · ${shipment.tonnage} tonnes`;
      info.appendChild(goods);

      const association = document.createElement('p');
      const company = shipment.company_name || 'Company not assigned';
      const driver = shipment.assigned_driver_name || 'Driver not assigned';
      association.textContent = `Company: ${company} · Driver: ${driver}`;
      info.appendChild(association);

      const deliveries = shipment.deliveries || [];
      if (deliveries.length) {
        const deliveryList = document.createElement('ul');
        deliveryList.className = 'shipment-delivery-summary';
        deliveries.forEach((delivery) => {
          const item = document.createElement('li');
          item.textContent = `${delivery.delivery_number} · ${delivery.goods_description || 'Goods not read'} · ${delivery.destination || shipment.destination}${delivery.customer_name ? ` · Customer: ${delivery.customer_name}` : ''}`;
          deliveryList.appendChild(item);
        });
        info.appendChild(deliveryList);
      }

      const trackButton = document.createElement('button');
      trackButton.type = 'button';
      trackButton.className = 'btn btn-secondary';
      trackButton.textContent = 'Track shipment';
      trackButton.addEventListener('click', () => {
        trackingInput.value = shipment.tracking_number;
        loadShipment(shipment.tracking_number);
      });
      card.append(info, trackButton);
      if (window.DifanApp?.state?.currentUser?.role === 'driver' &&
          ['ASSIGNED', 'AWAITING_DISPATCH', 'IN_TRANSIT'].includes(shipment.status)) {
        let clientSelect = null;
        const canStartTrip = ['ASSIGNED', 'AWAITING_DISPATCH'].includes(shipment.status);
        if (canStartTrip && !shipment.client_user_id) {
          const clientField = document.createElement('div');
          clientField.className = 'field';
          const clientLabel = document.createElement('label');
          clientLabel.textContent = 'Client company loaded for';
          clientSelect = document.createElement('select');
          clientSelect.required = true;
          clientSelect.setAttribute('aria-label', 'Client company loaded for');
          const placeholder = document.createElement('option');
          placeholder.value = '';
          placeholder.textContent = 'Select the client company';
          clientSelect.appendChild(placeholder);
          clientAccounts.forEach((account) => {
            const option = document.createElement('option');
            option.value = String(account.id);
            option.textContent = `${account.company_name} — ${account.display_name || account.email}`;
            if (
              shipment.company_name
              && shipment.company_name.trim().toLocaleLowerCase() === account.company_name.trim().toLocaleLowerCase()
            ) {
              option.selected = true;
            }
            clientSelect.appendChild(option);
          });
          clientField.append(clientLabel, clientSelect);
          card.appendChild(clientField);
        }
        const statusButton = document.createElement('button');
        statusButton.type = 'button';
        statusButton.className = 'btn btn-primary';
        statusButton.textContent = canStartTrip
          ? (shipment.client_user_id ? 'Start trip' : 'Confirm company and start trip')
          : 'Mark delivered';
        if (clientSelect) {
          statusButton.disabled = !clientSelect.value;
          clientSelect.addEventListener('change', () => {
            statusButton.disabled = !clientSelect.value;
          });
        }
        statusButton.addEventListener('click', async () => {
          if (clientSelect && !clientSelect.value) {
            setStatus('Select the client company loaded for this shipment before starting the trip.', 'error');
            return;
          }
          statusButton.disabled = true;
          try {
            const statusUpdate = { status: canStartTrip ? 'IN_TRANSIT' : 'DELIVERED' };
            if (clientSelect) statusUpdate.client_user_id = Number(clientSelect.value);
            const updated = await apiRequest(`http://localhost:5000/api/shipments/${encodeURIComponent(shipment.tracking_number)}/status`, {
              method: 'PATCH',
              body: JSON.stringify(statusUpdate),
            });
            document.dispatchEvent(new CustomEvent('shipment:loaded', { detail: updated.shipment }));
            await loadAvailableShipments();
          } catch (error) {
            setStatus(error.message || 'Could not update the shipment status.', 'error');
            statusButton.disabled = false;
          }
        });
        card.appendChild(statusButton);
      }
      accessibleList.appendChild(card);
    });
    renderClientTransitGoods();
  }

  function replaceSelectOptions(select, records, placeholder) {
    select.replaceChildren();
    const empty = document.createElement('option');
    empty.value = '';
    empty.textContent = placeholder;
    select.appendChild(empty);
    records.forEach((shipment) => {
      const option = document.createElement('option');
      option.value = shipment.tracking_number;
      option.textContent = `${shipment.tracking_number} · ${shipment.destination}`;
      select.appendChild(option);
    });
  }

  function renderGoodsDeliveryDetails() {
    goodsDeliveryDetails.replaceChildren();
    const shipment = shipments.find((item) => item.tracking_number === goodsDeliverySelect.value);
    if (!shipment) {
      const empty = document.createElement('p');
      empty.className = 'workflow-empty';
      empty.textContent = 'No assigned shipments are available for this client account.';
      goodsDeliveryDetails.appendChild(empty);
      return;
    }

    const summary = document.createElement('p');
    summary.textContent = `${shipment.tracking_number} · ${shipment.status.replaceAll('_', ' ')} · ${shipment.origin} to ${shipment.destination}`;
    goodsDeliveryDetails.appendChild(summary);
    const deliveries = shipment.deliveries || [];
    if (!deliveries.length) {
      const empty = document.createElement('p');
      empty.className = 'workflow-empty';
      empty.textContent = 'No OCR-extracted delivery records have been uploaded for this shipment yet.';
      goodsDeliveryDetails.appendChild(empty);
      return;
    }
    const list = document.createElement('ul');
    list.className = 'shipment-delivery-summary';
    deliveries.forEach((delivery) => {
      const item = document.createElement('li');
      item.textContent = [
        delivery.delivery_number,
        delivery.goods_description || 'Goods not read',
        delivery.destination || shipment.destination,
        delivery.customer_name ? `Client: ${delivery.customer_name}` : '',
      ].filter(Boolean).join(' · ');
      list.appendChild(item);
    });
    goodsDeliveryDetails.appendChild(list);
  }

  function clearPodSignature() {
    podSignatureContext.fillStyle = '#fff';
    podSignatureContext.fillRect(0, 0, podSignatureCanvas.width, podSignatureCanvas.height);
    podSignatureContext.beginPath();
    hasPodSignature = false;
  }

  function refreshPodSignaturePanel() {
    const isClient = window.DifanApp?.state?.currentUser?.role === 'client';
    podSignaturePanel.hidden = !isClient;
    if (!isClient) return;

    const shipment = shipments.find((item) => item.tracking_number === goodsDeliverySelect.value);
    if (!shipment) {
      podSignatureSummary.textContent = 'Select a delivery to see its signing status.';
      podSignatureStatus.textContent = '';
      podSignatureForm.hidden = true;
      podDownloadButton.hidden = true;
      return;
    }

    podSignatureSummary.textContent =
      `${shipment.tracking_number} · ${shipment.cargo_type}, ${shipment.tonnage} tonnes · ` +
      `${shipment.origin} to ${shipment.destination}`;
    if (shipment.pod_signed_at) {
      podSignatureForm.hidden = true;
      podDownloadButton.hidden = false;
      podSignatureStatus.textContent =
        `Signed by ${shipment.pod_signed_by} on ${new Date(shipment.pod_signed_at).toLocaleString()}.`;
    } else if (shipment.status === 'DELIVERED') {
      podSignatureForm.hidden = false;
      podDownloadButton.hidden = true;
      podSignatureStatus.textContent = 'Confirm the cargo was received, then sign below.';
      clearPodSignature();
    } else {
      podSignatureForm.hidden = true;
      podDownloadButton.hidden = true;
      podSignatureStatus.textContent = 'Electronic sign-off is available after the driver marks this shipment delivered.';
    }
  }

  function signaturePoint(event) {
    const bounds = podSignatureCanvas.getBoundingClientRect();
    return {
      x: (event.clientX - bounds.left) * podSignatureCanvas.width / bounds.width,
      y: (event.clientY - bounds.top) * podSignatureCanvas.height / bounds.height,
    };
  }

  podSignatureCanvas.addEventListener('pointerdown', (event) => {
    podSignatureCanvas.setPointerCapture(event.pointerId);
    const point = signaturePoint(event);
    podSignatureContext.beginPath();
    podSignatureContext.moveTo(point.x, point.y);
  });
  podSignatureCanvas.addEventListener('pointermove', (event) => {
    if (!podSignatureCanvas.hasPointerCapture(event.pointerId)) return;
    const point = signaturePoint(event);
    podSignatureContext.lineWidth = 4;
    podSignatureContext.lineCap = 'round';
    podSignatureContext.strokeStyle = '#1b3b2b';
    podSignatureContext.lineTo(point.x, point.y);
    podSignatureContext.stroke();
    hasPodSignature = true;
  });
  document.getElementById('client-pod-clear-signature').addEventListener('click', clearPodSignature);

  podDownloadButton.addEventListener('click', async () => {
    const shipment = shipments.find((item) => item.tracking_number === goodsDeliverySelect.value);
    if (!shipment?.proof_of_delivery_download_url) return;
    try {
      const response = await fetch(`http://localhost:5000${shipment.proof_of_delivery_download_url}`, {
        headers: tokenHeaders(),
      });
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.message || 'The signed proof of delivery could not be downloaded.');
      }
      const objectUrl = URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a');
      anchor.href = objectUrl;
      anchor.download = `${shipment.tracking_number}-signed-proof-of-delivery.pdf`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (error) {
      podSignatureStatus.textContent = error.message || 'The signed proof of delivery could not be downloaded.';
    }
  });

  podSignatureForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const shipment = shipments.find((item) => item.tracking_number === goodsDeliverySelect.value);
    if (!shipment || !hasPodSignature) {
      podSignatureStatus.textContent = 'Draw your signature before submitting.';
      return;
    }
    podSignatureSubmit.disabled = true;
    podSignatureStatus.textContent = 'Recording your electronic signature...';
    try {
      const data = await apiRequest(
        `http://localhost:5000/api/shipments/${encodeURIComponent(shipment.tracking_number)}/proof-of-delivery/sign`,
        {
          method: 'POST',
          body: JSON.stringify({
            signer_name: document.getElementById('client-pod-signer-name').value.trim(),
            signature_png: podSignatureCanvas.toDataURL('image/png'),
          }),
        },
      );
      podSignatureStatus.textContent = data.invoice_created
        ? `${data.message} Your delivery invoice is now available in Finance.`
        : data.message;
      await loadAvailableShipments();
    } catch (error) {
      podSignatureStatus.textContent = error.message || 'Unable to record the signature.';
    } finally {
      podSignatureSubmit.disabled = false;
    }
  });

  function refreshGoodsDeliveryOptions() {
    if (!goodsCompanySelect || !goodsDeliverySelect || !goodsDeliveryDetails) return;
    const user = window.DifanApp?.state?.currentUser;
    const role = user?.role;
    const isAdminOrHr = ['admin', 'hr', 'boss'].includes(role);
    const companyNames = isAdminOrHr
      ? [...new Set(clientAccounts.map((account) => account.company_name).filter(Boolean))]
      : role === 'client'
        ? [user.company_name].filter(Boolean)
        : [...new Set(shipments.map((shipment) => shipment.company_name).filter(Boolean))];
    const currentCompany = goodsCompanySelect.value;
    goodsCompanySelect.replaceChildren();
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = 'Select a client account';
    goodsCompanySelect.appendChild(placeholder);
    companyNames.sort((a, b) => a.localeCompare(b)).forEach((company) => {
      const option = document.createElement('option');
      option.value = company;
      option.textContent = company;
      goodsCompanySelect.appendChild(option);
    });
    goodsCompanySelect.disabled = companyNames.length <= 1;
    goodsCompanySelect.value = companyNames.includes(currentCompany)
      ? currentCompany
      : (companyNames[0] || '');

    const selectedCompany = goodsCompanySelect.value;
    const normalizedCompany = selectedCompany.trim().toLocaleLowerCase();
    const companyShipments = shipments.filter(
      (shipment) => (shipment.company_name || '').trim().toLocaleLowerCase() === normalizedCompany,
    );
    replaceSelectOptions(goodsDeliverySelect, companyShipments, 'Select an assigned delivery');
    goodsDeliverySelect.disabled = !companyShipments.length;
    if (companyShipments.length) goodsDeliverySelect.value = companyShipments[0].tracking_number;
    renderGoodsDeliveryDetails();
    refreshPodSignaturePanel();
  }

  function formatStamp(value) {
    return value ? new Date(value).toLocaleString() : 'Pending';
  }

  async function downloadDocument(documentRecord) {
    try {
      const response = await fetch(`http://localhost:5000${documentRecord.download_url}`, {
        headers: tokenHeaders(),
      });
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.message || 'Document download failed.');
      }
      const objectUrl = URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a');
      anchor.href = objectUrl;
      anchor.download = documentRecord.filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (error) {
      uploadStatus.textContent = error.message || 'Could not download the document.';
    }
  }

  async function loadShipmentDocuments(trackingNumber) {
    documentList.replaceChildren();
    if (!trackingNumber) return;
    const loading = document.createElement('p');
    loading.className = 'muted';
    loading.textContent = 'Loading validated documents...';
    documentList.appendChild(loading);
    try {
      const data = await apiRequest(
        `http://localhost:5000/api/shipments/${encodeURIComponent(trackingNumber)}/documents`
      );
      documentList.replaceChildren();
      if (!data.documents.length) {
        const empty = document.createElement('p');
        empty.className = 'workflow-empty';
        empty.textContent = 'No documents have been uploaded for this shipment.';
        documentList.appendChild(empty);
        return;
      }
      data.documents.forEach((record) => {
        const card = document.createElement('article');
        card.className = 'workflow-card document-card';
        const heading = document.createElement('h3');
        heading.textContent = record.filename;
        card.appendChild(heading);
        const type = document.createElement('p');
        type.textContent = record.document_type === 'proof_of_delivery' ? 'Proof of delivery' : 'Delivery document';
        card.appendChild(type);
        const validation = document.createElement('p');
        validation.textContent = `Destination OCR: ${record.destination_validated ? `verified — ${record.ocr_destination}` : 'not verified'}`;
        card.appendChild(validation);
        if (record.extracted_deliveries?.length) {
          const deliveryList = document.createElement('ul');
          deliveryList.className = 'shipment-delivery-summary';
          record.extracted_deliveries.forEach((delivery) => {
            const item = document.createElement('li');
            item.textContent = `${delivery.delivery_number} · ${delivery.goods_description || 'Goods not detected'} · ${delivery.destination || 'Destination not detected'}${delivery.customer_name ? ` · Customer: ${delivery.customer_name}` : ''}`;
            deliveryList.appendChild(item);
          });
          card.appendChild(deliveryList);
        }
        const stamps = document.createElement('p');
        stamps.className = 'document-stamps';
        stamps.textContent = `Security stamp: ${formatStamp(record.security_stamped_at)} · Client received stamp: ${formatStamp(record.client_received_stamped_at)}`;
        card.appendChild(stamps);
        const download = document.createElement('button');
        download.type = 'button';
        download.className = 'btn btn-secondary';
        download.textContent = 'Download stamped document';
        download.addEventListener('click', () => downloadDocument(record));
        card.appendChild(download);
        documentList.appendChild(card);
      });
    } catch (error) {
      documentList.replaceChildren();
      const message = document.createElement('p');
      message.className = 'workflow-empty';
      message.textContent = error.message || 'Unable to load shipment documents.';
      documentList.appendChild(message);
    }
  }

  async function refreshGoodsPage() {
    const role = window.DifanApp?.state?.currentUser?.role;
    const isDriver = role === 'driver';
    const isAdminOrHr = ['admin', 'hr', 'boss'].includes(role);
    const canDownload = role === 'client' || isAdminOrHr;
    uploadPanel.hidden = !isDriver;
    documentPanel.hidden = !canDownload;
    document.getElementById('goods-delivery-browser').hidden =
      !['driver', 'client', 'admin', 'hr'].includes(role);
    try {
      const data = await apiRequest('http://localhost:5000/api/shipments');
      shipments = data.shipments || [];
      refreshGoodsDeliveryOptions();
      if (isDriver) {
        replaceSelectOptions(uploadShipmentSelect, shipments, 'Select an assigned shipment');
      }
      if (canDownload) {
        replaceSelectOptions(documentSelect, shipments, 'Select a shipment');
        if (shipments.length) {
          documentSelect.value = shipments[0].tracking_number;
          await loadShipmentDocuments(documentSelect.value);
        } else {
          documentList.replaceChildren();
          const empty = document.createElement('p');
          empty.className = 'workflow-empty';
          empty.textContent = 'No shipments are assigned to this account.';
          documentList.appendChild(empty);
        }
      }
    } catch (error) {
      uploadStatus.textContent = error.message || 'Unable to load shipment documents.';
    }
  }

  async function loadAvailableShipments() {
    try {
      const data = await apiRequest('http://localhost:5000/api/shipments');
      shipments = data.shipments || [];
      const user = window.DifanApp?.state?.currentUser;
      const isAdminOrHr = ['admin', 'hr', 'boss'].includes(user?.role);
      if (user?.role === 'driver') {
        const clientData = await apiRequest('http://localhost:5000/api/shipments/clients');
        clientAccounts = clientData.clients || [];
      }
      renderAccessibleShipments();
      setStatus(`${shipments.length} shipment${shipments.length === 1 ? '' : 's'} available to your account.`, 'success');

      adminTools.hidden = !isAdminOrHr;
      if (isAdminOrHr) await loadAdminOptions();
      if (user?.role === 'driver' || user?.role === 'client' || isAdminOrHr) {
        await refreshGoodsPage();
      }
    } catch (error) {
      shipments = [];
      renderAccessibleShipments();
      adminTools.hidden = true;
      setStatus(error.message || 'Unable to load shipments for this account.', 'error');
    }
  }

  async function loadShipment(trackingNumber) {
    if (!trackingNumber) return;
    if (trackingPollTimer) clearInterval(trackingPollTimer);
    submitButton.disabled = true;
    details.hidden = true;
    setStatus(`Looking up ${trackingNumber}...`);

    try {
      const data = await apiRequest(
        `http://localhost:5000/api/shipments/track/${encodeURIComponent(trackingNumber)}`
      );
      const shipment = data.shipment;
      details.hidden = false;
      document.dispatchEvent(new CustomEvent('shipment:loaded', { detail: shipment }));
      setStatus(`Shipment ${shipment.tracking_number} found for ${shipment.company_name}.`, 'success');
      trackingPollTimer = setInterval(async () => {
        try {
          const latest = await apiRequest(
            `http://localhost:5000/api/shipments/track/${encodeURIComponent(shipment.tracking_number)}`
          );
          document.dispatchEvent(new CustomEvent('shipment:loaded', { detail: latest.shipment }));
        } catch (error) {
          setStatus(error.message || 'Live shipment status could not be refreshed.', 'error');
        }
      }, 30_000);
    } catch (error) {
      setStatus(error.message || 'Unable to reach the shipment service.', 'error');
    } finally {
      submitButton.disabled = false;
    }
  }

  function renderRatePreview(rows) {
    destinationRatesPreview.replaceChildren();
    rows.forEach((row) => {
      const tr = document.createElement('tr');
      const values = [
        String(row.row_number),
        row.origin,
        row.destination,
        row.truck_type,
        row.flat_rate_kes === null ? '—' : Number(row.flat_rate_kes).toLocaleString('en-KE', { minimumFractionDigits: 2 }),
        row.valid ? 'Ready to import' : row.errors.join(' '),
      ];
      values.forEach((value) => {
        const cell = document.createElement('td');
        cell.textContent = value;
        tr.appendChild(cell);
      });
      destinationRatesPreview.appendChild(tr);
    });
    if (!rows.length) {
      const row = document.createElement('tr');
      const cell = document.createElement('td');
      cell.colSpan = 6;
      cell.textContent = 'No rate rows were extracted.';
      row.appendChild(cell);
      destinationRatesPreview.appendChild(row);
    }
  }

  async function loadDestinationRates() {
    const list = document.getElementById('destination-rates-current');
    list.replaceChildren();
    try {
      const data = await apiRequest('http://localhost:5000/api/shipments/rates');
      if (!data.rates.length) {
        const empty = document.createElement('p');
        empty.className = 'workflow-empty';
        empty.textContent = 'No destination-specific rates are currently applied. Quotes use the standard estimate.';
        list.appendChild(empty);
        return;
      }
      data.rates.forEach((rate) => {
        const card = document.createElement('article');
        card.className = 'workflow-card';
        card.textContent =
          `${rate.origin} → ${rate.destination} · ${rate.truck_name} · KES ${Number(rate.flat_rate_kes).toLocaleString('en-KE', { minimumFractionDigits: 2 })} before VAT · ${rate.source_filename}`;
        list.appendChild(card);
      });
    } catch (error) {
      const message = document.createElement('p');
      message.className = 'workflow-empty';
      message.textContent = error.message || 'Applied destination rates could not be loaded.';
      list.appendChild(message);
    }
  }

  destinationRatesForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    pendingRatePreview = null;
    destinationRatesImport.hidden = true;
    destinationRatesPreview.replaceChildren();
    const file = document.getElementById('destination-rates-file').files[0];
    if (!file) {
      destinationRatesStatus.textContent = 'Choose an Excel or PDF rate sheet.';
      return;
    }
    const formData = new FormData();
    formData.append('file', file);
    const submit = destinationRatesForm.querySelector('button[type="submit"]');
    submit.disabled = true;
    destinationRatesStatus.textContent = 'Extracting rate rows for review...';
    try {
      const response = await fetch('http://localhost:5000/api/shipments/rates/preview', {
        method: 'POST',
        headers: tokenHeaders(),
        body: formData,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || 'Rate-sheet preview failed.');
      pendingRatePreview = data;
      renderRatePreview(data.rows);
      destinationRatesImport.hidden = !data.valid_rows || data.invalid_rows > 0;
      destinationRatesStatus.textContent =
        `${data.message} ${data.valid_rows} valid row(s), ${data.invalid_rows} row(s) need correction.`;
    } catch (error) {
      destinationRatesStatus.textContent = error.message || 'Rate-sheet preview failed.';
    } finally {
      submit.disabled = false;
    }
  });

  destinationRatesImport.addEventListener('click', async () => {
    if (!pendingRatePreview || pendingRatePreview.invalid_rows || !pendingRatePreview.valid_rows) return;
    destinationRatesImport.disabled = true;
    destinationRatesStatus.textContent = 'Applying reviewed destination rates...';
    try {
      const data = await apiRequest('http://localhost:5000/api/shipments/rates', {
        method: 'POST',
        body: JSON.stringify({
          source_filename: pendingRatePreview.source_filename,
          rows: pendingRatePreview.rows,
        }),
      });
      pendingRatePreview = null;
      destinationRatesImport.hidden = true;
      destinationRatesStatus.textContent = data.message;
      await loadDestinationRates();
    } catch (error) {
      destinationRatesStatus.textContent = error.message || 'Destination rates could not be applied.';
    } finally {
      destinationRatesImport.disabled = false;
    }
  });

  async function loadAdminOptions() {
    const data = await apiRequest('http://localhost:5000/api/auth/users');
    const users = data.users || [];
    clientAccounts = users.filter((user) => user.role === 'client' && user.account_status === 'active');
    const drivers = users.filter((user) =>
      user.role === 'driver'
      && user.account_status === 'active'
      && user.employment_status === 'ACTIVE',
    );
    const companySelect = document.getElementById('assignment-company');
    const driverSelect = document.getElementById('assignment-driver');
    const shipmentSelect = document.getElementById('assignment-shipment');
    const destinationInput = document.getElementById('assignment-destination');
    const accountSelect = document.getElementById('account-role-user');

    function setOptions(select, options, placeholder) {
      select.replaceChildren();
      const empty = document.createElement('option');
      empty.value = '';
      empty.textContent = placeholder;
      select.appendChild(empty);
      options.forEach(({ value, label }) => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = label;
        select.appendChild(option);
      });
    }

    setOptions(companySelect, clientAccounts.map((account) => ({
      value: String(account.id),
      label: `${account.company_name} — ${account.display_name || account.email}`,
    })), 'Select client account');
    setOptions(driverSelect, drivers.map((user) => ({
      value: String(user.id),
      label: `${user.display_name || user.driver_name || user.email} (${user.email})`,
    })), 'Select driver');
    setOptions(shipmentSelect, shipments.map((shipment) => ({
      value: shipment.tracking_number,
      label: `${shipment.tracking_number} — ${shipment.company_name || 'Unassigned'}`,
    })), 'Select shipment');
    const selectedShipment = shipments.find((item) => item.tracking_number === shipmentSelect.value);
    destinationInput.value = selectedShipment?.destination || '';
    setOptions(accountSelect, users.map((user) => ({
      value: String(user.id),
      label: `${user.email} — ${user.role}${user.account_status === 'pending' ? ' (pending)' : ''}`,
    })), 'Select account');

    const noAssignmentTargets = !clientAccounts.length || !drivers.length;
    assignmentForm.querySelector('button[type="submit"]').disabled = noAssignmentTargets || !shipments.length;
    if (noAssignmentTargets) {
      adminStatus.textContent = 'Create client accounts and provision driver accounts before assigning shipments.';
    } else {
      adminStatus.textContent = '';
    }
    await loadDestinationRates();
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const trackingNumber = trackingInput.value.trim();
    if (trackingNumber) loadShipment(trackingNumber);
  });

  assignmentForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    adminStatus.textContent = 'Saving shipment assignment...';
    try {
      const trackingNumber = document.getElementById('assignment-shipment').value;
      const clientAccount = clientAccounts.find(
        (account) => String(account.id) === document.getElementById('assignment-company').value,
      );
      if (!clientAccount) throw new Error('Select an active client account.');
      await apiRequest(`http://localhost:5000/api/shipments/${encodeURIComponent(trackingNumber)}/assignment`, {
        method: 'PATCH',
        body: JSON.stringify({
          client_user_id: clientAccount.id,
          company_name: clientAccount.company_name,
          driver_user_id: Number(document.getElementById('assignment-driver').value),
          destination: document.getElementById('assignment-destination').value.trim(),
        }),
      });
      adminStatus.textContent = 'Shipment assignment saved.';
      await loadAvailableShipments();
    } catch (error) {
      adminStatus.textContent = error.message || 'Could not save the shipment assignment.';
    }
  });

  document.getElementById('assignment-shipment').addEventListener('change', (event) => {
    const shipment = shipments.find((item) => item.tracking_number === event.target.value);
    document.getElementById('assignment-destination').value = shipment?.destination || '';
  });

  function updateDisplayNameRequirement() {
    const needsDisplayName = ['driver', 'mechanic', 'admin', 'hr'].includes(accountRole.value);
    const label = driverNameField.querySelector('label');
    label.textContent = accountRole.value === 'driver' ? 'Driver display name' : 'Employee display name';
    const displayNameInput = document.getElementById('account-driver-name');
    driverNameField.hidden = !needsDisplayName;
    displayNameInput.required = needsDisplayName;
  }

  accountRole.addEventListener('change', updateDisplayNameRequirement);
  updateDisplayNameRequirement();

  roleForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    adminStatus.textContent = 'Updating account access...';
    try {
      const userId = document.getElementById('account-role-user').value;
      const role = accountRole.value;
      const displayName = document.getElementById('account-driver-name').value.trim();
      await apiRequest(`http://localhost:5000/api/auth/users/${encodeURIComponent(userId)}/role`, {
        method: 'PATCH',
        body: JSON.stringify({ role, display_name: displayName }),
      });
      adminStatus.textContent = 'Account role updated. The user should sign in again to refresh their portal.';
      await loadAvailableShipments();
    } catch (error) {
      adminStatus.textContent = error.message || 'Could not update the account role.';
    }
  });

  uploadForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const trackingNumber = uploadShipmentSelect.value;
    const proofFiles = document.getElementById('proof-of-delivery-files').files;
    const deliveryFiles = document.getElementById('delivery-document-files').files;
    if (!trackingNumber || !proofFiles.length || !deliveryFiles.length) {
      uploadStatus.textContent = 'Select a shipment and upload both proof of delivery and delivery documents.';
      return;
    }
    const body = new FormData();
    Array.from(proofFiles).forEach((file) => body.append('proof_of_delivery', file));
    Array.from(deliveryFiles).forEach((file) => body.append('delivery_documents', file));
    const submit = uploadForm.querySelector('button[type="submit"]');
    submit.disabled = true;
    uploadStatus.textContent = 'Running OCR destination and delivery-number validation...';
    try {
      const data = await apiRequest(
        `http://localhost:5000/api/shipments/${encodeURIComponent(trackingNumber)}/documents`,
        { method: 'POST', body }
      );
      uploadStatus.textContent = data.message;
      uploadForm.reset();
      await loadAvailableShipments();
    } catch (error) {
      uploadStatus.textContent = error.message || 'Document validation failed.';
    } finally {
      submit.disabled = false;
    }
  });

  documentSelect.addEventListener('change', () => loadShipmentDocuments(documentSelect.value));
  goodsCompanySelect.addEventListener('change', refreshGoodsDeliveryOptions);
  goodsDeliverySelect.addEventListener('change', () => {
    renderGoodsDeliveryDetails();
    refreshPodSignaturePanel();
  });
  if (navLink) navLink.addEventListener('click', loadAvailableShipments);
  if (goodsNavLink) goodsNavLink.addEventListener('click', refreshGoodsPage);
  window.addEventListener('difan:session-ready', loadAvailableShipments);
});
