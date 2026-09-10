document.addEventListener('DOMContentLoaded', () => {
    const bookingForm = document.getElementById('uber-booking-form');

    if (bookingForm) {
        bookingForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const tonnage = parseFloat(document.getElementById('tonnage-select').value);
            const urgency = document.getElementById('urgency-select').value;
            
            let baseRate = tonnage * 65;
            if (urgency === 'express') baseRate *= 1.15;
            if (urgency === 'critical') baseRate *= 1.30;

            const deposit = baseRate * 0.50;

            document.getElementById('total-quote').textContent = `$${baseRate.toFixed(2)}`;
            document.getElementById('deposit-val').textContent = `$${deposit.toFixed(2)}`;
            document.getElementById('balance-val').textContent = `$${deposit.toFixed(2)}`;
            document.getElementById('booking-quote-box').style.display = 'block';
        });
    }

    // Delegation for Payment Buttons
    document.addEventListener('click', (e) => {
        if (e.target.classList.contains('pay-btn')) {
            const payType = e.target.getAttribute('data-type');
            alert(`Opening Payment Gateway...\nProcessing: ${payType}`);
        }
    });
});