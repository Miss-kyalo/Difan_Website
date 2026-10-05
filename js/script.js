document.addEventListener('DOMContentLoaded', () => {
    const btnClient = document.getElementById('btn-role-client');
    const btnAdmin = document.getElementById('btn-role-admin');
    const clientTabs = document.getElementById('client-tabs');
    const adminTabs = document.getElementById('admin-tabs');
    const clientPanels = document.getElementById('client-panels');
    const adminPanels = document.getElementById('admin-panels');
    const userDisplay = document.getElementById('user-display');

    function switchPortal(role) {
        if (role === 'client') {
            btnClient.classList.add('active');
            btnAdmin.classList.remove('active');
            clientTabs.style.display = 'flex';
            adminTabs.style.display = 'none';
            clientPanels.style.display = 'block';
            adminPanels.style.display = 'none';
            userDisplay.textContent = 'Customer Account: Bamburi Cement';
            activateFirstTab('client');
        } else {
            btnAdmin.classList.add('active');
            btnClient.classList.remove('active');
            adminTabs.style.display = 'flex';
            clientTabs.style.display = 'none';
            adminPanels.style.display = 'block';
            clientPanels.style.display = 'none';
            userDisplay.textContent = 'Company Employee: HR & Admin';
            activateFirstTab('admin');
        }
    }

    function activateFirstTab(group) {
        const targetTabs = group === 'client' ? clientTabs : adminTabs;
        const targetPanels = group === 'client' ? clientPanels : adminPanels;

        const firstTab = targetTabs.querySelector('.tab-btn');
        if (firstTab) {
            const tabId = firstTab.getAttribute('data-tab');
            
            targetTabs.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            targetPanels.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));

            firstTab.classList.add('active');
            const targetPanel = document.getElementById(tabId);
            if (targetPanel) targetPanel.classList.add('active');
        }
    }

    if (btnClient && btnAdmin) {
        btnClient.addEventListener('click', () => switchPortal('client'));
        btnAdmin.addEventListener('click', () => switchPortal('admin'));
    }

    document.querySelectorAll('.tab-btn').forEach(button => {
        button.addEventListener('click', (e) => {
            const group = e.target.getAttribute('data-group');
            const tabId = e.target.getAttribute('data-tab');

            const parentGroup = group === 'client' ? clientTabs : adminTabs;
            const parentPanels = group === 'client' ? clientPanels : adminPanels;

            parentGroup.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            parentPanels.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));

            e.target.classList.add('active');
            const activePanel = document.getElementById(tabId);
            if (activePanel) activePanel.classList.add('active');
        });
    });

    const accountForm = document.getElementById('account-gen-form');
    if (accountForm) {
        accountForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const company = document.getElementById('acc-company').value;
            window.DifanApp.showToast(`Account provisioned for ${company}`);
            accountForm.reset();
        });
    }
});