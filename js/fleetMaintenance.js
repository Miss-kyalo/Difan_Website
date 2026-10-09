document.addEventListener('DOMContentLoaded', () => {
  const incidentPanel = document.getElementById('fleet-incident-panel');
  const healthPanel = document.getElementById('fleet-health-panel');
  const sparesPanel = document.getElementById('fleet-spares-panel');
  const emergencyPanel = document.getElementById('workforce-emergency-panel');
  const incidentForm = document.getElementById('fleet-incident-form');
  const spareCreateForm = document.getElementById('fleet-spare-create-form');
  const spareUsageForm = document.getElementById('fleet-spare-usage-form');
  const mileagePanel = document.getElementById('fleet-mileage-panel');
  const mileageForm = document.getElementById('fleet-mileage-form');
  const mileageRows = document.getElementById('fleet-mileage-rows');
  const certificatePanel = document.getElementById('fleet-certificates-panel');
  const certificateForm = document.getElementById('fleet-certificate-upload-form');
  const certificateModal = document.getElementById('fleet-certificate-hard-stop-modal');
  if (!incidentPanel || !healthPanel || !sparesPanel || !incidentForm || !spareCreateForm ||
      !spareUsageForm || !mileagePanel || !mileageForm || !mileageRows ||
      !certificatePanel || !certificateForm || !certificateModal) return;

  const apiRoot = window.DifanApp.apiBase;
  const managementRoles = new Set(['admin', 'boss', 'hr', 'mechanic']);
  const fleetManagerRoles = new Set(['admin', 'boss', 'hr']);
  const employeeRoles = new Set(['driver', ...managementRoles]);
  let vehicles = [];
  let spareParts = [];

  function user() {
    return window.DifanApp?.state?.currentUser;
  }

  function headers() {
    const token = localStorage.getItem('jwt_token');
    if (!token) throw new Error('Please sign in to access fleet maintenance.');
    return { Authorization: ['Bearer', token].join(' ') };
  }

  async function apiRequest(path, options = {}) {
    const isFormData = options.body instanceof FormData;
    const response = await fetch(`${apiRoot}${path}`, {
      ...options,
      headers: {
        ...headers(),
        ...(!isFormData && options.body ? { 'Content-Type': 'application/json' } : {}),
        ...options.headers,
      },
    });
    const contentType = response.headers.get('Content-Type') || '';
    const data = contentType.includes('application/json')
      ? await response.json()
      : { message: 'The server returned an unexpected response.' };
    if (!response.ok) throw new Error(data.message || 'The fleet request could not be completed.');
    return data;
  }

  async function downloadCertificate(path, filename) {
    const response = await fetch(`${apiRoot}${path}`, { headers: headers() });
    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.message || 'Certificate photo could not be downloaded.');
    }
    const blobUrl = URL.createObjectURL(await response.blob());
    const anchor = document.createElement('a');
    anchor.href = blobUrl;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
  }

  function renderCertificateDashboard() {
    const list = document.getElementById('fleet-certificate-vehicle-list');
    const hardStopDetails = document.getElementById('fleet-certificate-hard-stop-details');
    list.replaceChildren();
    hardStopDetails.replaceChildren();
    const blockedCertificates = [];
    vehicles.forEach((vehicle) => {
      const card = document.createElement('article');
      card.className = 'workflow-card';
      const heading = document.createElement('h3');
      heading.append(window.DifanApp.vehicleLink(vehicle.registration), ` · ${vehicle.truck_name}`);
      card.appendChild(heading);
      vehicle.certificates.forEach((certificate) => {
        const line = document.createElement('p');
        line.className = 'fleet-certificate-line';
        const dot = document.createElement('span');
        dot.className = `fleet-certificate-dot fleet-certificate-dot--${certificate.indicator}`;
        dot.setAttribute('aria-label', certificate.indicator);
        const text = certificate.expires_on
          ? `${certificate.label}: ${certificate.indicator.toLowerCase()} · expires ${certificate.expires_on} (${certificate.days_remaining} days)`
          : `${certificate.label}: missing approved certificate`;
        line.append(dot, document.createTextNode(text));
        card.appendChild(line);
        if (certificate.pending_count) {
          card.appendChild(document.createTextNode(
            `${certificate.pending_count} renewal submission(s) awaiting review.`,
          ));
        }
        if (certificate.blocked) {
          blockedCertificates.push(`${vehicle.registration} · ${text}`);
          hardStopDetails.appendChild(document.createElement('p')).textContent =
            `${vehicle.registration} · ${text}`;
        }
      });
      const dispatch = document.createElement('p');
      dispatch.textContent = vehicle.dispatch_eligible
        ? 'Dispatch status: eligible'
        : 'Dispatch status: blocked pending approved certificates or vehicle availability.';
      card.appendChild(dispatch);
      list.appendChild(card);
    });
    if (!vehicles.length) {
      list.appendChild(document.createTextNode('No assigned vehicles are available for certificate tracking.'));
    }
    if (user()?.role === 'driver' && blockedCertificates.length && !certificateModal.open) {
      certificateModal.showModal();
    }
  }

  async function renderPendingCertificateReviews() {
    const panel = document.getElementById('fleet-certificate-review-panel');
    const list = document.getElementById('fleet-certificate-pending-list');
    panel.hidden = !fleetManagerRoles.has(user()?.role);
    list.replaceChildren();
    if (panel.hidden) return;
    const data = await apiRequest('/api/fleet/certificates/pending');
    if (!data.certificates.length) {
      list.appendChild(document.createTextNode('No certificate renewals are awaiting approval.'));
      return;
    }
    data.certificates.forEach((certificate) => {
      const card = document.createElement('article');
      card.className = 'workflow-card';
      const heading = document.createElement('h3');
      heading.textContent = `${certificate.registration} · ${certificate.certificate_label}`;
      const details = document.createElement('p');
      details.textContent = `Expiry ${certificate.expires_on} · submitted by ${certificate.uploaded_by || 'unknown'} · ${new Date(certificate.uploaded_at).toLocaleString()}`;
      const download = document.createElement('button');
      download.type = 'button';
      download.className = 'btn btn-secondary';
      download.textContent = 'Review certificate photo';
      download.addEventListener('click', async () => {
        try {
          await downloadCertificate(certificate.download_url, certificate.filename);
        } catch (error) {
          window.DifanApp.showToast(error.message, 'error');
        }
      });
      const approve = document.createElement('button');
      approve.type = 'button';
      approve.className = 'btn btn-primary';
      approve.textContent = 'Approve renewal';
      approve.addEventListener('click', async () => {
        approve.disabled = true;
        try {
          const result = await apiRequest(`/api/fleet/certificates/${certificate.id}/review`, {
            method: 'PATCH',
            body: JSON.stringify({ decision: 'APPROVED', note: '' }),
          });
          window.DifanApp.showToast(result.message, 'success');
          await loadFleet();
        } catch (error) {
          window.DifanApp.showToast(error.message || 'The certificate could not be approved.', 'error');
          approve.disabled = false;
        }
      });
      const reject = document.createElement('button');
      reject.type = 'button';
      reject.className = 'btn btn-secondary';
      reject.textContent = 'Reject renewal';
      reject.addEventListener('click', async () => {
        reject.disabled = true;
        try {
          const result = await apiRequest(`/api/fleet/certificates/${certificate.id}/review`, {
            method: 'PATCH',
            body: JSON.stringify({ decision: 'REJECTED', note: 'Renewal document rejected during review.' }),
          });
          window.DifanApp.showToast(result.message, 'success');
          await loadFleet();
        } catch (error) {
          window.DifanApp.showToast(error.message || 'The certificate could not be rejected.', 'error');
          reject.disabled = false;
        }
      });
      card.append(heading, details, download, approve, reject);
      list.appendChild(card);
    });
  }

  function setOptions(select, records, placeholder, valueOf, labelOf) {
    select.replaceChildren();
    const empty = document.createElement('option');
    empty.value = '';
    empty.textContent = placeholder;
    select.appendChild(empty);
    records.forEach((record) => {
      const option = document.createElement('option');
      option.value = valueOf(record);
      option.textContent = labelOf(record);
      select.appendChild(option);
    });
  }

  function setStatus(id, message, error = false) {
    const element = document.getElementById(id);
    element.textContent = message;
    element.dataset.state = error ? 'error' : 'success';
  }

  function renderHealth() {
    const rows = document.getElementById('fleet-health-rows');
    const history = document.getElementById('fleet-history-list');
    rows.replaceChildren();
    history.replaceChildren();
    vehicles.forEach((vehicle) => {
      const row = document.createElement('tr');
      const truckCell = document.createElement('td');
      truckCell.appendChild(window.DifanApp.vehicleLink(vehicle.registration));
      truckCell.appendChild(document.createTextNode(` · ${vehicle.truck_name}`));
      row.appendChild(truckCell);
      [
        vehicle.status,
        `${Number(vehicle.current_odometer_km).toLocaleString()} km`,
        String(vehicle.breakdowns_last_12_months),
        vehicle.parts_due?.filter((part) => part.status !== 'OK').map((part) =>
          `${part.name}: ${part.status.replace('_', ' ').toLowerCase()} (${Math.max(0, Math.round(part.remaining_km)).toLocaleString()} km)`,
        ).join('; ') || 'No service due recorded',
      ].forEach((value) => {
        const cell = document.createElement('td');
        cell.textContent = value;
        row.appendChild(cell);
      });
      rows.appendChild(row);

      if (!vehicle.breakdown_history?.length && !vehicle.spare_history?.length) return;
      const card = document.createElement('article');
      card.className = 'workflow-card';
      const heading = document.createElement('h3');
      heading.textContent = `${vehicle.registration} maintenance history`;
      card.appendChild(heading);
      (vehicle.breakdown_history || []).slice(0, 8).forEach((breakdown) => {
        const item = document.createElement('p');
        item.textContent = `Breakdown · ${breakdown.incident_date || new Date(breakdown.reported_at).toLocaleDateString()} · ${breakdown.severity} · ${breakdown.description} · ${breakdown.status}`;
        card.appendChild(item);
      });
      (vehicle.spare_history || []).slice(0, 12).forEach((change) => {
        const item = document.createElement('p');
        item.textContent = `Part replacement · ${change.part_name} (${change.part_number}) · qty ${change.quantity} · ${Number(change.changed_at_odometer).toLocaleString()} km · ${change.replaced_by}`;
        card.appendChild(item);
      });
      history.appendChild(card);
    });
    if (!vehicles.length) {
      const row = document.createElement('tr');
      const cell = document.createElement('td');
      cell.colSpan = 5;
      cell.textContent = 'No trucks are available for this account.';
      row.appendChild(cell);
      rows.appendChild(row);
    }
  }

  function renderSpares() {
    const inventory = document.getElementById('fleet-spare-inventory');
    const partSelect = document.getElementById('fleet-spare-part');
    inventory.replaceChildren();
    setOptions(
      partSelect,
      spareParts,
      'Select a stocked spare part',
      (part) => String(part.id),
      (part) => `${part.part_number} · ${part.name} · ${part.stock_quantity} in stock`,
    );
    spareParts.forEach((part) => {
      const card = document.createElement('article');
      card.className = 'workflow-card';
      const heading = document.createElement('h3');
      heading.textContent = `${part.part_number} · ${part.name}`;
      const summary = document.createElement('p');
      summary.textContent = `${part.stock_quantity} in stock · reorder at ${part.reorder_level} · replace every ${Number(part.service_interval_km).toLocaleString()} km · ${part.stock_status.replace('_', ' ').toLowerCase()}`;
      const form = document.createElement('form');
      form.className = 'workflow-actions';
      const quantity = document.createElement('input');
      quantity.type = 'number';
      quantity.min = '1';
      quantity.step = '1';
      quantity.required = true;
      quantity.setAttribute('aria-label', `Restock quantity for ${part.name}`);
      quantity.placeholder = 'Restock quantity';
      const submit = document.createElement('button');
      submit.type = 'submit';
      submit.className = 'btn btn-secondary';
      submit.textContent = 'Restock';
      form.append(quantity, submit);
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        submit.disabled = true;
        try {
          await apiRequest(`/api/fleet/spares/${part.id}/restock`, {
            method: 'POST',
            body: JSON.stringify({ quantity: Number(quantity.value) }),
          });
          await loadFleet();
          setStatus('fleet-spare-status', `${part.name} stock was updated.`);
        } catch (error) {
          setStatus('fleet-spare-status', error.message || 'Could not restock this spare part.', true);
        } finally {
          submit.disabled = false;
        }
      });
      card.append(heading, summary, form);
      inventory.appendChild(card);
    });
    if (!spareParts.length) {
      const empty = document.createElement('p');
      empty.className = 'workflow-empty';
      empty.textContent = 'No spare parts have been added to inventory yet.';
      inventory.appendChild(empty);
    }
  }

  function renderMileage(records) {
    mileageRows.replaceChildren();
    records.forEach((record) => {
      const row = document.createElement('tr');
      [
        new Date(record.recorded_at).toLocaleString(),
        record.vehicle_registration,
        record.shipment_tracking_number || record.trip_reference || '—',
        `${Number(record.distance_since_last_km).toLocaleString()} km`,
        `KES ${Number(record.mileage_amount_issued_kes || 0).toLocaleString()}`,
        record.driver_name,
        record.turnman_name || '—',
        record.notes || '—',
      ].forEach((value, index) => {
        const cell = document.createElement('td');
        if (index === 1 && window.DifanApp?.vehicleLink) cell.appendChild(window.DifanApp.vehicleLink(value));
        else cell.textContent = value;
        row.appendChild(cell);
      });
      mileageRows.appendChild(row);
    });
    if (!records.length) {
      const row = document.createElement('tr');
      const cell = document.createElement('td');
      cell.colSpan = 8;
      cell.textContent = 'No mileage readings have been recorded for this truck.';
      row.appendChild(cell);
      mileageRows.appendChild(row);
    }
  }

  async function loadMileage(registration) {
    mileageRows.replaceChildren();
    if (!registration) {
      renderMileage([]);
      return;
    }
    try {
      const data = await apiRequest(`/api/fleet/vehicles/${encodeURIComponent(registration)}/mileage`);
      renderMileage(data.records || []);
      const vehicle = vehicles.find((item) => item.registration === registration);
      setStatus('fleet-mileage-status', `${data.records.length} trip mileage record(s) loaded.`);
    } catch (error) {
      renderMileage([]);
      setStatus('fleet-mileage-status', error.message || 'Mileage history could not be loaded.', true);
    }
  }

  function renderBreakdowns(breakdowns) {
    const rows = document.getElementById('breakdown-control-rows');
    rows.replaceChildren();
    if (!breakdowns.length) {
      const row = document.createElement('tr');
      const cell = document.createElement('td');
      cell.colSpan = 6;
      cell.textContent = 'No breakdown incidents have been reported.';
      row.appendChild(cell);
      rows.appendChild(row);
      return;
    }
    breakdowns.forEach((breakdown) => {
      const row = document.createElement('tr');
      [
        `${breakdown.vehicle_registration} · ${breakdown.description}`,
        breakdown.reported_by,
        `${breakdown.status} · ${breakdown.severity}`,
        breakdown.replacement_driver || 'Not assigned',
        breakdown.mechanic_in_charge || 'Not assigned',
      ].forEach((value) => {
        const cell = document.createElement('td');
        cell.textContent = value;
        row.appendChild(cell);
      });
      const actionCell = document.createElement('td');
      if (managementRoles.has(user()?.role) && breakdown.status === 'OPEN') {
        const form = document.createElement('form');
        form.className = 'workflow-form';
        const work = document.createElement('input');
        work.placeholder = 'Repair work performed';
        work.maxLength = 1000;
        work.required = true;
        const technician = document.createElement('input');
        technician.placeholder = 'Technician';
        technician.maxLength = 120;
        technician.required = true;
        const cost = document.createElement('input');
        cost.type = 'number';
        cost.min = '0';
        cost.step = '0.01';
        cost.value = '0';
        cost.setAttribute('aria-label', 'Repair cost in KES');
        const completeLabel = document.createElement('label');
        const complete = document.createElement('input');
        complete.type = 'checkbox';
        completeLabel.append(complete, document.createTextNode(' Repair complete; return truck to service'));
        const submit = document.createElement('button');
        submit.type = 'submit';
        submit.className = 'btn btn-secondary';
        submit.textContent = 'Save repair log';
        form.append(work, technician, cost, completeLabel, submit);
        form.addEventListener('submit', async (event) => {
          event.preventDefault();
          submit.disabled = true;
          try {
            await apiRequest(`/api/fleet/breakdowns/${breakdown.id}/repairs`, {
              method: 'POST',
              body: JSON.stringify({
                description: work.value.trim(),
                technician_name: technician.value.trim(),
                cost_kes: Number(cost.value),
                completed: complete.checked,
              }),
            });
            await loadFleet();
          } catch (error) {
            window.DifanApp.showToast(error.message || 'Could not save the repair log.', 'error');
            submit.disabled = false;
          }
        });
        actionCell.appendChild(form);
      } else {
        actionCell.textContent = breakdown.repairs?.map((repair) =>
          `${repair.technician_name}: ${repair.description}`,
        ).join('; ') || 'No repair recorded';
      }
      row.appendChild(actionCell);
      rows.appendChild(row);
    });
  }

  async function loadFleet() {
    const role = user()?.role;
    const previousMileageVehicle = document.getElementById('fleet-mileage-vehicle').value;
    const canUseFleet = employeeRoles.has(role);
    incidentPanel.hidden = !canUseFleet;
    healthPanel.hidden = !canUseFleet;
    mileagePanel.hidden = !canUseFleet;
    certificatePanel.hidden = !canUseFleet;
    sparesPanel.hidden = !managementRoles.has(role);
    emergencyPanel.hidden = !canUseFleet;
    if (!canUseFleet) return;

    try {
      const [vehicleData, breakdownData] = await Promise.all([
        apiRequest('/api/fleet/vehicles'),
        apiRequest('/api/fleet/breakdowns'),
      ]);
      vehicles = vehicleData.vehicles || [];
      renderHealth();
      renderCertificateDashboard();
      await renderPendingCertificateReviews();
      renderBreakdowns(breakdownData.breakdowns || []);
      try {
        const shipmentData = await apiRequest('/api/shipments');
        const select = document.getElementById('fleet-mileage-shipment');
        const previous = select.value;
        select.replaceChildren(new Option('Select a shipment', ''));
        (shipmentData.shipments || []).forEach((shipment) => {
          select.appendChild(new Option(
            `${shipment.tracking_number} · ${shipment.origin} → ${shipment.destination}`,
            shipment.tracking_number,
          ));
        });
        select.value = previous;
      } catch (_error) { /* shipments list is optional for non-shipment roles */ }
      setOptions(
        document.getElementById('fleet-certificate-vehicle'),
        vehicles,
        'Select a truck',
        (vehicle) => vehicle.registration,
        (vehicle) => `${vehicle.registration} · ${vehicle.truck_name}`,
      );
      setOptions(
        document.getElementById('fleet-incident-vehicle'),
        vehicles,
        'Select a truck',
        (vehicle) => vehicle.registration,
        (vehicle) => `${vehicle.registration} · ${vehicle.truck_name}`,
      );
      setOptions(
        document.getElementById('fleet-mileage-vehicle'),
        vehicles,
        'Select a truck',
        (vehicle) => vehicle.registration,
        (vehicle) => `${vehicle.registration} · ${vehicle.truck_name}`,
      );
      setOptions(
        document.getElementById('fleet-spare-vehicle'),
        vehicles,
        'Select a truck',
        (vehicle) => vehicle.registration,
        (vehicle) => `${vehicle.registration} · ${vehicle.truck_name}`,
      );
      if (role === 'driver' && vehicles.length === 1) {
        document.getElementById('fleet-incident-vehicle').value = vehicles[0].registration;
        document.getElementById('fleet-spare-vehicle').value = vehicles[0].registration;
      }
      if (vehicles.length) {
        const selectedVehicle = vehicles.some((vehicle) => vehicle.registration === previousMileageVehicle)
          ? previousMileageVehicle
          : vehicles[0].registration;
        document.getElementById('fleet-mileage-vehicle').value = selectedVehicle;
        await loadMileage(selectedVehicle);
      } else {
        renderMileage([]);
      }
      if (managementRoles.has(role)) {
        const spareData = await apiRequest('/api/fleet/spares');
        spareParts = spareData.spares || [];
        renderSpares();
      }
    } catch (error) {
      setStatus('fleet-incident-status', error.message || 'Fleet records could not be loaded.', true);
    }
  }

  document.getElementById('fleet-incident-date').value = new Date().toISOString().slice(0, 10);
  document.getElementById('fleet-incident-vehicle').addEventListener('change', (event) => {
    const vehicle = vehicles.find((item) => item.registration === event.target.value);
    document.getElementById('fleet-incident-odometer').value = vehicle?.current_odometer_km ?? '';
    document.getElementById('fleet-spare-odometer').value = vehicle?.current_odometer_km ?? '';
  });
  document.getElementById('fleet-spare-vehicle').addEventListener('change', (event) => {
    const vehicle = vehicles.find((item) => item.registration === event.target.value);
    document.getElementById('fleet-spare-odometer').value = vehicle?.current_odometer_km ?? '';
  });
  document.getElementById('fleet-mileage-vehicle').addEventListener('change', (event) => {
    const vehicle = vehicles.find((item) => item.registration === event.target.value);
    loadMileage(event.target.value);
  });

  certificateForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const registration = document.getElementById('fleet-certificate-vehicle').value;
    const image = document.getElementById('fleet-certificate-photo').files[0];
    const status = document.getElementById('fleet-certificate-upload-status');
    const submit = certificateForm.querySelector('button[type="submit"]');
    if (!registration || !image) {
      setStatus('fleet-certificate-upload-status', 'Select a truck and certificate photo.', true);
      return;
    }
    const body = new FormData();
    body.append('certificate_type', document.getElementById('fleet-certificate-type').value);
    body.append('expires_on', document.getElementById('fleet-certificate-expires').value);
    body.append('document', image);
    submit.disabled = true;
    status.textContent = 'Uploading renewal for review...';
    try {
      const result = await apiRequest(
        `/api/fleet/vehicles/${encodeURIComponent(registration)}/certificates`,
        { method: 'POST', body },
      );
      setStatus('fleet-certificate-upload-status', result.message);
      certificateForm.reset();
      await loadFleet();
    } catch (error) {
      setStatus(
        'fleet-certificate-upload-status',
        error.message || 'Certificate renewal could not be uploaded.',
        true,
      );
    } finally {
      submit.disabled = false;
    }
  });

  document.getElementById('fleet-certificate-hard-stop-close').addEventListener('click', () => {
    certificateModal.close();
  });
  document.getElementById('fleet-certificate-hard-stop-review').addEventListener('click', () => {
    certificateModal.close();
    certificateForm.scrollIntoView({ behavior: 'smooth', block: 'center' });
    document.getElementById('fleet-certificate-vehicle').focus();
  });

  mileageForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const submit = mileageForm.querySelector('button[type="submit"]');
    const registration = document.getElementById('fleet-mileage-vehicle').value;
    const vehicle = vehicles.find((item) => item.registration === registration);
    submit.disabled = true;
    setStatus('fleet-mileage-status', 'Saving the trip mileage...');
    try {
      const data = await apiRequest(`/api/fleet/vehicles/${encodeURIComponent(registration)}/mileage`, {
        method: 'POST',
        body: JSON.stringify({
          driver_id: vehicle?.assigned_driver_id,
          trip_distance_km: Number(document.getElementById('fleet-mileage-distance').value),
          turnman_name: document.getElementById('fleet-mileage-turnman').value.trim(),
          shipment_tracking_number: document.getElementById('fleet-mileage-shipment').value,
          mileage_amount_issued_kes: Number(document.getElementById('fleet-mileage-amount').value || 0),
          notes: document.getElementById('fleet-mileage-notes').value.trim(),
        }),
      });
      setStatus(
        'fleet-mileage-status',
        `Trip saved for ${data.record.shipment_tracking_number}: ${Number(data.record.distance_since_last_km).toLocaleString()} km, KES ${Number(data.record.mileage_amount_issued_kes).toLocaleString()} issued.`,
      );
      mileageForm.reset();
      await loadFleet();
    } catch (error) {
      setStatus('fleet-mileage-status', error.message || 'Could not save the mileage reading.', true);
    } finally {
      submit.disabled = false;
    }
  });

  incidentForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const submit = incidentForm.querySelector('button[type="submit"]');
    submit.disabled = true;
    setStatus('fleet-incident-status', 'Saving incident report...');
    try {
      const symptoms = document.getElementById('fleet-incident-symptoms').value.trim();
      const data = await apiRequest(
        `/api/fleet/vehicles/${encodeURIComponent(document.getElementById('fleet-incident-vehicle').value)}/breakdowns`,
        {
          method: 'POST',
          body: JSON.stringify({
            incident_date: document.getElementById('fleet-incident-date').value,
            severity: document.getElementById('fleet-incident-severity').value,
            odometer_km: Number(document.getElementById('fleet-incident-odometer').value),
            location: document.getElementById('fleet-incident-location').value.trim(),
            symptoms,
            description: symptoms,
            findings: document.getElementById('fleet-incident-findings').value.trim(),
            action_taken: document.getElementById('fleet-incident-action').value.trim(),
            parts_used: document.getElementById('fleet-incident-parts').value.trim(),
            replacement_driver: document.getElementById('fleet-incident-replacement-driver').value.trim(),
            mechanic_in_charge: document.getElementById('fleet-incident-mechanic-in-charge').value.trim(),
          }),
        },
      );
      incidentForm.reset();
      document.getElementById('fleet-incident-date').value = new Date().toISOString().slice(0, 10);
      setStatus('fleet-incident-status', `${data.message} Reference: ${data.breakdown.id}.`);
      await loadFleet();
    } catch (error) {
      setStatus('fleet-incident-status', error.message || 'Could not save the incident report.', true);
    } finally {
      submit.disabled = false;
    }
  });

  spareCreateForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const submit = spareCreateForm.querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
      await apiRequest('/api/fleet/spares', {
        method: 'POST',
        body: JSON.stringify({
          part_number: document.getElementById('fleet-spare-number').value.trim(),
          name: document.getElementById('fleet-spare-name').value.trim(),
          service_interval_km: Number(document.getElementById('fleet-spare-interval').value),
          stock_quantity: Number(document.getElementById('fleet-spare-stock').value),
          reorder_level: Number(document.getElementById('fleet-spare-reorder').value),
        }),
      });
      spareCreateForm.reset();
      document.getElementById('fleet-spare-stock').value = '0';
      document.getElementById('fleet-spare-reorder').value = '0';
      await loadFleet();
      setStatus('fleet-spare-status', 'Spare part added to inventory.');
    } catch (error) {
      setStatus('fleet-spare-status', error.message || 'Could not add the spare part.', true);
    } finally {
      submit.disabled = false;
    }
  });

  spareUsageForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const submit = spareUsageForm.querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
      const registration = document.getElementById('fleet-spare-vehicle').value;
      const data = await apiRequest(`/api/fleet/vehicles/${encodeURIComponent(registration)}/spare-changes`, {
        method: 'POST',
        body: JSON.stringify({
          spare_part_id: Number(document.getElementById('fleet-spare-part').value),
          quantity: Number(document.getElementById('fleet-spare-quantity').value),
          changed_at_odometer: Number(document.getElementById('fleet-spare-odometer').value),
          replaced_by: document.getElementById('fleet-spare-technician').value.trim(),
          notes: document.getElementById('fleet-spare-notes').value.trim(),
        }),
      });
      setStatus('fleet-spare-status', data.message);
      spareUsageForm.reset();
      document.getElementById('fleet-spare-quantity').value = '1';
      await loadFleet();
    } catch (error) {
      setStatus('fleet-spare-status', error.message || 'Could not record spare-part usage.', true);
    } finally {
      submit.disabled = false;
    }
  });

  document.querySelector('[data-target-tab="breakdowns"]')?.addEventListener('click', loadFleet);
  document.querySelector('[data-target-tab="fleet"]')?.addEventListener('click', loadFleet);
  window.addEventListener('difan:session-ready', loadFleet);
  loadFleet();
});
