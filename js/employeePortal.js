document.addEventListener('DOMContentLoaded', () => {
  const approvalPanel = document.getElementById('hr-approval-panel');
  const registrationList = document.getElementById('employee-registration-list');
  const registrationStatus = document.getElementById('employee-registration-status');
  const refreshButton = document.getElementById('refresh-employee-registrations');
  const onboardingPanel = document.getElementById('account-onboarding-panel');
  const onboardingForm = document.getElementById('account-onboarding-form');
  const onboardingType = document.getElementById('onboarding-account-type');
  const onboardingNameField = document.getElementById('onboarding-name-field');
  const onboardingName = document.getElementById('onboarding-name');
  const onboardingStatus = document.getElementById('account-onboarding-status');
  const ratePanel = document.getElementById('container-rate-admin');
  const rateForm = document.getElementById('container-rate-form');
  const rateStatus = document.getElementById('container-rate-status');
  const employeeNavigation = document.getElementById('employees-navigation');
  const onboardingNavigation = document.getElementById('onboarding-navigation');
  const onboardingView = document.getElementById('view-onboarding');
  const onboardedAccountsPanel = document.getElementById('onboarded-accounts-panel');
  const onboardedAccountsList = document.getElementById('onboarded-accounts-list');
  const onboardedAccountsStatus = document.getElementById('onboarded-accounts-status');
  const enquiriesPanel = document.getElementById('transport-enquiries-panel');
  const enquiriesList = document.getElementById('transport-enquiries-list');
  const enquiriesStatus = document.getElementById('transport-enquiries-status');
  if (!approvalPanel || !registrationList || !rateForm) return;

  const adminRoles = new Set(['admin', 'hr', 'boss']);

  function getToken() {
    const token = localStorage.getItem('jwt_token');
    if (!token) throw new Error('Please sign in to continue.');
    return token;
  }

  async function apiRequest(path, options = {}) {
    const response = await fetch(window.DifanApp.apiUrl(path), {
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

  async function loadTransportEnquiries() {
    if (!enquiriesList || !enquiriesStatus) return;
    enquiriesList.replaceChildren();
    enquiriesStatus.textContent = 'Loading public transport enquiries...';
    try {
      const data = await apiRequest('/api/portal/transport-enquiries');
      if (!data.enquiries.length) {
        enquiriesStatus.textContent = 'There are no transport enquiries.';
        return;
      }
      enquiriesStatus.textContent = `${data.enquiries.length} transport ${data.enquiries.length === 1 ? 'enquiry' : 'enquiries'}.`;
      for (const enquiry of data.enquiries) {
        const card = document.createElement('article');
        card.className = 'workflow-record';
        const heading = document.createElement('h3');
        heading.textContent = `${enquiry.company_name} · ${enquiry.status}`;
        const details = document.createElement('p');
        details.textContent = `${enquiry.contact_name} · ${enquiry.origin} → ${enquiry.destination} · ${enquiry.cargo_description}${enquiry.tonnage ? ` · ${enquiry.tonnage} tonnes` : ''}${enquiry.pickup_date ? ` · Pickup ${enquiry.pickup_date}` : ''}`;
        const contact = document.createElement('p');
        contact.textContent = `${enquiry.email} · ${enquiry.phone} · Received ${new Date(enquiry.created_at).toLocaleString()}`;
        card.append(heading, details, contact);
        if (enquiry.notes) {
          const notes = document.createElement('p');
          notes.textContent = `Additional details: ${enquiry.notes}`;
          card.appendChild(notes);
        }
        const controls = document.createElement('div');
        controls.className = 'workflow-actions';
        const state = document.createElement('select');
        [
          ['OPEN', 'Open'],
          ['CONTACTED', 'Contacted'],
          ['CLOSED', 'Closed'],
        ].forEach(([value, label]) => state.add(new Option(label, value)));
        state.value = enquiry.status;
        const save = document.createElement('button');
        save.type = 'button';
        save.className = 'btn btn-secondary';
        save.textContent = 'Save follow-up status';
        save.addEventListener('click', async () => {
          save.disabled = true;
          try {
            await apiRequest(`/api/portal/transport-enquiries/${enquiry.id}`, {
              method: 'PATCH',
              body: JSON.stringify({ status: state.value }),
            });
            await loadTransportEnquiries();
          } catch (error) {
            enquiriesStatus.textContent = error.message || 'Unable to update enquiry status.';
            save.disabled = false;
          }
        });
        controls.append(state, save);
        card.appendChild(controls);
        enquiriesList.appendChild(card);
      }
    } catch (error) {
      enquiriesStatus.textContent = error.message || 'Unable to load transport enquiries.';
    }
  }

  async function loadOnboardedAccounts() {
    if (!onboardedAccountsList || !onboardedAccountsStatus) return;
    onboardedAccountsList.replaceChildren();
    onboardedAccountsStatus.textContent = 'Loading onboarded accounts...';
    try {
      const data = await apiRequest('/api/auth/users');
      const accounts = data.users.filter((account) =>
        account.role === 'client'
        || ['driver', 'mechanic', 'accountant', 'admin', 'hr', 'boss'].includes(account.role),
      );
      if (!accounts.length) {
        onboardedAccountsStatus.textContent = 'No onboarded accounts are available.';
        return;
      }
      onboardedAccountsStatus.textContent = `${accounts.length} onboarded client and employee account${accounts.length === 1 ? '' : 's'}.`;
      accounts.forEach((account) => {
        const card = document.createElement('article');
        card.className = 'workflow-record';
        const heading = document.createElement('h3');
        heading.textContent = `${account.display_name || account.company_name || account.email} · ${account.role}`;
        const details = document.createElement('p');
        details.textContent = `${account.email} · ${account.company_name} · ${account.account_status}`;
        card.append(heading, details);
        onboardedAccountsList.appendChild(card);
      });
    } catch (error) {
      onboardedAccountsStatus.textContent = error.message || 'Unable to load onboarded accounts.';
    }
  }

  async function refreshEmployeeTools() {
    const role = window.DifanApp?.state?.currentUser?.role;
    const isAdminOrHr = adminRoles.has(role);
    const canOnboard = ['hr', 'boss'].includes(role);
    approvalPanel.hidden = !isAdminOrHr;
    onboardingPanel.hidden = !canOnboard;
    if (onboardedAccountsPanel) onboardedAccountsPanel.hidden = !canOnboard;
    const rolePanel = document.getElementById('account-role-panel');
    if (rolePanel) rolePanel.hidden = !canOnboard;
    if (enquiriesPanel) enquiriesPanel.hidden = !isAdminOrHr;
    if (onboardingNavigation) onboardingNavigation.hidden = !canOnboard;
    if (onboardingView) onboardingView.hidden = !canOnboard;
    ratePanel.hidden = !isAdminOrHr;
    const rateNav = document.getElementById('ratesheets-navigation');
    const rateView = document.getElementById('view-ratesheets');
    if (rateNav) rateNav.hidden = !isAdminOrHr;
    if (rateView && !isAdminOrHr) rateView.hidden = true;
    if (employeeNavigation) employeeNavigation.hidden = !role || role === 'client';
    if (!isAdminOrHr) return;
    await loadRegistrations();
    if (canOnboard) await loadOnboardedAccounts();
  }

  function updateOnboardingFields() {
    const isEmployee = onboardingType.value !== 'client';
    onboardingNameField.hidden = !isEmployee;
    onboardingName.required = isEmployee;
  }

  onboardingType.addEventListener('change', updateOnboardingFields);
  updateOnboardingFields();
  onboardingForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const submitButton = document.getElementById('account-onboarding-submit');
    submitButton.disabled = true;
    onboardingStatus.textContent = 'Creating account and sending the temporary credentials...';
    try {
      const data = await apiRequest('/api/auth/users', {
        method: 'POST',
        body: JSON.stringify({
          role: onboardingType.value,
          company_name: document.getElementById('onboarding-company').value.trim(),
          email: document.getElementById('onboarding-email').value.trim(),
          display_name: onboardingName.value.trim(),
          phone: document.getElementById('onboarding-phone').value.trim(),
        }),
      });
      onboardingStatus.textContent = data.message;
      onboardingForm.reset();
      updateOnboardingFields();
      await loadOnboardedAccounts();
    } catch (error) {
      onboardingStatus.textContent = error.message || 'Unable to create the onboarding account.';
    } finally {
      submitButton.disabled = false;
    }
  });

  refreshButton.addEventListener('click', loadRegistrations);
  document.getElementById('refresh-transport-enquiries')?.addEventListener('click', loadTransportEnquiries);
  document.getElementById('refresh-onboarded-accounts')?.addEventListener('click', loadOnboardedAccounts);
  document.querySelector('[data-target-tab="booking"]')?.addEventListener('click', () => {
    if (adminRoles.has(window.DifanApp?.state?.currentUser?.role)) {
      loadTransportEnquiries();
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
