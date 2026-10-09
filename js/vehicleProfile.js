document.addEventListener('DOMContentLoaded', () => {
  const modal = document.getElementById('vehicle-profile-modal');
  const body = document.getElementById('vehicle-profile-body');
  const title = document.getElementById('vehicle-profile-title');
  const directoryPanel = document.getElementById('fleet-directory-panel');
  const directoryRows = document.getElementById('fleet-directory-rows');
  const directoryStatus = document.getElementById('fleet-directory-status');
  const phoneForm = document.getElementById('employee-phone-form');
  if (!modal || !body || !directoryPanel) return;

  const apiRoot = window.DifanApp.apiBase;
  const objectUrls = [];

  function user() {
    return window.DifanApp?.state?.currentUser;
  }

  function isEmployee() {
    const role = user()?.role;
    return Boolean(role) && role !== 'client';
  }

  async function request(path, options = {}) {
    const token = localStorage.getItem('jwt_token');
    if (!token) throw new Error('Please sign in to continue.');
    const response = await fetch(`${apiRoot}${path}`, {
      ...options,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      },
    });
    return response;
  }

  async function requestJson(path, options) {
    const response = await request(path, options);
    const text = await response.text();
    let data = {};
    try {
      data = text ? JSON.parse(text) : {};
    } catch (error) {
      data = {};
    }
    if (!response.ok) throw new Error(data.message || 'The request could not be completed.');
    return data;
  }

  function addRow(list, label, value) {
    const row = document.createElement('div');
    const term = document.createElement('dt');
    term.textContent = label;
    const detail = document.createElement('dd');
    if (value instanceof Node) detail.appendChild(value);
    else detail.textContent = value || 'Not provided';
    row.append(term, detail);
    list.appendChild(row);
  }

  async function openDocument(documentRecord, button) {
    button.disabled = true;
    try {
      const response = await request(documentRecord.download_url);
      if (!response.ok) throw new Error('This document could not be opened.');
      const url = URL.createObjectURL(await response.blob());
      objectUrls.push(url);
      window.open(url, '_blank', 'noopener');
    } catch (error) {
      body.querySelector('[data-profile-status]').textContent = error.message;
    } finally {
      button.disabled = false;
    }
  }

  function documentCard(certificate, documentRecord) {
    const card = document.createElement('article');
    card.className = 'workflow-card';
    const heading = document.createElement('h4');
    heading.textContent = certificate.label;
    card.appendChild(heading);
    const line = document.createElement('p');
    if (documentRecord) {
      const dot = document.createElement('span');
      dot.className = `fleet-certificate-dot fleet-certificate-dot--${certificate.indicator}`;
      dot.setAttribute('aria-label', certificate.indicator);
      line.append(dot, document.createTextNode(
        `Current · expires ${certificate.expires_on} (${certificate.days_remaining} days)`,
      ));
    } else {
      line.textContent = 'No approved document on file.';
    }
    card.appendChild(line);
    if (documentRecord) {
      const view = document.createElement('button');
      view.type = 'button';
      view.className = 'btn btn-secondary';
      view.textContent = 'View document';
      view.addEventListener('click', () => openDocument(documentRecord, view));
      card.appendChild(view);
    }
    if (certificate.pending_count) {
      const pending = document.createElement('p');
      pending.className = 'muted';
      pending.textContent = `${certificate.pending_count} renewal(s) awaiting review.`;
      card.appendChild(pending);
    }
    return card;
  }

  function renderProfile(data) {
    const { vehicle, driver, certificates, documents } = data;
    title.textContent = `${vehicle.registration} · ${vehicle.truck_name}`;
    body.replaceChildren();

    const details = document.createElement('dl');
    details.className = 'profile-details';
    addRow(details, 'Make / model', [vehicle.make, vehicle.model].filter(Boolean).join(' '));
    addRow(details, 'Capacity', `${vehicle.capacity_tonnes} tonnes`);
    addRow(details, 'Status', vehicle.status);
    addRow(details, 'Odometer', `${Number(vehicle.current_odometer_km).toLocaleString()} km`);
    addRow(details, 'Dispatch', vehicle.dispatch_eligible ? 'Eligible' : 'Blocked or no driver assigned');
    addRow(details, 'Assigned driver', driver ? `${driver.name}${driver.driver_code ? ` (${driver.driver_code})` : ''}` : 'No driver assigned');
    if (driver) {
      let phone = 'Not provided';
      if (driver.phone) {
        phone = document.createElement('a');
        phone.href = `tel:${driver.phone.replace(/[^+0-9]/g, '')}`;
        phone.textContent = driver.phone;
      }
      addRow(details, 'Driver phone', phone);
    }
    body.appendChild(details);

    const status = document.createElement('p');
    status.className = 'tracking-status';
    status.dataset.profileStatus = '';
    status.setAttribute('role', 'status');
    body.appendChild(status);

    const currentHeading = document.createElement('h3');
    currentHeading.textContent = 'Current documents';
    body.appendChild(currentHeading);
    const grid = document.createElement('div');
    grid.className = 'workforce-grid';
    certificates.forEach((certificate) => {
      const current = documents.find((item) => item.id === certificate.certificate_id);
      grid.appendChild(documentCard(certificate, current));
    });
    body.appendChild(grid);

    const historyHeading = document.createElement('h3');
    historyHeading.textContent = 'All uploaded documents';
    body.appendChild(historyHeading);
    if (!documents.length) {
      const empty = document.createElement('p');
      empty.className = 'muted';
      empty.textContent = 'No documents have been uploaded for this vehicle.';
      body.appendChild(empty);
      return;
    }
    const table = document.createElement('table');
    table.className = 'table-grid';
    const head = table.createTHead().insertRow();
    ['Document', 'Expires', 'Status', 'Uploaded', ''].forEach((text) => {
      head.appendChild(document.createElement('th')).textContent = text;
    });
    const tbody = table.createTBody();
    documents.forEach((item) => {
      const row = tbody.insertRow();
      row.insertCell().textContent = item.certificate_label;
      row.insertCell().textContent = item.expires_on;
      row.insertCell().textContent = item.status;
      row.insertCell().textContent = new Date(item.uploaded_at).toLocaleDateString();
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn btn-secondary';
      button.textContent = 'View';
      button.addEventListener('click', () => openDocument(item, button));
      row.insertCell().appendChild(button);
    });
    const wrap = document.createElement('div');
    wrap.className = 'operations-table-wrap';
    wrap.appendChild(table);
    body.appendChild(wrap);
  }

  async function openVehicleProfile(registration) {
    const fleetView = document.getElementById('view-fleet');
    if (fleetView && (fleetView.hidden || getComputedStyle(fleetView).display === 'none')) document.getElementById('fleet-navigation')?.click();
    title.textContent = registration;
    body.textContent = 'Loading vehicle profile...';
    if (!modal.open) modal.showModal();
    try {
      renderProfile(await requestJson(`/api/fleet/vehicles/${encodeURIComponent(registration)}/profile`));
    } catch (error) {
      body.textContent = error.message || 'Unable to load this vehicle profile.';
    }
  }

  function vehicleLink(registration) {
    const link = document.createElement('button');
    link.type = 'button';
    link.className = 'vehicle-link';
    link.textContent = registration;
    link.title = 'View vehicle profile';
    link.addEventListener('click', () => openVehicleProfile(registration));
    return link;
  }

  window.DifanApp.openVehicleProfile = openVehicleProfile;
  window.DifanApp.vehicleLink = vehicleLink;

  document.getElementById('vehicle-profile-close')?.addEventListener('click', () => modal.close());
  modal.addEventListener('close', () => {
    objectUrls.splice(0).forEach((url) => setTimeout(() => URL.revokeObjectURL(url), 60000));
  });

  async function loadDirectory() {
    directoryPanel.hidden = !isEmployee();
    directoryRows.replaceChildren();
    if (!isEmployee()) return;
    try {
      const data = await requestJson('/api/fleet/directory');
      directoryStatus.textContent = data.vehicles.length ? '' : 'No vehicles have been added to the fleet yet.';
      data.vehicles.forEach((vehicle) => {
        const row = directoryRows.insertRow();
        row.insertCell().appendChild(vehicleLink(vehicle.registration));
        row.insertCell().textContent = vehicle.truck_name;
        row.insertCell().textContent = vehicle.status;
        row.insertCell().textContent = vehicle.assigned_driver_name || 'Unassigned';
      });
    } catch (error) {
      directoryStatus.textContent = error.message || 'Unable to load the fleet directory.';
    }
  }

  async function loadOwnPhone() {
    if (!phoneForm) return;
    try {
      const data = await requestJson('/api/auth/me');
      document.getElementById('employee-phone').value = data.user.phone || '';
    } catch (error) {
      // The profile still works without a prefilled phone number.
    }
  }

  phoneForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const status = document.getElementById('employee-phone-status');
    try {
      await requestJson('/api/auth/profile', {
        method: 'PATCH',
        body: JSON.stringify({ phone: document.getElementById('employee-phone').value }),
      });
      status.textContent = 'Phone number saved.';
    } catch (error) {
      status.textContent = error.message;
    }
  });

  const statutoryFields = [['kra_pin', 'kra-pin'], ['nssf_number', 'nssf'], ['shif_number', 'shif']];
  const adminRoles = new Set(['admin', 'hr', 'boss']);

  function fillStatutory(prefix, employee) {
    statutoryFields.forEach(([field, id]) => {
      document.getElementById(`${prefix}-${id}`).value = employee[field] || '';
    });
  }

  function readStatutory(prefix) {
    return Object.fromEntries(statutoryFields.map(([field, id]) => [
      field, document.getElementById(`${prefix}-${id}`).value.trim(),
    ]));
  }

  async function loadOwnStatutory() {
    try {
      fillStatutory('employee', (await requestJson('/api/auth/employee-details')).employee);
    } catch (error) {
      document.getElementById('employee-statutory-status').textContent = error.message;
    }
  }

  document.getElementById('employee-statutory-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const status = document.getElementById('employee-statutory-status');
    try {
      const data = await requestJson('/api/auth/employee-details', {
        method: 'PATCH', body: JSON.stringify(readStatutory('employee')),
      });
      fillStatutory('employee', data.employee);
      status.textContent = 'Statutory details saved.';
    } catch (error) {
      status.textContent = error.message;
    }
  });

  const adminPanel = document.getElementById('admin-statutory-panel');
  const adminSelect = document.getElementById('admin-statutory-employee');
  const adminStatus = document.getElementById('admin-statutory-status');

  async function loadAdminEmployee() {
    if (!adminSelect.value) return;
    try {
      fillStatutory('admin', (await requestJson(`/api/auth/users/${adminSelect.value}/employee-details`)).employee);
      adminStatus.textContent = '';
    } catch (error) {
      adminStatus.textContent = error.message;
    }
  }

  async function loadAdminPanel() {
    adminPanel.hidden = !adminRoles.has(user()?.role);
    if (adminPanel.hidden) return;
    try {
      const data = await requestJson('/api/auth/users');
      adminSelect.replaceChildren();
      data.users.filter((account) => account.role !== 'client').forEach((account) => {
        adminSelect.add(new Option(`${account.display_name || account.email} · ${account.role}`, String(account.id)));
      });
      await loadAdminEmployee();
    } catch (error) {
      adminStatus.textContent = error.message;
    }
  }

  adminSelect?.addEventListener('change', loadAdminEmployee);
  document.getElementById('admin-statutory-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      const data = await requestJson(`/api/auth/users/${adminSelect.value}/employee-details`, {
        method: 'PATCH', body: JSON.stringify(readStatutory('admin')),
      });
      fillStatutory('admin', data.employee);
      adminStatus.textContent = `Saved details for ${data.employee.name}.`;
    } catch (error) {
      adminStatus.textContent = error.message;
    }
  });

  window.addEventListener('difan:session-ready', () => {
    loadAdminPanel();
    if (isEmployee()) loadOwnStatutory();
    loadDirectory();
    if (isEmployee()) loadOwnPhone();
  });
});
