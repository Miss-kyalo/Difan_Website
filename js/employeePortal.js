document.addEventListener('DOMContentLoaded', () => {
  const approvalPanel = document.getElementById('hr-approval-panel');
  const registrationList = document.getElementById('employee-registration-list');
  const registrationStatus = document.getElementById('employee-registration-status');
  const refreshButton = document.getElementById('refresh-employee-registrations');
  const ratePanel = document.getElementById('container-rate-admin');
  const rateForm = document.getElementById('container-rate-form');
  const rateStatus = document.getElementById('container-rate-status');
  const employeeNavigation = document.getElementById('employees-navigation');
  if (!approvalPanel || !registrationList || !rateForm) return;

  const adminRoles = new Set(['admin', 'hr']);

  function getToken() {
    const token = localStorage.getItem('jwt_token');
    if (!token) throw new Error('Please sign in to continue.');
    return token;
  }

  async function apiRequest(path, options = {}) {
    const response = await fetch(`http://localhost:5000${path}`, {
      ...options,
      headers: {
        Authorization: `Bearer ${getToken()}`,
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...options.headers,
      },
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.message || 'The request could not be completed.');
    return data;
  }

  function renderRegistration(record) {
    const card = document.createElement('article');
    card.className = 'shipment-access-card';
    const info = document.createElement('div');
    const name = document.createElement('strong');
    name.textContent = `${record.display_name || record.driver_name || 'Employee'} · ${record.role}`;
    const email = document.createElement('p');
    email.textContent = record.email;
    const state = document.createElement('p');
    state.textContent = `Submitted as ${record.role}; registration status: ${record.account_status}.`;
    info.append(name, email, state);

    const approveButton = document.createElement('button');
    approveButton.type = 'button';
    approveButton.className = 'btn btn-primary';
    approveButton.textContent = 'Approve registration';
    approveButton.addEventListener('click', async () => {
      approveButton.disabled = true;
      registrationStatus.textContent = `Approving ${record.display_name || record.email}...`;
      try {
        const result = await apiRequest(
          `/api/auth/employee-registrations/${encodeURIComponent(record.id)}/approve`,
          { method: 'PATCH' },
        );
        registrationStatus.textContent = result.message;
        await loadRegistrations();
      } catch (error) {
        registrationStatus.textContent = error.message || 'Unable to approve this registration.';
        approveButton.disabled = false;
      }
    });
    card.append(info, approveButton);
    registrationList.appendChild(card);
  }

  async function loadRegistrations() {
    registrationList.replaceChildren();
    registrationStatus.textContent = 'Loading pending employee registrations...';
    try {
      const data = await apiRequest('/api/auth/employee-registrations');
      if (!data.registrations.length) {
        registrationStatus.textContent = 'There are no pending employee registrations.';
        return;
      }
      registrationStatus.textContent = `${data.registrations.length} registration${data.registrations.length === 1 ? '' : 's'} awaiting HR approval.`;
      data.registrations.forEach(renderRegistration);
    } catch (error) {
      registrationStatus.textContent = error.message || 'Unable to load registrations.';
    }
  }

  async function loadContainerRates() {
    rateStatus.textContent = 'Loading current rates...';
    try {
      const data = await apiRequest('/api/portal/container-rates');
      const inputBySize = {
        '20ft': document.getElementById('container-rate-20ft'),
        '40ft': document.getElementById('container-rate-40ft'),
      };
      data.rates.forEach((rate) => {
        if (inputBySize[rate.size]) inputBySize[rate.size].value = rate.rate_kes;
      });
      rateStatus.textContent = data.rates.length
        ? 'Rates shown are VAT-exclusive.'
        : 'No container rates have been configured yet.';
    } catch (error) {
      rateStatus.textContent = error.message || 'Unable to load container rates.';
    }
  }

  async function refreshEmployeeTools() {
    const role = window.DifanApp?.state?.currentUser?.role;
    const isAdminOrHr = adminRoles.has(role);
    approvalPanel.hidden = !isAdminOrHr;
    ratePanel.hidden = !isAdminOrHr;
    if (employeeNavigation) employeeNavigation.hidden = !role || role === 'client';
    if (!isAdminOrHr) return;
    await Promise.all([loadRegistrations(), loadContainerRates()]);
  }

  refreshButton.addEventListener('click', loadRegistrations);
  document.querySelector('[data-target-tab="employees"]')?.addEventListener('click', () => {
    if (adminRoles.has(window.DifanApp?.state?.currentUser?.role)) {
      loadRegistrations();
      loadContainerRates();
    }
  });

  rateForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const submitButton = rateForm.querySelector('button[type="submit"]');
    submitButton.disabled = true;
    rateStatus.textContent = 'Saving both container rates...';
    try {
      const rates = {
        '20ft': Number(document.getElementById('container-rate-20ft').value),
        '40ft': Number(document.getElementById('container-rate-40ft').value),
      };
      const data = await apiRequest('/api/portal/container-rates', {
        method: 'PUT',
        body: JSON.stringify({ rates }),
      });
      rateStatus.textContent = `Saved VAT-exclusive rates: ${data.rates.map((rate) => `${rate.size}: KES ${Number(rate.rate_kes).toLocaleString('en-KE', { minimumFractionDigits: 2 })}`).join(' · ')}.`;
    } catch (error) {
      rateStatus.textContent = error.message || 'Unable to save container rates.';
    } finally {
      submitButton.disabled = false;
    }
  });

  window.addEventListener('difan:session-ready', refreshEmployeeTools);
});
