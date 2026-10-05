document.addEventListener('DOMContentLoaded', () => {
  const financeView = document.getElementById('view-finance');
  const financeNavigation = document.getElementById('finance-navigation');
  const deliveryList = document.getElementById('finance-delivery-list');
  const statusMessage = document.getElementById('finance-status');
  if (!financeView || !financeNavigation || !deliveryList || !statusMessage) return;

  const summaryFields = {
    paidCount: document.getElementById('finance-paid-count'),
    pendingCount: document.getElementById('finance-pending-count'),
    totalPaid: document.getElementById('finance-total-paid'),
    totalBalance: document.getElementById('finance-total-balance'),
  };

  function currency(amount) {
    return window.DifanApp?.formatCurrency(amount) || `KES ${Number(amount || 0).toFixed(2)}`;
  }

  function tokenHeaders() {
    const token = localStorage.getItem('jwt_token');
    if (!token) throw new Error('Please sign in to view delivery finance.');
    return { Authorization: 'Bearer ' + token };
  }

  async function apiRequest(path, options = {}) {
    const response = await fetch(`http://localhost:5000${path}`, {
      ...options,
      headers: {
        ...tokenHeaders(),
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...options.headers,
      },
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.message || 'The finance request could not be completed.');
    return data;
  }

  function createCell(value, className = '') {
    const cell = document.createElement('td');
    if (className) cell.className = className;
    cell.textContent = value;
    return cell;
  }

  function createPaymentForm(delivery) {
    const cell = document.createElement('td');
    cell.className = 'finance-update-column';
    const form = document.createElement('form');
    form.className = 'finance-payment-form';

    const invoiceLabel = document.createElement('label');
    invoiceLabel.textContent = 'Invoice total';
    const invoiceInput = document.createElement('input');
    invoiceInput.type = 'number';
    invoiceInput.min = '0';
    invoiceInput.max = '100000000';
    invoiceInput.step = '0.01';
    invoiceInput.required = true;
    invoiceInput.setAttribute('aria-label', `Invoice total for ${delivery.tracking_number}`);
    invoiceInput.value = delivery.invoice_amount_kes ?? '';
    invoiceLabel.appendChild(invoiceInput);

    const paidLabel = document.createElement('label');
    paidLabel.textContent = 'Paid so far';
    const paidInput = document.createElement('input');
    paidInput.type = 'number';
    paidInput.min = '0';
    paidInput.max = '100000000';
    paidInput.step = '0.01';
    paidInput.required = true;
    paidInput.setAttribute('aria-label', `Amount paid for ${delivery.tracking_number}`);
    paidInput.value = delivery.paid_amount_kes;
    paidLabel.appendChild(paidInput);

    const markPaidLabel = document.createElement('label');
    markPaidLabel.className = 'finance-mark-paid';
    const markPaidInput = document.createElement('input');
    markPaidInput.type = 'checkbox';
    markPaidInput.setAttribute('aria-label', `Mark ${delivery.tracking_number} fully paid`);
    markPaidLabel.append(markPaidInput, document.createTextNode('Mark fully paid'));

    markPaidInput.addEventListener('change', () => {
      if (markPaidInput.checked) paidInput.value = invoiceInput.value;
      paidInput.disabled = markPaidInput.checked;
    });
    invoiceInput.addEventListener('input', () => {
      if (markPaidInput.checked) paidInput.value = invoiceInput.value;
    });

    const saveButton = document.createElement('button');
    saveButton.type = 'submit';
    saveButton.className = 'btn btn-primary';
    saveButton.textContent = 'Save';
    form.append(invoiceLabel, paidLabel, markPaidLabel, saveButton);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      saveButton.disabled = true;
      statusMessage.textContent = `Saving payment for ${delivery.tracking_number}...`;
      try {
        await apiRequest(`/api/portal/delivery-finance/${encodeURIComponent(delivery.tracking_number)}`, {
          method: 'PATCH',
          body: JSON.stringify({
            invoice_amount_kes: invoiceInput.value,
            paid_amount_kes: paidInput.value,
            mark_paid: markPaidInput.checked,
          }),
        });
        await loadFinance();
        statusMessage.textContent = `Payment for ${delivery.tracking_number} updated.`;
      } catch (error) {
        statusMessage.textContent = error.message || 'Unable to save the payment.';
      } finally {
        saveButton.disabled = false;
      }
    });

    cell.appendChild(form);
    return cell;
  }

  function renderDelivery(delivery, canUpdate) {
    const row = document.createElement('tr');
    row.append(
      createCell(delivery.tracking_number),
      createCell(delivery.company_name || 'Unassigned'),
      createCell(delivery.destination),
      createCell(delivery.invoice_amount_kes === null ? 'Not invoiced' : currency(delivery.invoice_amount_kes)),
      createCell(currency(delivery.paid_amount_kes)),
      createCell(currency(delivery.balance_kes)),
    );
    const paymentStatus = createCell(delivery.payment_status.replaceAll('_', ' '), 'finance-payment-status');
    paymentStatus.dataset.status = delivery.payment_status;
    row.appendChild(paymentStatus);
    if (canUpdate) row.appendChild(createPaymentForm(delivery));
    deliveryList.appendChild(row);
  }

  async function loadFinance() {
    deliveryList.replaceChildren();
    statusMessage.textContent = 'Loading delivery finance...';
    try {
      const data = await apiRequest('/api/portal/delivery-finance');
      const currentUser = window.DifanApp?.state?.currentUser;
      const canUpdate = Boolean(data.can_update);
      financeView.classList.toggle('finance-read-only', !canUpdate);
      if (summaryFields.paidCount) summaryFields.paidCount.textContent = String(data.summary.paid_count);
      if (summaryFields.pendingCount) summaryFields.pendingCount.textContent = String(data.summary.pending_count);
      if (summaryFields.totalPaid) summaryFields.totalPaid.textContent = currency(data.summary.paid_amount_kes);
      if (summaryFields.totalBalance) summaryFields.totalBalance.textContent = currency(data.summary.balance_kes);

      for (const delivery of data.deliveries) renderDelivery(delivery, canUpdate);
      if (!data.deliveries.length) {
        statusMessage.textContent = currentUser?.role === 'client'
          ? 'No deliveries are linked to your company account yet.'
          : 'There are no deliveries to show.';
      } else {
        statusMessage.textContent = canUpdate
          ? 'Enter the invoice total and amount received, or mark a delivery fully paid.'
          : 'Showing payment status for your company deliveries.';
      }
    } catch (error) {
      statusMessage.textContent = error.message || 'Unable to load delivery finance.';
    }
  }

  financeNavigation.addEventListener('click', loadFinance);
  window.addEventListener('difan:session-ready', () => {
    if (window.DifanApp?.state?.activeTab === 'finance') loadFinance();
  });
});
