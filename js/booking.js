document.addEventListener('DOMContentLoaded', () => {
    const bookingForm = document.getElementById('uber-booking-form');
    const quoteBox = document.getElementById('booking-quote-box');
    const totalDisplay = document.getElementById('total-quote');
    const depositDisplay = document.getElementById('deposit-val');
    const balanceDisplay = document.getElementById('balance-val');

    if (bookingForm) {
        bookingForm.addEventListener('submit', (e) => {
            e.preventDefault();

            const tonnage = parseFloat(document.getElementById('tonnage-select').value) || 15;
            const urgency = document.getElementById('urgency-select').value;

            let baseRate = tonnage * 8000;

            if (urgency === 'express') baseRate *= 1.15;
            if (urgency === 'critical') baseRate *= 1.30;

            const deposit = baseRate * 0.5;
            const balance = baseRate * 0.5;

            totalDisplay.textContent = window.DifanApp.formatCurrency(baseRate);
            depositDisplay.textContent = window.DifanApp.formatCurrency(deposit);
            balanceDisplay.textContent = window.DifanApp.formatCurrency(balance);

            quoteBox.style.display = 'block';
            window.DifanApp.showToast('Instant quote generated successfully.');
        });
    }

    document.querySelectorAll('.pay-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            window.DifanApp.showToast('Processing 50% commitment deposit via MPESA/Card...');
            setTimeout(() => {
                window.DifanApp.showToast('Payment Received! Vehicle dispatched.');
            }, 1500);
        });
    });
});