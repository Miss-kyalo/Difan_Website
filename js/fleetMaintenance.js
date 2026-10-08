document.addEventListener('DOMContentLoaded', () => {
  const incidentPanel = document.getElementById('fleet-incident-panel');
  const healthPanel = document.getElementById('fleet-health-panel');
  const sparesPanel = document.getElementById('fleet-spares-panel');
  const emergencyPanel = document.getElementById('workforce-emergency-panel');
  const incidentForm = document.getElementById('fleet-incident-form');
  const spareCreateForm = document.getElementById('fleet-spare-create-form');
  const spareUsageForm = document.getElementById('fleet-spare-usage-form');
  if (!incidentPanel || !healthPanel || !sparesPanel || !incidentForm || !spareCreateForm || !spareUsageForm) return;

  const apiRoot = 'http://localhost:5000';
  const managementRoles = new Set(['admin', 'boss', 'hr', 'mechanic']);
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
    const response = await fetch(`${apiRoot}${path}`, {
      ...options,
      headers: {
        ...headers(),
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
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
      [
        `${vehicle.registration} · ${vehicle.truck_name}`,
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

  function renderBreakdowns(breakdowns) {
    const rows = document.getElementById('breakdown-control-rows');
    rows.replaceChildren();
    if (!breakdowns.length) {
      const row = document.createElement('tr');
      const cell = document.createElement('td');
      cell.colSpan = 4;
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
    const canUseFleet = employeeRoles.has(role);
    incidentPanel.hidden = !canUseFleet;
    healthPanel.hidden = !canUseFleet;
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
      renderBreakdowns(breakdownData.breakdowns || []);
      setOptions(
        document.getElementById('fleet-incident-vehicle'),
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
  window.addEventListener('difan:session-ready', loadFleet);
  loadFleet();
});
