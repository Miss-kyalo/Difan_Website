document.addEventListener('DOMContentLoaded', () => {
    // Role Switching
    const clientBtn = document.getElementById('btn-role-client');
    const adminBtn = document.getElementById('btn-role-admin');
    const clientTabs = document.getElementById('client-tabs');
    const adminTabs = document.getElementById('admin-tabs');
    const userDisplay = document.getElementById('user-display');

    clientBtn.addEventListener('click', () => {
        clientBtn.classList.add('active');
        adminBtn.classList.remove('active');
        clientTabs.style.display = 'flex';
        adminTabs.style.display = 'none';
        userDisplay.textContent = 'Client Portal: Bamburi Cement';
        switchTab('tab-track');
    });

    adminBtn.addEventListener('click', () => {
        adminBtn.classList.add('active');
        clientBtn.classList.remove('active');
        adminTabs.style.display = 'flex';
        clientTabs.style.display = 'none';
        userDisplay.textContent = 'Admin Control: System Dispatcher';
        switchTab('tab-admin-dispatch');
    });

    // Tab Switching
    document.querySelectorAll('.tab-btn').forEach(button => {
        button.addEventListener('click', (e) => {
            const tabGroup = e.target.getAttribute('data-group');
            const targetTab = e.target.getAttribute('data-tab');

            document.querySelectorAll(`#${tabGroup}-tabs .tab-btn`).forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');

            switchTab(targetTab);
        });
    });

    function switchTab(tabId) {
        document.querySelectorAll('.panel').forEach(panel => panel.classList.remove('active'));
        const activePanel = document.getElementById(tabId);
        if (activePanel) activePanel.classList.add('active');
    }

    // Dismiss Notifications
    document.getElementById('close-notification-btn').addEventListener('click', () => {
        document.getElementById('sys-notification').style.display = 'none';
    });
});