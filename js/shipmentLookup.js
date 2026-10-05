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
  let shipments = [];

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

  function renderAccessibleShipments() {
    accessibleList.replaceChildren();
    if (!shipments.length) {
      const empty = document.createElement('p');
      empty.className = 'workflow-empty';
      empty.textContent = 'No shipments are assigned to this account yet.';
      accessibleList.appendChild(empty);
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
          ['AWAITING_DISPATCH', 'IN_TRANSIT'].includes(shipment.status)) {
        const statusButton = document.createElement('button');
        statusButton.type = 'button';
        statusButton.className = 'btn btn-primary';
        statusButton.textContent = shipment.status === 'AWAITING_DISPATCH' ? 'Start trip' : 'Mark delivered';
        statusButton.addEventListener('click', async () => {
          statusButton.disabled = true;
          try {
            await apiRequest(`http://localhost:5000/api/shipments/${encodeURIComponent(shipment.tracking_number)}/status`, {
              method: 'PATCH',
              body: JSON.stringify({
                status: shipment.status === 'AWAITING_DISPATCH' ? 'IN_TRANSIT' : 'DELIVERED',
              }),
            });
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
    const canDownload = role === 'client' || role === 'admin';
    uploadPanel.hidden = !isDriver;
    documentPanel.hidden = !canDownload;
    try {
      const data = await apiRequest('http://localhost:5000/api/shipments');
      shipments = data.shipments || [];
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
      renderAccessibleShipments();
      setStatus(`${shipments.length} shipment${shipments.length === 1 ? '' : 's'} available to your account.`, 'success');

      const user = window.DifanApp?.state?.currentUser;
      const isAdmin = user?.role === 'admin';
      adminTools.hidden = !isAdmin;
      if (isAdmin) await loadAdminOptions();
      if (user?.role === 'driver' || user?.role === 'client' || isAdmin) {
        refreshGoodsPage();
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
    } catch (error) {
      setStatus(error.message || 'Unable to reach the shipment service.', 'error');
    } finally {
      submitButton.disabled = false;
    }
  }

  async function loadAdminOptions() {
    const data = await apiRequest('http://localhost:5000/api/auth/users');
    const users = data.users || [];
    const clientAccounts = users.filter((user) => user.role === 'client');
    const drivers = users.filter((user) => user.role === 'driver');
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

    const uniqueCompanies = [...new Set(clientAccounts.map((user) => user.company_name))];
    setOptions(companySelect, uniqueCompanies.map((company) => ({ value: company, label: company })), 'Select client company');
    setOptions(driverSelect, drivers.map((user) => ({
      value: String(user.id),
      label: `${user.driver_name} (${user.email})`,
    })), 'Select driver');
    setOptions(shipmentSelect, shipments.map((shipment) => ({
      value: shipment.tracking_number,
      label: `${shipment.tracking_number} — ${shipment.company_name || 'Unassigned'}`,
    })), 'Select shipment');
    const selectedShipment = shipments.find((item) => item.tracking_number === shipmentSelect.value);
    destinationInput.value = selectedShipment?.destination || '';
    setOptions(accountSelect, users.map((user) => ({
      value: String(user.id),
      label: `${user.email} — ${user.role}`,
    })), 'Select account');

    const noAssignmentTargets = !uniqueCompanies.length || !drivers.length;
    assignmentForm.querySelector('button[type="submit"]').disabled = noAssignmentTargets || !shipments.length;
    if (noAssignmentTargets) {
      adminStatus.textContent = 'Create client accounts and provision driver accounts before assigning shipments.';
    } else {
      adminStatus.textContent = '';
    }
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
      await apiRequest(`http://localhost:5000/api/shipments/${encodeURIComponent(trackingNumber)}/assignment`, {
        method: 'PATCH',
        body: JSON.stringify({
          company_name: document.getElementById('assignment-company').value,
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

  accountRole.addEventListener('change', () => {
    const needsDriverName = accountRole.value === 'driver';
    driverNameField.hidden = !needsDriverName;
    document.getElementById('account-driver-name').required = needsDriverName;
  });

  roleForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    adminStatus.textContent = 'Updating account access...';
    try {
      const userId = document.getElementById('account-role-user').value;
      const role = accountRole.value;
      const driverName = document.getElementById('account-driver-name').value.trim();
      await apiRequest(`http://localhost:5000/api/auth/users/${encodeURIComponent(userId)}/role`, {
        method: 'PATCH',
        body: JSON.stringify({ role, driver_name: driverName }),
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
  if (navLink) navLink.addEventListener('click', loadAvailableShipments);
  if (goodsNavLink) goodsNavLink.addEventListener('click', refreshGoodsPage);
  window.addEventListener('difan:session-ready', loadAvailableShipments);
});
