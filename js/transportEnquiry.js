document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('public-transport-enquiry-form');
  const status = document.getElementById('public-transport-enquiry-status');
  if (!form || !status) return;

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const submit = document.getElementById('public-transport-enquiry-submit');
    const payload = Object.fromEntries(new FormData(form).entries());
    payload.tonnage = payload.tonnage || null;
    submit.disabled = true;
    status.textContent = 'Sending your transport enquiry...';
    try {
      const response = await fetch('http://localhost:5000/api/portal/transport-enquiries', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || 'Your enquiry could not be sent.');
      form.reset();
      status.textContent = `${data.message} Reference: ${data.reference}.`;
    } catch (error) {
      status.textContent = error.message || 'Your enquiry could not be sent.';
    } finally {
      submit.disabled = false;
    }
  });
});
