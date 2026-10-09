document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('shipment-track-form');
  if (!form) return;
  const apiRoot = window.DifanApp.apiBase;

  const trackingInput = document.getElementById('shipment-tracking-number');
  const submitButton = document.getElementById('shipment-track-submit');
  const statusMessage = document.getElementById('shipment-track-status');
  const details = document.getElementById('shipment-track-details');
  const accessibleList = document.getElementById('shipment-accessible-list');
  const navLink = document.querySelector('[data-target-tab="tracking"]');
  const adminTools = document.getElementById('tracking-admin-tools');
  const assignmentForm = document.getElementById('shipment-assignment-form');
  const autoMatchButton = document.getElementById('assignment-auto-match-button');
  const driverLoadBoardPanel = document.getElementById('driver-load-board-panel');
  const driverLoadBoardStatus = document.getElementById('driver-load-board-status');
  const driverLoadBoardList = document.getElementById('driver-load-board-list');
  const driverLoadBoardShareLocation = document.getElementById('driver-load-board-share-location');
  const driverLoadBoardRefresh = document.getElementById('driver-load-board-refresh');
  const driverBolScanButton = document.getElementById('driver-scan-bol-button');
  const driverBolCamera = document.getElementById('driver-bol-camera');
  const destinationRatesForm = document.getElementById('destination-rates-upload-form');
  const destinationRatesPreview = document.getElementById('destination-rates-preview');
  const destinationRatesImport = document.getElementById('destination-rates-import-button');
  const destinationRatesStatus = document.getElementById('destination-rates-status');
  const roleForm = document.getElementById('account-role-form');
  const adminStatus = document.getElementById('tracking-admin-status');
  const accountRole = document.getElementById('account-role-value');
  const roleStatus = document.getElementById('account-role-status');
  const driverNameField = document.getElementById('driver-name-field');
  const uploadForm = document.getElementById('shipment-document-upload-form');
  const operationalEvidenceForm = document.getElementById('shipment-operational-evidence-form');
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
  const claimPanel = document.getElementById('shipment-damage-claims-panel');
  const claimForm = document.getElementById('shipment-damage-claim-form');
  const claimLineItem = document.getElementById('damage-claim-line-item');
  const claimList = document.getElementById('shipment-damage-claim-list');
  const claimStatus = document.getElementById('damage-claim-status');
  const pdfPreviewDialog = document.getElementById('shipment-pdf-preview-modal');
  const pdfPreviewTitle = document.getElementById('shipment-pdf-preview-title');
  const pdfPreviewFrame = document.getElementById('shipment-pdf-preview-frame');
  const pdfPreviewDownload = document.getElementById('shipment-pdf-preview-download');
  const clientDelayPanel = document.getElementById('client-distribution-delay-panel');
  const clientDelayRows = document.getElementById('client-distribution-delay-rows');
  const clientDelayStatus = document.getElementById('client-distribution-delay-status');
  const geofencePanel = document.getElementById('shipment-geofence-panel');
  const geofenceForm = document.getElementById('shipment-geofence-form');
  const geofenceSelect = document.getElementById('geofence-shipment');
  const geofenceStatus = document.getElementById('shipment-geofence-status');
  let hasPodSignature = false;
  let shipments = [];
  let clientAccounts = [];
  let pendingRatePreview = null;
  const rateScope = document.getElementById('rate-sheet-scope');
  const rateClientId = () => (rateScope.value && rateScope.value !== 'standard' ? rateScope.value : '');
  let trackingPollTimer = null;
  let driverBolCameraStream = null;
  let driverBolScanActive = false;
  let pdfPreviewUrl = null;

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
    const isFormData = options.body instanceof FormData;
    const response = await fetch(url, {
      ...options,
      headers: {
        ...tokenHeaders(),
        ...(!isFormData && options.body ? { 'Content-Type': 'application/json' } : {}),
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

  async function fetchPdf(path, filename, statusElement) {
    const response = await fetch(window.DifanApp.apiUrl(path), { headers: tokenHeaders() });
    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.message || 'The PDF could not be retrieved.');
    }
    return response.blob();
  }

  async function previewPdf(path, filename, statusElement) {
    try {
      if (pdfPreviewUrl) URL.revokeObjectURL(pdfPreviewUrl);
      const previewPath = `${path}${path.includes('?') ? '&' : '?'}preview=1`;
      const blob = await fetchPdf(previewPath, filename, statusElement);
      pdfPreviewUrl = URL.createObjectURL(blob);
      pdfPreviewTitle.textContent = filename;
      pdfPreviewFrame.src = pdfPreviewUrl;
      pdfPreviewDownload.href = pdfPreviewUrl;
      pdfPreviewDownload.download = filename;
      pdfPreviewDialog.showModal();
      if (statusElement) statusElement.textContent = `${filename} opened for preview.`;
    } catch (error) {
      if (statusElement) statusElement.textContent = error.message || 'The PDF could not be previewed.';
      else window.DifanApp.showToast(error.message || 'The PDF could not be previewed.', 'error');
    }
  }

  async function downloadPdf(path, filename, statusElement) {
    try {
      const blob = await fetchPdf(path, filename, statusElement);
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = objectUrl;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
      if (statusElement) statusElement.textContent = `${filename} downloaded. A copy is also saved to this shipment in the app.`;
    } catch (error) {
      if (statusElement) statusElement.textContent = error.message || 'The PDF could not be downloaded.';
      else window.DifanApp.showToast(error.message || 'The PDF could not be downloaded.', 'error');
    }
  }

  document.getElementById('shipment-pdf-preview-close').addEventListener('click', () => {
    pdfPreviewDialog.close();
  });
  pdfPreviewDialog.addEventListener('close', () => {
    pdfPreviewFrame.removeAttribute('src');
    if (pdfPreviewUrl) URL.revokeObjectURL(pdfPreviewUrl);
    pdfPreviewUrl = null;
  });

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
      const detention = document.createElement('p');
      detention.textContent = `Agreed detention rate: ${window.DifanApp.formatCurrency(shipment.detention_rate_kes_per_hour || 0)}/hour · accrued before VAT: ${window.DifanApp.formatCurrency(shipment.detention_charges_kes || 0)} · detention VAT: ${window.DifanApp.formatCurrency(shipment.detention_vat_kes || 0)} · invoice total: ${window.DifanApp.formatCurrency(shipment.invoice_total_kes || shipment.quoted_amount_kes || 0)}`;
      details.appendChild(detention);
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

  function billOfLadingPath(shipment) {
    return `/api/shipments/${encodeURIComponent(shipment.tracking_number)}/bill-of-lading`;
  }

  function downloadBillOfLading(shipment) {
    const filename = `${shipment.tracking_number}-bill-of-lading.pdf`;
    void downloadPdf(billOfLadingPath(shipment), filename, statusMessage);
  }

  function previewBillOfLading(shipment) {
    const filename = `${shipment.tracking_number}-bill-of-lading.pdf`;
    void previewPdf(billOfLadingPath(shipment), filename, statusMessage);
  }

  async function createCustomerTrackingLink(shipment, sendEmail = false) {
    setStatus(sendEmail ? 'Emailing secure tracking link to the receiver...' : 'Creating a secure tracking link...');
    try {
      const data = await apiRequest(
        `${apiRoot}/api/shipments/${encodeURIComponent(shipment.tracking_number)}/tracking-link`,
        { method: 'POST', body: JSON.stringify({ send_email: sendEmail }) },
      );
      if (data.notification?.status === 'failed' || data.notification?.status === 'not_sent') {
        setStatus(`${data.message} Link: ${data.tracking_url}`, 'error');
        return;
      }
      if (!sendEmail) {
        try {
          await navigator.clipboard.writeText(data.tracking_url);
          setStatus(`Secure tracking link copied. It expires ${new Date(data.expires_at).toLocaleString()}.`, 'success');
        } catch {
          const input = document.createElement('textarea');
          input.value = data.tracking_url;
          input.setAttribute('readonly', '');
          input.style.position = 'fixed';
          input.style.opacity = '0';
          document.body.appendChild(input);
          input.select();
          const copied = document.execCommand('copy');
          input.remove();
          if (!copied) {
            setStatus(`Clipboard access is unavailable. Copy this secure tracking link: ${data.tracking_url}`, 'error');
            return;
          }
          setStatus(`Secure tracking link copied. It expires ${new Date(data.expires_at).toLocaleString()}.`, 'success');
        }
      } else {
        setStatus(data.message, 'success');
      }
    } catch (error) {
      setStatus(error.message || 'Secure tracking link could not be created or delivered.', 'error');
    }
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
      const tripActions = document.createElement('div');
      tripActions.className = 'workflow-actions';
      const bolPreviewButton = document.createElement('button');
      bolPreviewButton.type = 'button';
      bolPreviewButton.className = 'btn btn-secondary';
      bolPreviewButton.textContent = 'Preview trip BOL + QR';
      bolPreviewButton.addEventListener('click', () => previewBillOfLading(shipment));
      const bolButton = document.createElement('button');
      bolButton.type = 'button';
      bolButton.className = 'btn btn-secondary';
      bolButton.textContent = 'Download trip BOL + QR';
      bolButton.addEventListener('click', () => downloadBillOfLading(shipment));
      const linkButton = document.createElement('button');
      linkButton.type = 'button';
      linkButton.className = 'btn btn-secondary';
      linkButton.textContent = 'Copy customer tracking link';
      linkButton.addEventListener('click', () => createCustomerTrackingLink(shipment));
      tripActions.append(bolPreviewButton, bolButton, linkButton);
      if (shipment.end_customer_email) {
        const emailButton = document.createElement('button');
        emailButton.type = 'button';
        emailButton.className = 'btn btn-secondary';
        emailButton.textContent = 'Email customer tracking link';
        emailButton.addEventListener('click', () => createCustomerTrackingLink(shipment, true));
        tripActions.appendChild(emailButton);
      }
      card.append(info, trackButton, tripActions);
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
        const events = shipment.geofence_events || [];
        if (events.length) {
          const visitHistory = document.createElement('p');
          visitHistory.textContent = `Geofence history: ${events.map((event) =>
            `${event.facility_name} ${event.event_type.toLowerCase()} ${new Date(event.recorded_at).toLocaleString()}`
          ).join(' · ')}`;
          goodsDeliveryDetails.appendChild(visitHistory);
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
            const updated = await apiRequest(`${apiRoot}/api/shipments/${encodeURIComponent(shipment.tracking_number)}/status`, {
              method: 'PATCH',
              body: JSON.stringify(statusUpdate),
            });
            if (updated.automated_warnings?.length) {
              setStatus(
                `Delivery recorded. ${updated.automated_warnings.length} automated warning(s) are available in your HR records for rebuttal.`,
                'error',
              );
            } else if (updated.customer_notification?.status !== 'sent' && canStartTrip) {
              setStatus(`Trip started. ${updated.customer_notification?.message || 'Customer tracking notification was not sent.'}`, 'warning');
            } else {
              setStatus('Shipment status updated successfully.');
            }
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
    const detention = document.createElement('p');
    detention.textContent = `Agreed detention rate: ${window.DifanApp.formatCurrency(shipment.detention_rate_kes_per_hour || 0)}/hour · accrued before VAT: ${window.DifanApp.formatCurrency(shipment.detention_charges_kes || 0)} · detention VAT: ${window.DifanApp.formatCurrency(shipment.detention_vat_kes || 0)} · invoice total: ${window.DifanApp.formatCurrency(shipment.invoice_total_kes || shipment.quoted_amount_kes || 0)}`;
    goodsDeliveryDetails.appendChild(detention);
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
      document.getElementById('client-pod-preview').hidden = true;
      return;
    }

    podSignatureSummary.textContent =
      `${shipment.tracking_number} · ${shipment.cargo_type}, ${shipment.tonnage} tonnes · ` +
      `${shipment.origin} to ${shipment.destination}`;
    if (shipment.pod_signed_at) {
      podSignatureForm.hidden = true;
      podDownloadButton.hidden = false;
      document.getElementById('client-pod-preview').hidden = false;
      podSignatureStatus.textContent =
        `Signed by ${shipment.pod_signed_by} on ${new Date(shipment.pod_signed_at).toLocaleString()}.`;
    } else if (shipment.status === 'DELIVERED') {
      podSignatureForm.hidden = false;
      podDownloadButton.hidden = true;
      document.getElementById('client-pod-preview').hidden = true;
      podSignatureStatus.textContent = 'Confirm the cargo was received, then sign below.';
      clearPodSignature();
    } else {
      podSignatureForm.hidden = true;
      podDownloadButton.hidden = true;
      document.getElementById('client-pod-preview').hidden = true;
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
    void downloadPdf(
      shipment.proof_of_delivery_download_url,
      `${shipment.tracking_number}-signed-proof-of-delivery.pdf`,
      podSignatureStatus,
    );
  });

  document.getElementById('client-pod-preview').addEventListener('click', () => {
    const shipment = shipments.find((item) => item.tracking_number === goodsDeliverySelect.value);
    if (!shipment?.proof_of_delivery_download_url) return;
    void previewPdf(
      shipment.proof_of_delivery_download_url,
      `${shipment.tracking_number}-signed-proof-of-delivery.pdf`,
      podSignatureStatus,
    );
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
        `${apiRoot}/api/shipments/${encodeURIComponent(shipment.tracking_number)}/proof-of-delivery/sign`,
        {
          method: 'POST',
          body: JSON.stringify({
            signer_name: document.getElementById('client-pod-signer-name').value.trim(),
            signature_png: podSignatureCanvas.toDataURL('image/png'),
          }),
        },
      );
      podSignatureStatus.textContent = [
        data.invoice_created ? `${data.message} Your delivery invoice is now available in Finance.` : data.message,
        data.email_delivery?.message,
      ].filter(Boolean).join(' ');
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
    refreshDamageClaimPanel();
  }

  async function downloadClaimEvidence(record) {
    try {
      const response = await fetch(window.DifanApp.apiUrl(record.download_url), {
        headers: tokenHeaders(),
      });
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.message || 'Claim evidence could not be downloaded.');
      }
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = record.filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      claimStatus.textContent = error.message || 'Claim evidence could not be downloaded.';
    }
  }

  async function loadDamageClaims(shipment) {
    claimList.replaceChildren();
    if (!shipment) return;
    try {
      const data = await apiRequest(
        `${apiRoot}/api/shipments/${encodeURIComponent(shipment.tracking_number)}/claims`,
      );
      if (!data.claims.length) {
        const empty = document.createElement('p');
        empty.className = 'workflow-empty';
        empty.textContent = 'No damage claims have been filed for this shipment.';
        claimList.appendChild(empty);
        return;
      }
      data.claims.forEach((claim) => {
        const card = document.createElement('article');
        card.className = 'workflow-card';
        const heading = document.createElement('h3');
        heading.textContent = `${claim.line_item_description} · Filed by ${claim.filed_by}`;
        card.appendChild(heading);
        const details = document.createElement('p');
        details.textContent = `${claim.details} · ${new Date(claim.filed_at).toLocaleString()}`;
        card.appendChild(details);
        claim.evidence.forEach((evidence) => {
          const row = document.createElement('p');
          row.textContent = `${evidence.filename} · ${new Date(evidence.uploaded_at).toLocaleString()} · SHA-256 ${evidence.sha256}`;
          const download = document.createElement('button');
          download.type = 'button';
          download.className = 'btn btn-secondary';
          download.textContent = 'Download photo';
          download.addEventListener('click', () => downloadClaimEvidence(evidence));
          row.appendChild(document.createTextNode(' '));
          row.appendChild(download);
          card.appendChild(row);
        });
        const evidenceForm = document.createElement('form');
        evidenceForm.className = 'workflow-form';
        const photoField = document.createElement('input');
        photoField.type = 'file';
        photoField.accept = 'image/jpeg,image/png,image/webp';
        photoField.required = true;
        photoField.setAttribute('aria-label', 'Add supporting damage photo');
        const submit = document.createElement('button');
        submit.className = 'btn btn-secondary';
        submit.type = 'submit';
        submit.textContent = 'Add supporting photo';
        evidenceForm.append(photoField, submit);
        evidenceForm.addEventListener('submit', async (event) => {
          event.preventDefault();
          const body = new FormData();
          body.append('photo', photoField.files[0]);
          submit.disabled = true;
          try {
            await apiRequest(
              `${apiRoot}/api/shipments/claims/${encodeURIComponent(claim.id)}/evidence`,
              { method: 'POST', body },
            );
            await loadDamageClaims(shipment);
            claimStatus.textContent = 'Supporting damage photo added to the shared claim.';
          } catch (error) {
            claimStatus.textContent = error.message || 'Supporting photo could not be uploaded.';
            submit.disabled = false;
          }
        });
        card.appendChild(evidenceForm);
        claimList.appendChild(card);
      });
    } catch (error) {
      const message = document.createElement('p');
      message.className = 'workflow-empty';
      message.textContent = error.message || 'Damage claims could not be loaded.';
      claimList.appendChild(message);
    }
  }

  function refreshDamageClaimPanel() {
    const userRole = window.DifanApp?.state?.currentUser?.role;
    const allowedRole = userRole === 'client' || userRole === 'driver';
    const shipment = shipments.find((item) => item.tracking_number === goodsDeliverySelect.value);
    claimPanel.hidden = !allowedRole || !shipment
      || !['IN_TRANSIT', 'BREAKDOWN', 'DELIVERED'].includes(shipment.status);
    claimForm.hidden = !allowedRole || !shipment
      || !['IN_TRANSIT', 'BREAKDOWN', 'DELIVERED'].includes(shipment.status);
    if (!shipment || !allowedRole) {
      claimList.replaceChildren();
      return;
    }
    claimLineItem.replaceChildren(new Option('Choose a cargo line item (or describe it below)', ''));
    (shipment.deliveries || []).forEach((delivery) => {
      const option = new Option(
        `${delivery.delivery_number} · ${delivery.goods_description || delivery.destination || 'Delivery item'}`,
        String(delivery.id),
      );
      claimLineItem.add(option);
    });
    void loadDamageClaims(shipment);
  }

  function formatStamp(value) {
    return value ? new Date(value).toLocaleString() : 'Pending';
  }

  async function downloadDocument(documentRecord) {
    try {
      const response = await fetch(window.DifanApp.apiUrl(documentRecord.download_url), {
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
        `${apiRoot}/api/shipments/${encodeURIComponent(trackingNumber)}/documents`
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
        const documentLabels = {
          trip_bol: 'Trip bill of lading',
          signed_pod: 'Signed proof of delivery',
          proof_of_delivery: 'Proof of delivery',
        };
        type.textContent = documentLabels[record.document_type] || 'Delivery document';
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
        download.textContent = 'Download document';
        download.addEventListener('click', () => downloadDocument(record));
        card.appendChild(download);
        if (record.mime_type === 'application/pdf') {
          const preview = document.createElement('button');
          preview.type = 'button';
          preview.className = 'btn btn-secondary';
          preview.textContent = 'Preview PDF';
          preview.addEventListener('click', () => {
            void previewPdf(record.download_url, record.filename, uploadStatus);
          });
          card.appendChild(preview);
        }
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

  async function refreshClientDistributionDelays() {
    clientDelayRows.replaceChildren();
    try {
      const data = await apiRequest(
        window.DifanApp.apiUrl('/api/portal/workforce/client-distribution-center-delays'),
      );
      if (!data.facilities.length) {
        clientDelayStatus.textContent = 'No pickup-site geofence visits have been recorded for your shipments yet.';
        return;
      }
      clientDelayStatus.textContent = 'Only delay events for your shipments are included.';
      data.facilities.forEach((facility) => {
        const row = document.createElement('tr');
        [
          facility.facility_name,
          String(facility.completed_visits),
          facility.average_delay_hours.toFixed(2),
          facility.longest_delay_hours.toFixed(2),
        ].forEach((value) => {
          const cell = document.createElement('td');
          cell.textContent = value;
          row.appendChild(cell);
        });
        clientDelayRows.appendChild(row);
      });
    } catch (error) {
      clientDelayStatus.textContent = error.message || 'Your distribution-center insights could not be loaded.';
    }
  }

  async function refreshGoodsPage() {
    const role = window.DifanApp?.state?.currentUser?.role;
    const isDriver = role === 'driver';
    const isAdminOrHr = ['admin', 'hr', 'boss'].includes(role);
    const canDownload = role === 'client' || isAdminOrHr;
    clientDelayPanel.hidden = role !== 'client';
    uploadPanel.hidden = !isDriver;
    documentPanel.hidden = !canDownload;
    document.getElementById('goods-delivery-browser').hidden =
      !['driver', 'client', 'admin', 'hr'].includes(role);
    try {
      const data = await apiRequest(`${apiRoot}/api/shipments`);
      shipments = data.shipments || [];
      if (role === 'client') await refreshClientDistributionDelays();
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
      const data = await apiRequest(`${apiRoot}/api/shipments`);
      shipments = data.shipments || [];
      const user = window.DifanApp?.state?.currentUser;
      const isAdminOrHr = ['admin', 'hr', 'boss'].includes(user?.role);
      const isDriver = user?.role === 'driver';
      driverLoadBoardPanel.hidden = !isDriver;
      if (user?.role === 'driver') {
        const clientData = await apiRequest(`${apiRoot}/api/shipments/clients`);
        clientAccounts = clientData.clients || [];
      }
      renderAccessibleShipments();
      setStatus(`${shipments.length} shipment${shipments.length === 1 ? '' : 's'} available to your account.`, 'success');

      adminTools.hidden = !isAdminOrHr;
      geofencePanel.hidden = !isDriver;
      if (isDriver) {
        replaceSelectOptions(
          geofenceSelect,
          shipments.filter((shipment) => [
            'ASSIGNED', 'AWAITING_DISPATCH', 'IN_TRANSIT', 'BREAKDOWN', 'DELIVERED',
          ].includes(shipment.status)),
          'Select an assigned shipment',
        );
      }
      if (isAdminOrHr) await loadAdminOptions();
      if (isDriver) await loadDriverLoadBoard();
      if (user?.role === 'driver' || user?.role === 'client' || isAdminOrHr) {
        await refreshGoodsPage();
      }
    } catch (error) {
      shipments = [];
      renderAccessibleShipments();
      adminTools.hidden = true;
      geofencePanel.hidden = true;
      driverLoadBoardPanel.hidden = true;
      setStatus(error.message || 'Unable to load shipments for this account.', 'error');
    }
  }

  async function loadDriverLoadBoard() {
    driverLoadBoardList.replaceChildren();
    driverLoadBoardStatus.textContent = 'Finding loads compatible with your assigned vehicle...';
    try {
      const data = await apiRequest(`${apiRoot}/api/shipments/driver-load-board`);
      driverLoadBoardStatus.textContent = data.message;
      if (!data.loads?.length) {
        const empty = document.createElement('p');
        empty.className = 'workflow-empty';
        empty.textContent = data.eligible
          ? 'No unassigned loads match your assigned truck at the moment.'
          : data.message;
        driverLoadBoardList.appendChild(empty);
        return;
      }
      data.loads.forEach((load) => {
        const card = document.createElement('article');
        card.className = 'shipment-access-card';
        const information = document.createElement('div');
        const title = document.createElement('strong');
        title.textContent = `${load.tracking_number} · ${load.cargo_type} · ${load.tonnage} tonnes`;
        information.appendChild(title);
        const route = document.createElement('p');
        route.textContent = `${load.origin} → ${load.destination}`;
        information.appendChild(route);
        const pickup = document.createElement('p');
        pickup.textContent = `Pickup: ${load.pickup_address || load.origin} · ${load.pickup_at ? new Date(load.pickup_at).toLocaleString() : 'Schedule pending'}`;
        information.appendChild(pickup);
        const proximity = document.createElement('p');
        proximity.textContent = load.distance_to_pickup_km === null
          ? 'Distance unavailable; share fresh GPS for proximity ordering.'
          : `${load.distance_to_pickup_km} km from your last shared GPS position`;
        information.appendChild(proximity);
        if (load.backhaul) {
          const backhaul = document.createElement('span');
          backhaul.className = 'badge badge-info';
          backhaul.textContent = 'Backhaul opportunity';
          information.appendChild(backhaul);
        }
        const accept = document.createElement('button');
        accept.type = 'button';
        accept.className = 'btn btn-primary';
        accept.textContent = 'Accept compatible load';
        accept.addEventListener('click', async () => {
          accept.disabled = true;
          driverLoadBoardStatus.textContent = `Accepting ${load.tracking_number}...`;
          try {
            const accepted = await apiRequest(
              `${apiRoot}/api/shipments/driver-load-board/${encodeURIComponent(load.tracking_number)}/accept`,
              { method: 'POST', body: JSON.stringify({}) },
            );
            driverLoadBoardStatus.textContent = accepted.message;
            await loadAvailableShipments();
          } catch (error) {
            driverLoadBoardStatus.textContent = error.message || 'This load could not be accepted.';
            accept.disabled = false;
          }
        });
        card.append(information, accept);
        driverLoadBoardList.appendChild(card);
      });
    } catch (error) {
      driverLoadBoardStatus.textContent = error.message || 'Compatible loads could not be loaded.';
    }
  }

  function stopDriverBolScan() {
    driverBolScanActive = false;
    if (driverBolCameraStream) {
      driverBolCameraStream.getTracks().forEach((track) => track.stop());
      driverBolCameraStream = null;
    }
    driverBolCamera.srcObject = null;
    driverBolCamera.hidden = true;
    driverBolScanButton.textContent = 'Scan assigned trip BOL QR';
  }

  async function startTripFromScannedBol(value) {
    let token;
    try {
      const scannedUrl = new URL(value);
      if (
        scannedUrl.origin !== window.location.origin
        || scannedUrl.pathname !== '/tracking.html'
      ) {
        throw new Error('This QR code is not a Difan shipment BOL.');
      }
      token = scannedUrl.searchParams.get('token');
      if (!token) throw new Error('This BOL QR does not contain a secure tracking token.');
    } catch (error) {
      throw new Error(error.message || 'The scanned QR code is not a valid Difan shipment link.');
    }

    const publicTracking = await apiRequest(
      `${apiRoot}/api/shipments/public-tracking/${encodeURIComponent(token)}`,
    );
    const trackingNumber = publicTracking.tracking.tracking_number;
    const shipment = shipments.find((item) => item.tracking_number === trackingNumber);
    if (!shipment) {
      throw new Error('This shipment is not assigned to your driver account.');
    }
    if (!['ASSIGNED', 'AWAITING_DISPATCH'].includes(shipment.status)) {
      throw new Error(`Shipment ${trackingNumber} cannot start from status ${shipment.status.replaceAll('_', ' ')}.`);
    }
    const started = await apiRequest(
      `${apiRoot}/api/shipments/${encodeURIComponent(trackingNumber)}/status`,
      { method: 'PATCH', body: JSON.stringify({ status: 'IN_TRANSIT' }) },
    );
    document.dispatchEvent(new CustomEvent('shipment:loaded', { detail: started.shipment }));
    driverLoadBoardStatus.textContent = started.customer_notification?.message
      ? `Trip ${trackingNumber} started. ${started.customer_notification.message}`
      : `Trip ${trackingNumber} started successfully.`;
    await loadAvailableShipments();
  }

  driverBolScanButton.addEventListener('click', async () => {
    if (driverBolScanActive) {
      stopDriverBolScan();
      driverLoadBoardStatus.textContent = 'BOL camera scan cancelled.';
      return;
    }
    if (!('BarcodeDetector' in window) || !navigator.mediaDevices?.getUserMedia) {
      driverLoadBoardStatus.textContent =
        'QR camera scanning is not supported by this browser. Use the assigned shipment card to start the trip.';
      return;
    }
    driverBolScanButton.disabled = true;
    driverLoadBoardStatus.textContent = 'Requesting camera permission for BOL scanning...';
    try {
      const detector = new BarcodeDetector({ formats: ['qr_code'] });
      driverBolCameraStream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: { ideal: 'environment' } },
      });
      driverBolCamera.srcObject = driverBolCameraStream;
      driverBolCamera.hidden = false;
      await driverBolCamera.play();
      driverBolScanActive = true;
      driverBolScanButton.textContent = 'Stop BOL scan';
      driverLoadBoardStatus.textContent = 'Point the camera at the assigned trip BOL QR code.';

      const scanFrame = async () => {
        if (!driverBolScanActive) return;
        try {
          const codes = await detector.detect(driverBolCamera);
          const scannedValue = codes.find((code) => code.rawValue)?.rawValue;
          if (scannedValue) {
            stopDriverBolScan();
            driverLoadBoardStatus.textContent = 'BOL QR verified. Starting the assigned trip...';
            await startTripFromScannedBol(scannedValue);
            return;
          }
          window.requestAnimationFrame(scanFrame);
        } catch (error) {
          stopDriverBolScan();
          driverLoadBoardStatus.textContent = error.message || 'The BOL QR could not be scanned.';
        }
      };
      window.requestAnimationFrame(scanFrame);
    } catch (error) {
      stopDriverBolScan();
      driverLoadBoardStatus.textContent =
        error.name === 'NotAllowedError'
          ? 'Camera permission was denied. Use the assigned shipment card to start the trip.'
          : error.message || 'Camera access failed. Use the assigned shipment card to start the trip.';
    } finally {
      driverBolScanButton.disabled = false;
    }
  });

  driverLoadBoardRefresh.addEventListener('click', () => {
    void loadDriverLoadBoard();
  });
  driverLoadBoardShareLocation.addEventListener('click', async () => {
    if (!navigator.geolocation) {
      driverLoadBoardStatus.textContent = 'This browser does not provide GPS. Refresh still shows compatible loads without proximity sorting.';
      return;
    }
    driverLoadBoardShareLocation.disabled = true;
    driverLoadBoardStatus.textContent = 'Requesting your current location...';
    try {
      const position = await new Promise((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(resolve, reject, {
          enableHighAccuracy: true,
          maximumAge: 60_000,
          timeout: 15_000,
        });
      });
      const saved = await apiRequest(`${apiRoot}/api/shipments/driver-location`, {
        method: 'POST',
        body: JSON.stringify({
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
          accuracy_m: position.coords.accuracy,
        }),
      });
      driverLoadBoardStatus.textContent = saved.message;
      await loadDriverLoadBoard();
    } catch (error) {
      driverLoadBoardStatus.textContent = error.message || 'Location was not saved. Check GPS permission and try again.';
    } finally {
      driverLoadBoardShareLocation.disabled = false;
    }
  });

  async function loadShipment(trackingNumber) {
    if (!trackingNumber) return;
    if (trackingPollTimer) clearInterval(trackingPollTimer);
    submitButton.disabled = true;
    details.hidden = true;
    setStatus(`Looking up ${trackingNumber}...`);

    try {
      const data = await apiRequest(
        `${apiRoot}/api/shipments/track/${encodeURIComponent(trackingNumber)}`
      );
      const shipment = data.shipment;
      details.hidden = false;
      document.dispatchEvent(new CustomEvent('shipment:loaded', { detail: shipment }));
      setStatus(`Shipment ${shipment.tracking_number} found for ${shipment.company_name}.`, 'success');
      trackingPollTimer = setInterval(async () => {
        try {
          const latest = await apiRequest(
            `${apiRoot}/api/shipments/track/${encodeURIComponent(shipment.tracking_number)}`
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
      const data = await apiRequest(`${apiRoot}/api/shipments/rates${rateClientId() ? `?client_id=${encodeURIComponent(rateClientId())}` : ''}`);
      if (!data.rates.length) {
        const empty = document.createElement('p');
        empty.className = 'workflow-empty';
        empty.textContent = rateClientId() ? 'No rates have been uploaded for this client yet.' : 'No standard rates are applied. Quotes use the standard estimate.';
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

  rateScope.addEventListener('change', () => {
    pendingRatePreview = null;
    destinationRatesImport.hidden = true;
    destinationRatesPreview.replaceChildren();
    destinationRatesStatus.textContent = '';
    loadDestinationRates();
  });

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
      const response = await fetch(window.DifanApp.apiUrl('/api/shipments/rates/preview'), {
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
      const data = await apiRequest(`${apiRoot}/api/shipments/rates`, {
        method: 'POST',
        body: JSON.stringify({
          source_filename: pendingRatePreview.source_filename,
          client_id: rateClientId() || null,
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
    const [data, dispatchEligibility] = await Promise.all([
      apiRequest(`${apiRoot}/api/auth/users`),
      apiRequest(`${apiRoot}/api/fleet/dispatch-eligibility`),
    ]);
    const users = data.users || [];
    clientAccounts = users.filter((user) => user.role === 'client' && user.account_status === 'active');
    const blockedDriverIds = new Set(
      (dispatchEligibility.blocked_drivers || []).map((driver) => driver.driver_id),
    );
    const drivers = users.filter((user) =>
      user.role === 'driver'
      && user.account_status === 'active'
      && user.employment_status === 'ACTIVE'
      && !blockedDriverIds.has(user.id),
    );
    const companySelect = document.getElementById('assignment-company');
    const driverSelect = document.getElementById('assignment-driver');
    const shipmentSelect = document.getElementById('assignment-shipment');
    const destinationInput = document.getElementById('assignment-destination');
    const accountSelect = document.getElementById('account-role-user');
    const previousSelection = {
      company: companySelect.value,
      driver: driverSelect.value,
      shipment: shipmentSelect.value,
    };

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

    const previousRateScope = rateScope.value;
    rateScope.replaceChildren(new Option('Standard rates (quote page)', 'standard'));
    clientAccounts.forEach((account) => {
      rateScope.appendChild(new Option(`${account.company_name} — ${account.display_name || account.email}`, String(account.id)));
    });
    if ([...rateScope.options].some((option) => option.value === previousRateScope)) rateScope.value = previousRateScope;

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
    if (shipments.some((shipment) => shipment.tracking_number === previousSelection.shipment)) {
      shipmentSelect.value = previousSelection.shipment;
    }
    if (clientAccounts.some((account) => String(account.id) === previousSelection.company)) {
      companySelect.value = previousSelection.company;
    }
    if (drivers.some((driver) => String(driver.id) === previousSelection.driver)) {
      driverSelect.value = previousSelection.driver;
    }
    const selectedShipment = shipments.find((item) => item.tracking_number === shipmentSelect.value);
    if (selectedShipment) destinationInput.value = selectedShipment.destination || '';
    setOptions(accountSelect, users.map((user) => ({
      value: String(user.id),
      label: `${user.email} — ${user.role}${user.account_status === 'pending' ? ' (pending)' : ''}`,
    })), 'Select account');

    const noAssignmentTargets = !clientAccounts.length || !drivers.length;
    assignmentForm.querySelector('button[type="submit"]').disabled = noAssignmentTargets || !shipments.length;
    if (noAssignmentTargets) {
      adminStatus.textContent = drivers.length
        ? 'Create client accounts before assigning shipments.'
        : dispatchEligibility.blocked_drivers?.length
          ? 'No drivers are dispatch-eligible. Review expired or missing vehicle certificates in Fleet Operations.'
          : 'Create client accounts and provision active driver accounts before assigning shipments.';
    } else {
      adminStatus.textContent = adminStatus.dataset.assignmentResult || '';
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
    const submit = assignmentForm.querySelector('button[type="submit"]');
    submit.disabled = true;
    adminStatus.textContent = 'Saving shipment assignment...';
    try {
      const trackingNumber = document.getElementById('assignment-shipment').value;
      if (!trackingNumber) throw new Error('Select a shipment to assign.');
      const clientAccount = clientAccounts.find(
        (account) => String(account.id) === document.getElementById('assignment-company').value,
      );
      if (!clientAccount) throw new Error('Select an active client account.');
      const driverId = document.getElementById('assignment-driver').value;
      if (!driverId) throw new Error('Select an active, dispatch-eligible driver.');
      const assigned = await apiRequest(`${apiRoot}/api/shipments/${encodeURIComponent(trackingNumber)}/assignment`, {
        method: 'PATCH',
        body: JSON.stringify({
          client_user_id: clientAccount.id,
          company_name: clientAccount.company_name,
          driver_user_id: Number(driverId),
          destination: document.getElementById('assignment-destination').value.trim(),
          detention_rate_kes_per_hour: Number(document.getElementById('assignment-detention-rate').value),
        }),
      });
      const resultMessage =
        `Shipment ${assigned.shipment.tracking_number} assigned to ${assigned.shipment.assigned_driver_name}. ` +
        `${assigned.driver_notification?.message || 'Driver notification status is unavailable.'}`;
      adminStatus.dataset.assignmentResult = resultMessage;
      await loadAvailableShipments();
      adminStatus.textContent = resultMessage;
    } catch (error) {
      adminStatus.textContent = error.message || 'Could not save the shipment assignment.';
    } finally {
      submit.disabled = false;
    }
  });

  autoMatchButton.addEventListener('click', async () => {
    const trackingNumber = document.getElementById('assignment-shipment').value;
    if (!trackingNumber) {
      adminStatus.textContent = 'Select a shipment before auto-matching a driver.';
      return;
    }
    autoMatchButton.disabled = true;
    adminStatus.textContent = 'Finding the nearest compatible driver with a fresh shared GPS position...';
    try {
      const data = await apiRequest(
        `${apiRoot}/api/shipments/${encodeURIComponent(trackingNumber)}/auto-assignment`,
        { method: 'POST', body: JSON.stringify({}) },
      );
      const resultMessage =
        `${data.driver.name} auto-assigned to ${data.shipment.tracking_number} ` +
        `from ${data.distance_to_pickup_km} km away. ` +
        `${data.driver_notification?.message || 'Driver notification status unavailable.'}`;
      adminStatus.dataset.assignmentResult = resultMessage;
      await loadAvailableShipments();
      const driverSelect = document.getElementById('assignment-driver');
      if (Array.from(driverSelect.options).some((option) => option.value === String(data.driver.id))) {
        driverSelect.value = String(data.driver.id);
      }
      adminStatus.textContent = resultMessage;
    } catch (error) {
      adminStatus.textContent = error.message || 'No eligible nearby driver could be assigned.';
    } finally {
      autoMatchButton.disabled = false;
    }
  });

  document.getElementById('assignment-shipment').addEventListener('change', (event) => {
    delete adminStatus.dataset.assignmentResult;
    adminStatus.textContent = '';
    const shipment = shipments.find((item) => item.tracking_number === event.target.value);
    document.getElementById('assignment-destination').value = shipment?.destination || '';
    document.getElementById('assignment-detention-rate').value =
      String(shipment?.detention_rate_kes_per_hour || 0);
  });
  ['assignment-company', 'assignment-driver', 'assignment-destination', 'assignment-detention-rate']
    .forEach((id) => {
      document.getElementById(id).addEventListener('input', () => {
        delete adminStatus.dataset.assignmentResult;
        adminStatus.textContent = '';
      });
      document.getElementById(id).addEventListener('change', () => {
        delete adminStatus.dataset.assignmentResult;
        adminStatus.textContent = '';
      });
    });

  claimForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const shipment = shipments.find((item) => item.tracking_number === goodsDeliverySelect.value);
    const photo = document.getElementById('damage-claim-photo').files[0];
    if (!shipment || !photo) {
      claimStatus.textContent = 'Select a shipment and attach a damage photo.';
      return;
    }
    const body = new FormData();
    body.append('line_item_id', claimLineItem.value);
    body.append('line_item_description', document.getElementById('damage-claim-item-description').value.trim());
    body.append('details', document.getElementById('damage-claim-details').value.trim());
    body.append('photo', photo);
    const submit = claimForm.querySelector('button[type="submit"]');
    submit.disabled = true;
    claimStatus.textContent = 'Filing damage claim and securely storing photo evidence...';
    try {
      await apiRequest(
        `${apiRoot}/api/shipments/${encodeURIComponent(shipment.tracking_number)}/claims`,
        { method: 'POST', body },
      );
      claimForm.reset();
      claimStatus.textContent = 'Damage claim filed. The shipper and assigned driver can now review and add evidence.';
      await loadDamageClaims(shipment);
    } catch (error) {
      claimStatus.textContent = error.message || 'Damage claim could not be filed.';
    } finally {
      submit.disabled = false;
    }
  });

  geofenceForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const shipment = shipments.find((item) => item.tracking_number === geofenceSelect.value);
    if (!shipment) {
      geofenceStatus.textContent = 'Select an assigned shipment.';
      return;
    }
    if (!navigator.geolocation) {
      geofenceStatus.textContent = 'This browser does not provide GPS location. Use a supported device and browser.';
      return;
    }
    const submit = document.getElementById('geofence-submit');
    submit.disabled = true;
    geofenceStatus.textContent = 'Requesting device location...';
    navigator.geolocation.getCurrentPosition(async (position) => {
      try {
        const data = await apiRequest(
          `${apiRoot}/api/shipments/${encodeURIComponent(shipment.tracking_number)}/geofence-events`,
          {
            method: 'POST',
            body: JSON.stringify({
              site_type: document.getElementById('geofence-site').value,
              event_type: document.getElementById('geofence-event').value,
              latitude: position.coords.latitude,
              longitude: position.coords.longitude,
              accuracy_m: position.coords.accuracy,
            }),
          },
        );
        geofenceStatus.textContent = `${data.message} Detention accrued: ${window.DifanApp.formatCurrency(data.detention_charges_kes)}.`;
        await loadAvailableShipments();
      } catch (error) {
        geofenceStatus.textContent = error.message || 'Geofence event could not be recorded.';
      } finally {
        submit.disabled = false;
      }
    }, (error) => {
      geofenceStatus.textContent = error.code === error.PERMISSION_DENIED
        ? 'Location permission was denied. Enable GPS permission to record the geofence event.'
        : 'Current device location is unavailable. Move outdoors and retry.';
      submit.disabled = false;
    }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
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
    roleStatus.textContent = 'Updating account access...';
    try {
      const userId = document.getElementById('account-role-user').value;
      const role = accountRole.value;
      const displayName = document.getElementById('account-driver-name').value.trim();
      await apiRequest(`${apiRoot}/api/auth/users/${encodeURIComponent(userId)}/role`, {
        method: 'PATCH',
        body: JSON.stringify({ role, display_name: displayName }),
      });
      roleStatus.textContent = 'Account role updated. The user should sign in again to refresh their portal.';
      await loadAvailableShipments();
    } catch (error) {
      roleStatus.textContent = error.message || 'Could not update the account role.';
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
        `${apiRoot}/api/shipments/${encodeURIComponent(trackingNumber)}/documents`,
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

  operationalEvidenceForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const trackingNumber = document.getElementById('operational-evidence-tracking').value.trim();
    const file = document.getElementById('operational-evidence-image').files[0];
    const status = document.getElementById('operational-evidence-status');
    const submit = operationalEvidenceForm.querySelector('button[type="submit"]');
    if (!trackingNumber || !file) {
      status.textContent = 'Enter the shipment tracking number and choose an image.';
      return;
    }
    const body = new FormData();
    body.append('evidence_type', document.getElementById('operational-evidence-type').value);
    body.append('image', file);
    body.append('note', document.getElementById('operational-evidence-note').value.trim());
    submit.disabled = true;
    status.textContent = 'Validating and uploading trip evidence...';
    try {
      const result = await apiRequest(
        `${apiRoot}/api/shipments/${encodeURIComponent(trackingNumber)}/operational-evidence`,
        { method: 'POST', body },
      );
      status.textContent = result.message;
      operationalEvidenceForm.reset();
    } catch (error) {
      status.textContent = error.message || 'Trip evidence could not be uploaded.';
    } finally {
      submit.disabled = false;
    }
  });

  documentSelect.addEventListener('change', () => loadShipmentDocuments(documentSelect.value));
  goodsCompanySelect.addEventListener('change', refreshGoodsDeliveryOptions);
  goodsDeliverySelect.addEventListener('change', () => {
    renderGoodsDeliveryDetails();
    refreshPodSignaturePanel();
    refreshDamageClaimPanel();
  });
  if (geofencePanel) {
    geofencePanel.hidden = window.DifanApp?.state?.currentUser?.role !== 'driver';
  }
  if (navLink) navLink.addEventListener('click', loadAvailableShipments);
  if (goodsNavLink) goodsNavLink.addEventListener('click', refreshGoodsPage);
  window.addEventListener('difan:session-ready', loadAvailableShipments);
});
