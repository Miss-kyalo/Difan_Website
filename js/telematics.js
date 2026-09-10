document.addEventListener('DOMContentLoaded', () => {
    const trackForm = document.getElementById('track-form');
    const conditionSelect = document.getElementById('condition-status');
    const rejectFields = document.getElementById('reject-fields');
    const conditionForm = document.getElementById('condition-form');

    if (trackForm) {
        trackForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const ref = document.getElementById('track-input').value;
            window.DifanApp.showToast(`Updated tracking information for load ref: ${ref}`);
        });
    }

    if (conditionSelect) {
        conditionSelect.addEventListener('change', (e) => {
            if (e.target.value === 'partial_reject' || e.target.value === 'full_reject') {
                rejectFields.style.display = 'block';
            } else {
                rejectFields.style.display = 'none';
            }
        });
    }

    if (conditionForm) {
        conditionForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const status = conditionSelect.value;
            if (status === 'good') {
                window.DifanApp.showToast('Delivery marked as fully intact and accepted.');
            } else {
                window.DifanApp.showToast('Discrepancy report recorded and flagged for claims review.');
            }
            conditionForm.reset();
            rejectFields.style.display = 'none';
        });
    }

    document.querySelectorAll('.alert-action-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            window.DifanApp.showToast('Relief Truck KDG-102K dispatched to swap payload.');
            this.textContent = 'Relief Dispatched';
            this.disabled = true;
            this.classList.remove('btn-primary');
            this.classList.add('btn-secondary');
        });
    });
});