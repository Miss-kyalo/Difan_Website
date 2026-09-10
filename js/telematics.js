document.addEventListener('DOMContentLoaded', () => {
    // Condition Selection Rejection Fields Toggle
    const conditionSelect = document.getElementById('condition-status');
    const rejectFields = document.getElementById('reject-fields');

    if (conditionSelect) {
        conditionSelect.addEventListener('change', (e) => {
            const val = e.target.value;
            rejectFields.style.display = (val === 'partial_reject' || val === 'full_reject') ? 'block' : 'none';
        });
    }

    // Account Generation
    const accForm = document.getElementById('account-gen-form');
    if (accForm) {
        accForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const company = document.getElementById('acc-company').value;
            const email = document.getElementById('acc-email').value;
            const tempPassword = 'DF-' + Math.random().toString(36).substring(2, 8).toUpperCase();

            alert(`Account Provisioned!\nCompany: ${company}\nEmail: ${email}\nTemporary Password: ${tempPassword}\n\nEmail sent via backend API.`);
        });
    }
});