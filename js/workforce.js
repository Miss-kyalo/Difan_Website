document.addEventListener('DOMContentLoaded', () => {
  const nav = document.getElementById('workforce-navigation');
  const lockoutPanel = document.getElementById('workforce-lockout-panel');
  const pendingList = document.getElementById('workforce-pending-list');
  const signingPanel = document.getElementById('workforce-signing-panel');
  const signingTitle = document.getElementById('workforce-signing-title');
  const signingDocument = document.getElementById('workforce-signing-document');
  const confirmations = document.getElementById('workforce-signing-confirmations');
  const signatureCanvas = document.getElementById('workforce-signature-canvas');
  const signatureContext = signatureCanvas.getContext('2d');
  const submitSignature = document.getElementById('workforce-submit-signature');
  const signatureStatus = document.getElementById('workforce-signing-status');
  const emergencyForm = document.getElementById('workforce-emergency-form');
  const emergencyStatus = document.getElementById('workforce-emergency-status');
  const emergencyType = document.getElementById('workforce-emergency-type');
  const emergencyVehicleField = document.getElementById('workforce-emergency-vehicle-field');
  const emergencyVehicle = document.getElementById('workforce-emergency-vehicle');
  const caseForm = document.getElementById('workforce-case-form');
  const payrollForm = document.getElementById('workforce-payroll-form');
  const payrollYear = document.getElementById('workforce-payroll-year');
  const noticeForm = document.getElementById('workforce-notice-form');
  const clientRatingPanel = document.getElementById('client-rating-panel');
  const clientRatingForm = document.getElementById('client-rating-form');
  const driverClientRatingPanel = document.getElementById('workforce-driver-client-rating-panel');
  const driverClientRatingForm = document.getElementById('workforce-driver-client-rating-form');

  if (!nav || !lockoutPanel || !pendingList || !signatureCanvas || !emergencyForm) return;

  const apiRoot = 'http://localhost:5000';
  const employeeRoles = new Set(['driver', 'mechanic', 'accountant', 'admin', 'hr', 'boss']);
  const hrRoles = new Set(['hr', 'boss']);
  let pendingTasks = [];
  let selectedTask = null;
  let hasInk = false;
  let ratingShipment = null;
  let dashboardTimer = null;

  function currentUser() {
    return window.DifanApp?.state?.currentUser;
  }

  function authHeaders() {
    const token = localStorage.getItem('jwt_token');
    if (!token) throw new Error('Please sign in to continue.');
    return { Authorization: `Bearer ${token}` };
  }

  async function apiRequest(path, options = {}) {
    const isFormData = options.body instanceof FormData;
    const response = await fetch(`${apiRoot}${path}`, {
      ...options,
      headers: {
        ...authHeaders(),
        ...(!isFormData && options.body ? { 'Content-Type': 'application/json' } : {}),
        ...options.headers,
      },
    });
    const contentType = response.headers.get('Content-Type') || '';
    const result = contentType.includes('application/json')
      ? await response.json()
      : { message: 'The server returned an unexpected response.' };
    if (!response.ok) {
      if (response.status === 423) {
        window.DifanApp.state.workforceLockout = true;
      }
      throw new Error(result.message || 'The request could not be completed.');
    }
    return result;
  }

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }

  async function downloadPrivatePdf(path, filename, statusElement) {
    try {
      const response = await fetch(`${apiRoot}${path}`, { headers: authHeaders() });
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.message || 'The PDF could not be downloaded.');
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = objectUrl;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
      if (statusElement) statusElement.textContent = `${filename} downloaded.`;
    } catch (error) {
      if (statusElement) statusElement.textContent = error.message || 'The PDF could not be downloaded.';
      else window.DifanApp.showToast(error.message || 'The PDF could not be downloaded.', 'error');
    }
  }

  function populatePayrollYears() {
    if (!payrollYear) return;
    const currentYear = new Date().getFullYear();
    payrollYear.replaceChildren();
    for (let year = currentYear; year >= currentYear - 9; year -= 1) {
      payrollYear.add(new Option(String(year), String(year)));
    }
    payrollYear.value = String(currentYear);
  }

  function ensureDeviceId() {
    let id = localStorage.getItem('difan_browser_device_id');
    if (!id) {
      id = globalThis.crypto?.randomUUID?.() || `browser-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      localStorage.setItem('difan_browser_device_id', id);
    }
    return id;
  }

  function resetCanvas() {
    signatureContext.clearRect(0, 0, signatureCanvas.width, signatureCanvas.height);
    signatureContext.fillStyle = '#ffffff';
    signatureContext.fillRect(0, 0, signatureCanvas.width, signatureCanvas.height);
    signatureContext.strokeStyle = '#1b3b2b';
    signatureContext.lineWidth = 3;
    signatureContext.lineCap = 'round';
    signatureContext.lineJoin = 'round';
    hasInk = false;
  }

  let drawing = false;
  function canvasPoint(event) {
    const bounds = signatureCanvas.getBoundingClientRect();
    return {
      x: (event.clientX - bounds.left) * signatureCanvas.width / bounds.width,
      y: (event.clientY - bounds.top) * signatureCanvas.height / bounds.height,
    };
  }
  signatureCanvas.addEventListener('pointerdown', (event) => {
    event.preventDefault();
    drawing = true;
    signatureCanvas.setPointerCapture(event.pointerId);
    const point = canvasPoint(event);
    signatureContext.beginPath();
    signatureContext.moveTo(point.x, point.y);
  });
  signatureCanvas.addEventListener('pointermove', (event) => {
    if (!drawing) return;
    event.preventDefault();
    const point = canvasPoint(event);
    signatureContext.lineTo(point.x, point.y);
    signatureContext.stroke();
    hasInk = true;
  });
  signatureCanvas.addEventListener('pointerup', () => { drawing = false; });
  signatureCanvas.addEventListener('pointercancel', () => { drawing = false; });
  document.getElementById('workforce-clear-signature').addEventListener('click', resetCanvas);
  resetCanvas();

  function setLockout(enabled) {
    window.DifanApp.state.workforceLockout = enabled;
    document.body.classList.toggle('workforce-navigation-lockout', enabled);
    lockoutPanel.hidden = !enabled;
    if (enabled) {
      const link = document.querySelector('[data-target-tab="workforce"]');
      if (link && window.DifanApp.state.activeTab !== 'workforce') link.click();
    }
  }

  function taskLabel(task) {
    return task.kind === 'payroll'
      ? `Paystub · ${task.record.pay_period}`
      : `${task.record.notice_type === 'TERMS_UPDATE' ? 'Terms update' : 'Consent agreement'} · ${task.record.title}`;
  }

  function selectTask(task) {
    selectedTask = task;
    signingPanel.hidden = false;
    signingTitle.textContent = taskLabel(task);
    signingDocument.replaceChildren();
    confirmations.replaceChildren();
    const text = task.kind === 'payroll'
      ? [
        `Pay period: ${task.record.pay_period}`,
        `Gross salary: ${window.DifanApp.formatCurrency(task.record.gross_pay)}`,
        `Standard payroll deductions: ${window.DifanApp.formatCurrency(task.record.deductions)}`,
        `NSSF: ${task.record.nssf_deduction == null ? 'Not entered' : window.DifanApp.formatCurrency(task.record.nssf_deduction)}`,
        `SHIF: ${task.record.shif_deduction == null ? 'Not entered' : window.DifanApp.formatCurrency(task.record.shif_deduction)}`,
        `Housing levy: ${task.record.housing_levy_deduction == null ? 'Not entered' : window.DifanApp.formatCurrency(task.record.housing_levy_deduction)}`,
        `Taxable pay: ${task.record.taxable_pay == null ? 'Not entered' : window.DifanApp.formatCurrency(task.record.taxable_pay)}`,
        `Tax charged: ${task.record.tax_charged == null ? 'Not entered' : window.DifanApp.formatCurrency(task.record.tax_charged)}`,
        `Personal relief: ${task.record.personal_relief == null ? 'Not entered' : window.DifanApp.formatCurrency(task.record.personal_relief)}`,
        `Other reliefs: ${task.record.other_reliefs == null ? 'Not entered' : window.DifanApp.formatCurrency(task.record.other_reliefs)}`,
        `PAYE: ${task.record.paye_tax == null ? 'Not entered' : window.DifanApp.formatCurrency(task.record.paye_tax)}`,
        `Salary Advance / Early Cashout: ${window.DifanApp.formatCurrency(task.record.salary_advance)}`,
        `Net pay: ${window.DifanApp.formatCurrency(task.record.net_pay)}`,
      ].join('\n')
      : `${task.record.body}\n\nNotice version: ${task.record.version}`;
    signingDocument.textContent = text;
    if (task.kind === 'payroll') {
      [
        ['receipt_confirmed', 'I acknowledge receipt of this paystub.'],
        ['paystub_confirmed', 'I have reviewed and acknowledge the listed paystub amounts.'],
      ].forEach(([name, label]) => addConfirmation(name, label));
      if (Number(task.record.salary_advance) > 0) {
        addConfirmation(
          'advance_confirmed',
          `Separate Advance Consent & Legal Notice: I acknowledge and consent that ${window.DifanApp.formatCurrency(task.record.salary_advance)} is a Salary Advance / Early Cashout and is to be offset against final trip settlements as permitted by applicable law and the applicable written agreement. This acknowledgement does not waive rights under applicable law.`,
        );
      }
    } else {
      addConfirmation('acknowledged', 'I have read and acknowledge this notice.');
    }
    signatureStatus.textContent = '';
    resetCanvas();
    signingPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function addConfirmation(name, label) {
    const wrapper = node('label', undefined, 'field');
    const input = node('input');
    input.type = 'checkbox';
    input.name = name;
    input.required = true;
    wrapper.append(input, document.createTextNode(` ${label}`));
    confirmations.appendChild(wrapper);
  }

  function renderPendingTasks() {
    pendingList.replaceChildren();
    if (!pendingTasks.length) {
      pendingList.appendChild(node('p', 'No pending acknowledgements.'));
      signingPanel.hidden = true;
      selectedTask = null;
      setLockout(false);
      return;
    }
    setLockout(true);
    pendingTasks.forEach((task) => {
      const article = node('article', undefined, 'workflow-card');
      article.appendChild(node('h3', taskLabel(task)));
      if (task.kind === 'payroll' && Number(task.record.salary_advance) > 0) {
        article.appendChild(node(
          'p',
          `Separate acknowledgment required for Salary Advance / Early Cashout: ${window.DifanApp.formatCurrency(task.record.salary_advance)}.`,
        ));
      }
      const review = node('button', 'Review and sign', 'btn btn-primary');
      review.type = 'button';
      review.addEventListener('click', () => selectTask(task));
      article.appendChild(review);
      pendingList.appendChild(article);
    });
    if (!selectedTask || !pendingTasks.includes(selectedTask)) selectTask(pendingTasks[0]);
  }

  function renderPayroll(records, currentUserId, isManager) {
    const employeeList = document.getElementById('workforce-payroll-list');
    const adminList = document.getElementById('workforce-payroll-admin-list');
    employeeList.replaceChildren();
    adminList.replaceChildren();
    const ownRecords = records.filter((record) => record.employee_id === currentUserId);
    ownRecords.forEach((record) => {
      const article = node('article', undefined, 'workflow-card');
      article.appendChild(node(
        'h3',
        `${record.pay_period} · ${record.status.replaceAll('_', ' ')}`,
      ));
      article.appendChild(node(
        'p',
        `Gross: ${window.DifanApp.formatCurrency(record.gross_pay)} · Standard payroll deductions: ${window.DifanApp.formatCurrency(record.deductions)} · Salary Advance / Early Cashout: ${window.DifanApp.formatCurrency(record.salary_advance)} · Net: ${window.DifanApp.formatCurrency(record.net_pay)}`,
      ));
      const payslipDownload = node('button', 'Download payslip PDF', 'btn btn-secondary');
      payslipDownload.type = 'button';
      payslipDownload.addEventListener('click', () => {
        const safePeriod = record.pay_period.replace(/[^A-Za-z0-9_-]+/g, '-') || 'pay-period';
        downloadPrivatePdf(
          `/api/portal/payroll/${record.id}/pdf`,
          `${safePeriod}-payslip.pdf`,
          document.getElementById('workforce-p9-status'),
        );
      });
      article.appendChild(payslipDownload);
      if (record.signed_pdf_sha256) {
        const download = node('a', 'Download signed immutable PDF');
        download.href = `${apiRoot}/api/portal/payroll/${record.id}/signed-document`;
        download.target = '_blank';
        download.rel = 'noopener';
        download.textContent += ` · SHA-256 ${record.signed_pdf_sha256}`;
        download.addEventListener('click', async (event) => {
          event.preventDefault();
          try {
            const response = await fetch(download.href, { headers: authHeaders() });
            if (!response.ok) {
              const data = await response.json();
              throw new Error(data.message || 'The PDF could not be downloaded.');
            }
            const blob = await response.blob();
            const anchor = document.createElement('a');
            anchor.href = URL.createObjectURL(blob);
            anchor.download = `${record.pay_period}-signed-paystub.pdf`;
            anchor.click();
            URL.revokeObjectURL(anchor.href);
          } catch (error) {
            window.DifanApp.showToast(error.message, 'error');
          }
        });
        article.appendChild(download);
      }
      employeeList.appendChild(article);
    });
    if (!ownRecords.length) employeeList.appendChild(node('p', 'No paystubs are available yet.'));

    if (!isManager) return;
    records.forEach((record) => {
      const article = node('article', undefined, 'workflow-card');
      article.appendChild(node(
        'h3',
        `${record.employee_name} · ${record.pay_period} · ${record.status.replaceAll('_', ' ')}`,
      ));
      article.appendChild(node(
        'p',
        `Deductions: ${window.DifanApp.formatCurrency(record.deductions)} · Salary Advance / Early Cashout: ${window.DifanApp.formatCurrency(record.salary_advance)} · Net: ${window.DifanApp.formatCurrency(record.net_pay)}`,
      ));
      const adminPayslipDownload = node('button', 'Download payslip PDF', 'btn btn-secondary');
      adminPayslipDownload.type = 'button';
      adminPayslipDownload.addEventListener('click', () => {
        const safePeriod = record.pay_period.replace(/[^A-Za-z0-9_-]+/g, '-') || 'pay-period';
        downloadPrivatePdf(
          `/api/portal/payroll/${record.id}/pdf`,
          `${safePeriod}-payslip.pdf`,
          document.getElementById('workforce-p9-status'),
        );
      });
      article.appendChild(adminPayslipDownload);
      if (record.status === 'PENDING_APPROVAL') {
        const approve = node('button', 'Approve and publish paystub', 'btn btn-secondary');
        approve.type = 'button';
        approve.addEventListener('click', async () => {
          approve.disabled = true;
          try {
            await apiRequest(`/api/portal/payroll/${record.id}/approve`, { method: 'PATCH' });
            await refreshSessionData();
          } catch (error) {
            approve.disabled = false;
            window.DifanApp.showToast(error.message, 'error');
          }
        });
        article.appendChild(approve);
      }
      adminList.appendChild(article);
    });
  }

  function renderNotices(notices) {
    const container = document.getElementById('workforce-notice-list');
    container.replaceChildren();
    notices.forEach((notice) => {
      const article = node('article', undefined, 'workflow-card');
      article.appendChild(node('h3', `${notice.title} · ${notice.version}`));
      article.appendChild(node('p', notice.body));
      if (notice.signed_document_url) {
        const download = node('a', 'Download signed acknowledgement');
        download.href = `${apiRoot}${notice.signed_document_url}`;
        download.target = '_blank';
        download.rel = 'noopener';
        article.appendChild(download);
      }
      container.appendChild(article);
    });
    if (!notices.length) container.appendChild(node('p', 'No current terms updates or consent agreements.'));
  }

  async function captureLocation() {
    const locationStatus = document.getElementById('workforce-location-status');
    if (!navigator.geolocation) {
      locationStatus.textContent = 'GPS is unavailable in this browser; this status will be recorded.';
      return { latitude: null, longitude: null };
    }
    locationStatus.textContent = 'Requesting GPS coordinates...';
    return new Promise((resolve) => {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          locationStatus.textContent = 'GPS coordinates captured for this acknowledgement.';
          resolve({
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
          });
        },
        () => {
          locationStatus.textContent = 'GPS was unavailable or declined; this status will be recorded.';
          resolve({ latitude: null, longitude: null });
        },
        { enableHighAccuracy: true, timeout: 8000, maximumAge: 0 },
      );
    });
  }

  submitSignature.addEventListener('click', async () => {
    if (!selectedTask) return;
    if (!hasInk) {
      signatureStatus.textContent = 'Draw your signature before submitting.';
      return;
    }
    const checkboxes = Array.from(confirmations.querySelectorAll('input[type="checkbox"]'));
    if (checkboxes.some((checkbox) => !checkbox.checked)) {
      signatureStatus.textContent = 'Confirm every acknowledgement before signing.';
      return;
    }
    submitSignature.disabled = true;
    signatureStatus.textContent = 'Capturing signature metadata and saving the immutable PDF...';
    try {
      const location = await captureLocation();
      const payload = {
        signature_png: signatureCanvas.toDataURL('image/png'),
        device_id: ensureDeviceId(),
        ...location,
      };
      let result;
      if (selectedTask.kind === 'payroll') {
        payload.receipt_confirmed = true;
        payload.paystub_confirmed = true;
        payload.advance_confirmed = Number(selectedTask.record.salary_advance) <= 0
          || confirmations.querySelector('[name="advance_confirmed"]').checked;
        result = await apiRequest(`/api/portal/payroll/${selectedTask.record.id}/sign`, {
          method: 'POST',
          body: JSON.stringify(payload),
        });
      } else {
        payload.acknowledged = true;
        result = await apiRequest(`/api/portal/workforce/notices/${selectedTask.record.id}/acknowledge`, {
          method: 'POST',
          body: JSON.stringify(payload),
        });
      }
      signatureStatus.textContent = `Signed at ${result.signed_at || result.acknowledged_at}. SHA-256: ${result.sha256}`;
      selectedTask = null;
      await refreshSessionData();
    } catch (error) {
      signatureStatus.textContent = error.message || 'The acknowledgement could not be signed.';
    } finally {
      submitSignature.disabled = false;
    }
  });

  function updateEmergencyVehicleRequirement() {
    const requiresVehicle = emergencyType.value === 'ROADSIDE_BREAKDOWN';
    emergencyVehicleField.hidden = !requiresVehicle;
    emergencyVehicle.required = requiresVehicle;
  }
  emergencyType.addEventListener('change', updateEmergencyVehicleRequirement);
  updateEmergencyVehicleRequirement();

  emergencyForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const submit = emergencyForm.querySelector('button[type="submit"]');
    submit.disabled = true;
    emergencyStatus.textContent = 'Submitting safety report...';
    try {
      const data = await apiRequest('/api/portal/workforce/emergency', {
        method: 'POST',
        body: JSON.stringify({
          report_type: emergencyType.value,
          vehicle_registration: emergencyVehicle.value.trim(),
          location: document.getElementById('workforce-emergency-location').value.trim(),
          description: document.getElementById('workforce-emergency-description').value.trim(),
        }),
      });
      emergencyStatus.textContent = `${data.message} Reference: ${data.reference}.`;
      emergencyForm.reset();
      emergencyType.dispatchEvent(new Event('change'));
    } catch (error) {
      emergencyStatus.textContent = error.message || 'Unable to record the safety report.';
    } finally {
      submit.disabled = false;
    }
  });

  function renderDriverScores(score) {
    const container = document.getElementById('workforce-driver-score');
    container.replaceChildren();
    [
      `Composite score: ${score.score}`,
      `Safety: ${score.safety_score}`,
      `Customer rating: ${score.customer_rating_average}/5 (${score.customer_rating_count} ratings)`,
      `On-time delivery: ${score.on_time_score}% (${score.on_time_deliveries}/${score.scored_deliveries})`,
      `HR infraction penalty (90-day decay): ${score.hr_infraction_penalty}`,
    ].forEach((label) => container.appendChild(node('p', label)));
    const feedback = document.getElementById('workforce-driver-feedback');
    feedback.replaceChildren();
    score.customer_feedback.forEach((item) => {
      feedback.appendChild(node(
        'p',
        `${item.tracking_number} · ${item.stars}/5 · ${item.feedback || 'No written feedback'}`,
        'workflow-card',
      ));
    });
  }

  async function loadLeaderboard() {
    const container = document.getElementById('workforce-leaderboard');
    container.replaceChildren();
    try {
      const response = await fetch(`${apiRoot}/api/portal/workforce/leaderboard`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || 'Leaderboard could not be loaded.');
      if (!data.drivers.length) container.appendChild(node('p', 'No drivers have opted in to the public leaderboard.'));
      data.drivers.forEach((driver) => {
        container.appendChild(node('p', `#${driver.rank} · ${driver.handle} · ${driver.score}` , 'workflow-card'));
      });
    } catch (error) {
      container.appendChild(node('p', error.message || 'Leaderboard unavailable.'));
    }
  }

  async function loadClientLeaderboard() {
    const container = document.getElementById('workforce-client-leaderboard');
    container.replaceChildren();
    try {
      const data = await apiRequest('/api/portal/workforce/client-leaderboard');
      if (!data.clients.length) {
        container.appendChild(node('p', 'No client facility ratings have been submitted yet.'));
        return;
      }
      data.clients.forEach((client) => {
        const card = node('article', undefined, 'workflow-card');
        card.appendChild(node('h3', `#${client.rank} · ${client.company_name}`));
        card.appendChild(node(
          'p',
          `Average ${client.average_rating}/5 from ${client.rating_count} rating(s) · Loading speed ${client.loading_speed_average}/5 · Facility friendliness ${client.facility_friendliness_average}/5`,
        ));
        client.feedback.forEach((item) => {
          card.appendChild(node('p', `${item.tracking_number}: ${item.feedback}`));
        });
        container.appendChild(card);
      });
    } catch (error) {
      container.appendChild(node('p', error.message || 'Client ratings could not be loaded.'));
    }
  }

  async function loadDriverClientRatingOptions() {
    const panel = driverClientRatingPanel;
    const select = document.getElementById('workforce-driver-client-shipment');
    if (!panel || !select) return;
    const isDriver = currentUser()?.role === 'driver';
    panel.hidden = !isDriver;
    if (!isDriver) return;
    select.replaceChildren(new Option('Select a completed shipment', ''));
    try {
      const data = await apiRequest('/api/portal/workforce/driver/rateable-shipments');
      data.shipments.forEach((shipment) => {
        select.add(new Option(
          `${shipment.tracking_number} · ${shipment.company_name} · ${shipment.destination}`,
          shipment.tracking_number,
        ));
      });
      const status = document.getElementById('workforce-driver-client-rating-status');
      status.textContent = data.shipments.length
        ? 'Ratings are available after signed proof of delivery.'
        : 'No unrated completed deliveries are available.';
    } catch (error) {
      document.getElementById('workforce-driver-client-rating-status').textContent =
        error.message || 'Completed shipments could not be loaded.';
    }
  }

  async function loadHrDashboard() {
    if (!hrRoles.has(currentUser()?.role)) return;
    const statusList = document.getElementById('workforce-driver-status-list');
    const caseList = document.getElementById('workforce-case-list');
    const emergencyList = document.getElementById('workforce-emergency-list');
    try {
      const data = await apiRequest('/api/portal/workforce/hr-dashboard');
      const driverSelect = document.getElementById('workforce-case-driver');
      const payrollEmployee = document.getElementById('workforce-payroll-employee');
      statusList.replaceChildren();
      caseList.replaceChildren();
      emergencyList.replaceChildren();
      driverSelect.replaceChildren();
      const blank = new Option('Select driver', '');
      driverSelect.appendChild(blank);
      for (const driver of data.drivers) {
        const option = new Option(`${driver.name} (${driver.driver_id})`, driver.id);
        driverSelect.appendChild(option);
        const card = node('article', undefined, 'workflow-card');
        card.appendChild(node('h3', `${driver.name} · ${driver.driver_id}`));
        card.appendChild(node(
          'p',
          `${driver.employment_status}${driver.leave_type ? ` (${driver.leave_type})` : ''} · score ${driver.score.score}`,
        ));
        const form = document.createElement('form');
        form.className = 'workflow-grid';
        const status = document.createElement('select');
        [
          ['ACTIVE', 'Active'],
          ['ON_LEAVE', 'On Leave (Sick/Vacation)'],
          ['SUSPENDED', 'Suspended (Disciplinary)'],
          ['OFF_DUTY', 'Off-Duty'],
        ].forEach(([value, label]) => status.add(new Option(label, value)));
        status.value = driver.employment_status;
        const leave = document.createElement('select');
        leave.add(new Option('Sick leave', 'SICK'));
        leave.add(new Option('Vacation leave', 'VACATION'));
        leave.value = driver.leave_type || 'SICK';
        leave.hidden = status.value !== 'ON_LEAVE';
        status.addEventListener('change', () => { leave.hidden = status.value !== 'ON_LEAVE'; });
        const note = document.createElement('input');
        note.maxLength = 500;
        note.placeholder = 'Status note (optional)';
        note.value = driver.status_note || '';
        const save = node('button', 'Update availability', 'btn btn-secondary');
        save.type = 'submit';
        form.append(status, leave, note, save);
        form.addEventListener('submit', async (event) => {
          event.preventDefault();
          save.disabled = true;
          try {
            await apiRequest(`/api/portal/workforce/drivers/${driver.id}/status`, {
              method: 'PATCH',
              body: JSON.stringify({ status: status.value, leave_type: leave.value, note: note.value }),
            });
            await loadHrDashboard();
          } catch (error) {
            window.DifanApp.showToast(error.message, 'error');
            save.disabled = false;
          }
        });
        card.appendChild(form);
        statusList.appendChild(card);
      }
      if (!data.drivers.length) statusList.appendChild(node('p', 'No driver accounts are available.'));
      for (const item of data.cases) {
        const card = node('article', undefined, 'workflow-card');
        card.appendChild(node('h3', `${item.employee_name} · ${item.case_type.replaceAll('_', ' ')}`));
        card.appendChild(node('p', `${item.severity.replaceAll('_', ' ')} · ${item.severity_points} points · ${item.status}`));
        card.appendChild(node('p', item.details));
        card.appendChild(node('p', `Dispute deadline: ${new Date(item.dispute_deadline_at).toLocaleString()}`));
        item.evidence.forEach((file) => addEvidenceLink(card, file));
        item.rebuttals.forEach((rebuttal) => {
          card.appendChild(node('p', `Driver rebuttal: ${rebuttal.details}`));
          rebuttal.evidence.forEach((file) => addEvidenceLink(card, file));
        });
        if (['DISPUTED', 'UNDER_REVIEW', 'DISPUTE_OPEN'].includes(item.status)) {
          ['Uphold infraction', 'Dismiss infraction'].forEach((label, index) => {
            const resolve = node('button', label, 'btn btn-secondary');
            resolve.type = 'button';
            resolve.addEventListener('click', async () => {
              try {
                await apiRequest(`/api/portal/workforce/cases/${item.id}/resolve`, {
                  method: 'PATCH',
                  body: JSON.stringify({ upheld: index === 0, resolution_note: '' }),
                });
                await loadHrDashboard();
              } catch (error) {
                window.DifanApp.showToast(error.message, 'error');
              }
            });
            card.appendChild(resolve);
          });
        }
        caseList.appendChild(card);
      }
      if (!data.cases.length) caseList.appendChild(node('p', 'No HR records have been issued.'));
      data.emergencies.forEach((report) => {
        emergencyList.appendChild(node(
          'article',
          `${report.reference} · ${report.report_type.replaceAll('_', ' ')} · ${report.employee_name} · ${report.location} · ${report.description}`,
          'workflow-card',
        ));
      });
      if (!data.emergencies.length) emergencyList.appendChild(node('p', 'No safety reports have been submitted.'));
      await loadClientLeaderboard();

      const userResponse = await apiRequest('/api/auth/users');
      const employeeOptions = userResponse.users.filter((user) => employeeRoles.has(user.role));
      const p9Employee = document.getElementById('workforce-p9-employee');
      payrollEmployee.replaceChildren();
      p9Employee.replaceChildren();
      payrollEmployee.appendChild(new Option('Select employee', ''));
      p9Employee.appendChild(new Option('Select employee', ''));
      employeeOptions.forEach((user) => {
        const label = `${user.display_name || user.driver_name || user.email} · ${user.role}`;
        payrollEmployee.add(new Option(label, user.id));
        p9Employee.add(new Option(label, user.id));
      });
      renderPayroll(
        (await apiRequest(`/api/portal/payroll?year=${encodeURIComponent(payrollYear.value)}`)).slips,
        currentUser().id,
        true,
      );
    } catch (error) {
      window.DifanApp.showToast(error.message || 'HR dashboard could not be refreshed.', 'error');
    }
  }

  function addEvidenceLink(container, file) {
    const link = node('a', `${file.filename} · SHA-256 ${file.sha256}`);
    link.href = `${apiRoot}${file.download_url}`;
    link.target = '_blank';
    link.rel = 'noopener';
    link.addEventListener('click', async (event) => {
      event.preventDefault();
      try {
        const response = await fetch(link.href, { headers: authHeaders() });
        if (!response.ok) {
          const data = await response.json();
          throw new Error(data.message || 'Evidence could not be downloaded.');
        }
        const blob = await response.blob();
        const anchor = document.createElement('a');
        anchor.href = URL.createObjectURL(blob);
        anchor.download = file.filename;
        anchor.click();
        URL.revokeObjectURL(anchor.href);
      } catch (error) {
        window.DifanApp.showToast(error.message, 'error');
      }
    });
    container.appendChild(link);
  }

  async function loadEmployeeCases() {
    const user = currentUser();
    if (hrRoles.has(user?.role)) return;
    const list = document.getElementById('workforce-driver-case-list');
    document.getElementById('workforce-driver-cases').hidden = user?.role !== 'driver';
    list.replaceChildren();
    try {
      const data = await apiRequest('/api/portal/workforce/cases');
      for (const item of data.cases) {
        const card = node('article', undefined, 'workflow-card');
        card.appendChild(node('h3', `${item.case_type.replaceAll('_', ' ')} · ${item.severity.replaceAll('_', ' ')}`));
        card.appendChild(node('p', item.details));
        card.appendChild(node('p', `Status: ${item.status}. Rebuttal deadline: ${new Date(item.dispute_deadline_at).toLocaleString()}`));
        item.evidence.forEach((file) => addEvidenceLink(card, file));
        if (['DISPUTE_OPEN', 'DISPUTED'].includes(item.status) && !item.rebuttals.length) {
          const form = document.createElement('form');
          form.className = 'workflow-form';
          const details = document.createElement('textarea');
          details.required = true;
          details.maxLength = 3000;
          details.placeholder = 'Your written rebuttal';
          const uploads = document.createElement('input');
          uploads.type = 'file';
          uploads.multiple = true;
          uploads.accept = 'application/pdf,image/jpeg,image/png,image/webp';
          const submit = node('button', 'Submit rebuttal', 'btn btn-secondary');
          submit.type = 'submit';
          form.append(details, uploads, submit);
          form.addEventListener('submit', async (event) => {
            event.preventDefault();
            const body = new FormData();
            body.append('details', details.value.trim());
            Array.from(uploads.files).forEach((file) => body.append('evidence', file));
            submit.disabled = true;
            try {
              await apiRequest(`/api/portal/workforce/cases/${item.id}/dispute`, {
                method: 'POST',
                body,
              });
              await loadEmployeeCases();
              await refreshSessionData();
            } catch (error) {
              window.DifanApp.showToast(error.message, 'error');
              submit.disabled = false;
            }
          });
          card.appendChild(form);
        }
        item.rebuttals.forEach((rebuttal) => card.appendChild(node('p', `Your rebuttal: ${rebuttal.details}`)));
        list.appendChild(card);
      }
      if (!data.cases.length) list.appendChild(node('p', 'There are no HR records on your profile.'));
    } catch (error) {
      list.appendChild(node('p', error.message || 'HR records could not be loaded.'));
    }
  }

  caseForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const status = document.getElementById('workforce-case-status');
    const submit = caseForm.querySelector('button[type="submit"]');
    const body = new FormData();
    body.append('employee_id', document.getElementById('workforce-case-driver').value);
    body.append('case_type', document.getElementById('workforce-case-type').value);
    body.append('severity', document.getElementById('workforce-case-severity').value);
    body.append('details', document.getElementById('workforce-case-details').value.trim());
    Array.from(document.getElementById('workforce-case-evidence').files).forEach((file) => body.append('evidence', file));
    submit.disabled = true;
    status.textContent = 'Creating the HR record and opening the 72-hour rebuttal window...';
    try {
      const result = await apiRequest('/api/portal/workforce/cases', { method: 'POST', body });
      status.textContent = result.message;
      caseForm.reset();
      await loadHrDashboard();
    } catch (error) {
      status.textContent = error.message || 'The HR record could not be created.';
    } finally {
      submit.disabled = false;
    }
  });

  payrollForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const submit = payrollForm.querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
      await apiRequest('/api/portal/payroll', {
        method: 'POST',
        body: JSON.stringify({
          employee_id: Number(document.getElementById('workforce-payroll-employee').value),
          pay_period: document.getElementById('workforce-payroll-period').value.trim(),
          basic_pay: Number(document.getElementById('workforce-payroll-basic').value),
          allowances: Number(document.getElementById('workforce-payroll-allowances').value),
          bonus: Number(document.getElementById('workforce-payroll-bonus').value),
          deductions: Number(document.getElementById('workforce-payroll-deductions').value),
          salary_advance: Number(document.getElementById('workforce-payroll-advance').value),
          nssf_deduction: Number(document.getElementById('workforce-payroll-nssf').value),
          shif_deduction: Number(document.getElementById('workforce-payroll-shif').value),
          housing_levy_deduction: Number(document.getElementById('workforce-payroll-housing').value),
          taxable_pay: Number(document.getElementById('workforce-payroll-taxable').value),
          tax_charged: Number(document.getElementById('workforce-payroll-tax-charged').value),
          personal_relief: Number(document.getElementById('workforce-payroll-personal-relief').value),
          other_reliefs: Number(document.getElementById('workforce-payroll-other-reliefs').value),
          paye_tax: Number(document.getElementById('workforce-payroll-paye').value),
        }),
      });
      payrollForm.reset();
      await refreshSessionData();
    } catch (error) {
      window.DifanApp.showToast(error.message, 'error');
    } finally {
      submit.disabled = false;
    }
  });

  noticeForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const status = document.getElementById('workforce-notice-status');
    const submit = noticeForm.querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
      const result = await apiRequest('/api/portal/workforce/notices', {
        method: 'POST',
        body: JSON.stringify({
          notice_type: document.getElementById('workforce-notice-type').value,
          title: document.getElementById('workforce-notice-title').value.trim(),
          version: document.getElementById('workforce-notice-version').value.trim(),
          body: document.getElementById('workforce-notice-body').value.trim(),
        }),
      });
      status.textContent = `Published ${result.notice.title}; employee acknowledgement is now required.`;
      noticeForm.reset();
      await refreshSessionData();
    } catch (error) {
      status.textContent = error.message || 'Notice could not be published.';
    } finally {
      submit.disabled = false;
    }
  });

  async function loadDriverScore() {
    if (currentUser()?.role !== 'driver') return;
    document.getElementById('workforce-driver-score-panel').hidden = false;
    try {
      const data = await apiRequest('/api/portal/workforce/score');
      renderDriverScores(data.score);
      const preferences = await apiRequest('/api/auth/me');
      document.getElementById('workforce-leaderboard-opt-in').checked =
        Boolean(preferences.user.leaderboard_opt_in);
      document.getElementById('workforce-leaderboard-handle').value =
        preferences.user.leaderboard_handle || preferences.user.driver_code || '';
    } catch (error) {
      document.getElementById('workforce-driver-score').textContent =
        error.message || 'Your score could not be loaded.';
    }
  }

  document.getElementById('workforce-leaderboard-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
      await apiRequest('/api/portal/workforce/leaderboard-opt-in', {
        method: 'PATCH',
        body: JSON.stringify({
          opt_in: document.getElementById('workforce-leaderboard-opt-in').checked,
          handle: document.getElementById('workforce-leaderboard-handle').value.trim(),
        }),
      });
      await loadLeaderboard();
    } catch (error) {
      window.DifanApp.showToast(error.message, 'error');
    } finally {
      submit.disabled = false;
    }
  });

  async function refreshSessionData() {
    const user = currentUser();
    if (!user || !employeeRoles.has(user.role)) return;
    window.DifanApp.state.workforceLockout = true;
    document.body.classList.add('workforce-navigation-lockout');
    lockoutPanel.hidden = false;
    pendingList.replaceChildren(node('p', 'Checking required paystub, terms, and consent acknowledgements...'));
    try {
      const [pending, payroll] = await Promise.all([
        apiRequest('/api/portal/workforce/pending'),
        apiRequest(`/api/portal/payroll?year=${encodeURIComponent(payrollYear.value)}`),
      ]);
      pendingTasks = [
        ...pending.pending_slips.map((record) => ({ kind: 'payroll', record })),
        ...pending.pending_notices.map((record) => ({ kind: 'notice', record })),
      ];
      renderPendingTasks();
      renderPayroll(payroll.slips, user.id, hrRoles.has(user.role));
      if (!pending.must_acknowledge) {
        const noticeData = await apiRequest('/api/portal/workforce/notices');
        renderNotices(noticeData.notices);
      } else {
        renderNotices(pending.pending_notices);
      }
      if (pending.must_acknowledge) {
        document.getElementById('workforce-signing-status').textContent =
          'Please complete each required acknowledgement. Safety actions remain available.';
      }
    } catch (error) {
      window.DifanApp.showToast(error.message || 'Required payroll acknowledgements could not be checked.', 'error');
      pendingList.replaceChildren(node(
        'p',
        'The required acknowledgement status could not be verified. Navigation remains locked until it can be checked.',
      ));
      const retry = node('button', 'Retry acknowledgement check', 'btn btn-secondary');
      retry.type = 'button';
      retry.addEventListener('click', refreshSessionData);
      pendingList.appendChild(retry);
      if (window.DifanApp.state.activeTab !== 'workforce') {
        document.querySelector('[data-target-tab="workforce"]')?.click();
      }
      return;
    }
    await Promise.all([loadDriverScore(), loadLeaderboard(), loadEmployeeCases()]);
    await loadDriverClientRatingOptions();
    if (hrRoles.has(user.role)) await loadHrDashboard();
  }

  function renderRatingPanel(shipment) {
    if (!clientRatingPanel || currentUser()?.role !== 'client') return;
    ratingShipment = shipment;
    clientRatingPanel.hidden = !shipment?.pod_signed_at;
    if (!shipment?.pod_signed_at) return;
    const status = document.getElementById('client-rating-status');
    const submit = clientRatingForm.querySelector('button[type="submit"]');
    submit.disabled = true;
    status.textContent = 'Checking whether this delivery has already been rated...';
    apiRequest(`/api/portal/workforce/shipments/${encodeURIComponent(shipment.tracking_number)}/rating`)
      .then((data) => {
        const stars = document.getElementById('client-rating-stars');
        const feedback = document.getElementById('client-rating-feedback');
        if (data.rating) {
          stars.value = String(data.rating.stars);
          feedback.value = data.rating.feedback || '';
          stars.disabled = true;
          feedback.disabled = true;
          submit.disabled = true;
          status.textContent = 'Thank you. This delivery has already been rated.';
        } else {
          stars.disabled = false;
          feedback.disabled = false;
          submit.disabled = !data.can_rate;
          if (data.already_rated) {
            stars.disabled = true;
            feedback.disabled = true;
            status.textContent = 'This delivery has already received its one customer rating.';
          } else {
            status.textContent = data.can_rate
              ? 'Rate your delivery from 1 to 5 stars and optionally leave feedback.'
              : 'Ratings become available after the signed proof of delivery is recorded.';
          }
        }
      })
      .catch((error) => { status.textContent = error.message; });
  }

  clientRatingForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!ratingShipment) return;
    const submit = clientRatingForm.querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
      await apiRequest(`/api/portal/workforce/shipments/${encodeURIComponent(ratingShipment.tracking_number)}/rating`, {
        method: 'POST',
        body: JSON.stringify({
          stars: Number(document.getElementById('client-rating-stars').value),
          feedback: document.getElementById('client-rating-feedback').value.trim(),
        }),
      });
      renderRatingPanel(ratingShipment);
    } catch (error) {
      document.getElementById('client-rating-status').textContent = error.message;
      submit.disabled = false;
    }
  });

  driverClientRatingForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const submit = driverClientRatingForm.querySelector('button[type="submit"]');
    const trackingNumber = document.getElementById('workforce-driver-client-shipment').value;
    const status = document.getElementById('workforce-driver-client-rating-status');
    if (!trackingNumber) {
      status.textContent = 'Select a completed delivery before rating the client.';
      return;
    }
    submit.disabled = true;
    try {
      const result = await apiRequest(
        `/api/portal/workforce/shipments/${encodeURIComponent(trackingNumber)}/client-rating`,
        {
          method: 'POST',
          body: JSON.stringify({
            loading_speed_stars: Number(document.getElementById('workforce-driver-loading-stars').value),
            facility_friendliness_stars: Number(document.getElementById('workforce-driver-facility-stars').value),
            feedback: document.getElementById('workforce-driver-client-feedback').value.trim(),
          }),
        },
      );
      status.textContent = `Client rating saved (${result.rating.score}/5). Thank you.`;
      driverClientRatingForm.reset();
      await loadDriverClientRatingOptions();
    } catch (error) {
      status.textContent = error.message || 'The client rating could not be saved.';
    } finally {
      submit.disabled = false;
    }
  });

  window.addEventListener('shipment:loaded', (event) => renderRatingPanel(event.detail));
  window.addEventListener('difan:session-ready', () => {
    if (dashboardTimer) clearInterval(dashboardTimer);
    refreshSessionData();
    dashboardTimer = setInterval(() => {
      if (window.DifanApp.state.activeTab === 'workforce') refreshSessionData();
    }, 30_000);
  });
  document.querySelector('[data-target-tab="workforce"]')?.addEventListener('click', refreshSessionData);
  populatePayrollYears();
  payrollYear?.addEventListener('change', refreshSessionData);
  document.getElementById('workforce-download-own-p9')?.addEventListener('click', () => {
    const year = payrollYear.value;
    downloadPrivatePdf(
      `/api/portal/payroll/p9/${encodeURIComponent(year)}`,
      `${year}-P9-annual-summary.pdf`,
      document.getElementById('workforce-p9-status'),
    );
  });
  document.getElementById('workforce-download-employee-p9')?.addEventListener('click', () => {
    const employeeId = document.getElementById('workforce-p9-employee').value;
    const year = payrollYear.value;
    const status = document.getElementById('workforce-p9-status');
    if (!employeeId) {
      status.textContent = 'Select an employee before downloading their P9.';
      return;
    }
    downloadPrivatePdf(
      `/api/portal/payroll/employees/${encodeURIComponent(employeeId)}/p9/${encodeURIComponent(year)}`,
      `${year}-employee-P9.pdf`,
      status,
    );
  });
  if (currentUser() && localStorage.getItem('jwt_token')) refreshSessionData();
});
