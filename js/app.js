/**
 * DIFAN LOGISTICS (K) LTD - Central Application Core (app.js)
 * Manages global application state, navigation, dashboard metrics, 
 * RBAC session control, mechanic dispatch tracking, incident reporting, 
 * and freight quotation calculations.
 */

// Global Application Namespace
window.DifanApp = {
    // 1. GLOBAL TOAST NOTIFICATION SYSTEM
    showToast(message, type = 'success') {
        let toastContainer = document.getElementById('difan-toast-container');
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.id = 'difan-toast-container';
            toastContainer.style.cssText = `
                position: fixed; bottom: 20px; right: 20px; z-index: 9999;
                display: flex; flex-direction: column; gap: 10px;
            `;
            document.body.appendChild(toastContainer);
        }

        const toast = document.createElement('div');
        const bgColors = { success: '#28a745', error: '#dc3545', warning: '#ffc107', info: '#0056b3' };
        toast.style.cssText = `
            background-color: ${bgColors[type] || bgColors.success}; color: #fff;
            padding: 12px 20px; border-radius: 6px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            font-family: Arial, sans-serif; font-size: 0.9rem; opacity: 0;
            transition: opacity 0.3s ease, transform 0.3s ease; transform: translateY(10px);
        `;
        toast.innerText = message;
        toastContainer.appendChild(toast);

        setTimeout(() => { toast.style.opacity = '1'; toast.style.transform = 'translateY(0)'; }, 10);
        setTimeout(() => {
            toast.style.opacity = '0'; toast.style.transform = 'translateY(10px)';
            setTimeout(() => toast.remove(), 300);
        }, 3500);
    },

    // 2. CURRENCY FORMATTER (KENYAN SHILLINGS)
    formatCurrency(amount) {
        const num = Number(amount) || 0;
        return `KES ${num.toLocaleString('en-KE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    },

    // 3. APPLICATION & RBAC STATE
    state: {
        activeTab: 'dashboard',
        currentUser: {
            name: "Mary Wambui",
            role: "accountant", // Options: 'accountant' | 'driver' | 'admin'
            station: "Athi River HQ"
        },
        fleetMetrics: {
            totalTrailers: 18,
            activeOnTransit: 14,
            inMaintenance: 2,
            yardIdle: 2
        },
        // Fleet Incidents & Mechanic Assignments Data
        breakdownIncidents: [
            {
                id: "INC-2026-08821",
                truckNo: "KDA-8821",
                driverName: "John Mwangi",
                location: "Salama Corridor (A109)",
                operationalStatus: "Engine Overheat Alert",
                reliefTruck: "KDG-102K",
                severity: "Moderate (Vehicle Inoperable / Cargo Safe)",
                rootCause: "Thermostat stick / coolant hose pressure drop resulting in rapid thermal build-up.",
                mechanicTeam: [
                    { name: "Erick Omondi", role: "Lead Mechanic", action: "On-site OBD diagnostics & engine recovery" },
                    { name: "Josephat Mutua", role: "Yard Assistant", action: "Cargo transfer & towing support" }
                ],
                timestamp: "2026-09-10 14:30 EAT"
            }
        ]
    }
};

document.addEventListener('DOMContentLoaded', () => {

    initNavigation();
    initDashboardMetrics();
    initFreightCalculator();
    initRoleSwitcher();
    initIncidentTable();
    initQuickSearch();

    // --- NAVIGATION ROUTER ---
    function initNavigation() {
        const navLinks = document.querySelectorAll('.nav-link, [data-target-tab]');
        const tabViews = document.querySelectorAll('.tab-view');

        navLinks.forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                const targetTab = link.getAttribute('data-target-tab') || link.getAttribute('href').replace('#', '');
                
                navLinks.forEach(nl => nl.classList.remove('active'));
                link.classList.add('active');

                tabViews.forEach(view => {
                    if (view.id === `view-${targetTab}`) {
                        view.style.display = 'block';
                        window.DifanApp.state.activeTab = targetTab;
                    } else {
                        view.style.display = 'none';
                    }
                });
                window.scrollTo({ top: 0, behavior: 'smooth' });
            });
        });
    }

    // --- DASHBOARD METRICS & RBAC UI ---
    function initDashboardMetrics() {
        const metrics = window.DifanApp.state.fleetMetrics;
        const user = window.DifanApp.state.currentUser;

        const setElemText = (id, text) => {
            const el = document.getElementById(id);
            if (el) el.innerText = text;
        };

        setElemText('stat-total-trailers', metrics.totalTrailers);
        setElemText('stat-active-transit', metrics.activeOnTransit);
        setElemText('stat-maintenance', metrics.inMaintenance);
        setElemText('stat-yard-idle', metrics.yardIdle);
        setElemText('current-user-badge', `${user.name} (${user.role.toUpperCase()})`);

        // Enforce RBAC visibility on restricted dashboard panels
        const accountantOnlyElements = document.querySelectorAll('.accountant-restricted');
        accountantOnlyElements.forEach(el => {
            el.style.display = user.role === 'accountant' ? 'block' : 'none';
        });
    }

    // --- ROLE SWITCHER SIMULATOR ---
    function initRoleSwitcher() {
        const switcher = document.getElementById('role-switcher-select');
        if (!switcher) return;

        switcher.value = window.DifanApp.state.currentUser.role;
        switcher.addEventListener('change', (e) => {
            const newRole = e.target.value;
            window.DifanApp.state.currentUser.role = newRole;
            if (newRole === 'accountant') window.DifanApp.state.currentUser.name = "Mary Wambui";
            if (newRole === 'driver') window.DifanApp.state.currentUser.name = "Peter Ochieng";
            if (newRole === 'admin') window.DifanApp.state.currentUser.name = "David Kiprop";

            window.DifanApp.showToast(`Session role switched to: ${newRole.toUpperCase()}`, 'info');
            initDashboardMetrics();

            // Trigger re-render if HR payroll or roster functions are globally available
            if (typeof renderPayroll === 'function') renderPayroll();
            if (typeof renderRoster === 'function') renderRoster();
        });
    }

    // --- INCIDENT REPORT & MECHANIC ASSIGNMENT TABLE ---
    function initIncidentTable() {
        const container = document.getElementById('breakdown-control-rows');
        if (!container) return;

        const incidents = window.DifanApp.state.breakdownIncidents;
        container.innerHTML = '';

        const fragment = document.createDocumentFragment();
        incidents.forEach(item => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><code>${item.truckNo}</code></td>
                <td><strong>${item.driverName}</strong></td>
                <td><span class="badge badge-warning">${item.operationalStatus}</span><br><small>${item.location}</small></td>
                <td>
                    <div><strong>Relief Vehicle:</strong> <code>${item.reliefTruck}</code></div>
                    <div style="margin-top: 6px; font-size: 0.85rem;">
                        <strong>🛠️ Assigned Mechanic Team:</strong>
                        <ul style="margin: 3px 0 0 16px; padding: 0;">
                            ${item.mechanicTeam.map(tech => `<li><strong>${tech.name}</strong> (${tech.role}) – <em>${tech.action}</em></li>`).join('')}
                        </ul>
                    </div>
                    <button class="btn btn-sm btn-outline view-incident-report" data-id="${item.id}" style="margin-top: 8px;">
                        📄 View Official Incident Report
                    </button>
                </td>
            `;
            fragment.appendChild(tr);
        });
        container.appendChild(fragment);

        // Event listener for opening the popup incident report
        container.addEventListener('click', (e) => {
            if (e.target.classList.contains('view-incident-report')) {
                const id = e.target.getAttribute('data-id');
                const incident = incidents.find(inc => inc.id === id);
                if (incident) generateIncidentReportWindow(incident);
            }
        });
    }

    // --- POPUP INCIDENT REPORT GENERATOR ---
    function generateIncidentReportWindow(incident) {
        const win = window.open('', '_blank', 'width=850,height=900');
        if (!win) {
            alert("Popup blocked! Please allow popups to view the Incident Report.");
            return;
        }

        win.document.write(`
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <title>Incident Report - ${incident.id}</title>
                <style>
                    body { font-family: Arial, sans-serif; padding: 2rem; color: #333; line-height: 1.5; }
                    .header { text-align: center; border-bottom: 2px solid #0056b3; padding-bottom: 1rem; margin-bottom: 1.5rem; }
                    .header h1 { margin: 0; color: #0056b3; font-size: 1.8rem; }
                    .meta-table { width: 100%; border-collapse: collapse; margin-bottom: 1.5rem; }
                    .meta-table th, .meta-table td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; }
                    .meta-table th { background-color: #f2f2f2; }
                    .section-title { color: #0056b3; border-bottom: 1px solid #ddd; padding-bottom: 4px; margin-top: 1.5rem; }
                    .btn-print { background: #0056b3; color: white; border: none; padding: 10px 20px; font-size: 1rem; cursor: pointer; border-radius: 4px; margin-top: 2rem; }
                    @media print { .btn-print { display: none; } }
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>DIFAN LOGISTICS (K) LTD</h1>
                    <p>Fleet Operations & Technical Support Division</p>
                    <h2>FLEET BREAKDOWN & INCIDENT REPORT</h2>
                </div>

                <table class="meta-table">
                    <tr><th>Incident Ref</th><td>${incident.id}</td><th>Timestamp</th><td>${incident.timestamp}</td></tr>
                    <tr><th>Location</th><td>${incident.location}</td><th>Severity</th><td><strong>${incident.severity}</strong></td></tr>
                </table>

                <h3 class="section-title">1. Vehicle & Driver Profile</h3>
                <p><strong>Trailer:</strong> <code>${incident.truckNo}</code> | <strong>Driver:</strong> ${incident.driverName}</p>

                <h3 class="section-title">2. Root Cause Analysis</h3>
                <p>${incident.rootCause}</p>

                <h3 class="section-title">3. Mechanic Team Dispatch & Recovery Actions</h3>
                <p><strong>Relief Unit:</strong> <code>${incident.reliefTruck}</code> dispatched.</p>
                <ul>
                    ${incident.mechanicTeam.map(tech => `<li><strong>${tech.name}</strong> (${tech.role}) – ${tech.action}</li>`).join('')}
                </ul>

                <br>
                <button class="btn-print" onclick="window.print()">🖨️ Print / Save as PDF</button>
            </body>
            </html>
        `);
        win.document.close();
    }

    // --- FREIGHT CORRIDOR QUOTATION CALCULATOR ---
    function initFreightCalculator() {
        const calcForm = document.getElementById('freight-calc-form');
        if (!calcForm) return;

        calcForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const origin = document.getElementById('calc-origin').value;
            const destination = document.getElementById('calc-destination').value;
            const tonnage = parseFloat(document.getElementById('calc-tonnage').value) || 30;

            const corridors = {
                "Athi River-Mombasa": { km: 480, rate: 14 },
                "Athi River-Kisumu": { km: 355, rate: 16 },
                "Athi River-Malaba": { km: 440, rate: 15 },
                "Athi River-Nakuru": { km: 160, rate: 18 }
            };

            const route = corridors[`${origin}-${destination}`] || { km: 300, rate: 15 };
            const freight = route.km * tonnage * route.rate;
            const total = freight + (freight * 0.05) + 3500;

            const resultBox = document.getElementById('calc-result-output');
            if (resultBox) {
                resultBox.style.display = 'block';
                resultBox.innerHTML = `
                    <div style="background: #e8f4fd; border: 1px solid #b8daff; padding: 1rem; border-radius: 6px;">
                        <h4 style="margin: 0 0 6px 0; color: #0056b3;">🚚 Freight Quote: ${origin} to ${destination}</h4>
                        <p style="margin: 2px 0;">Distance: <strong>${route.km} KM</strong> | Load: <strong>${tonnage} Tonnes</strong></p>
                        <p style="margin: 2px 0; font-size: 1.1rem; font-weight: bold; color: #28a745;">Total Quote: ${window.DifanApp.formatCurrency(total)}</p>
                    </div>
                `;
            }
            window.DifanApp.showToast("Freight quotation calculated!");
        });
    }

    // --- QUICK SEARCH ---
    function initQuickSearch() {
        const searchInput = document.getElementById('global-search-input');
        if (!searchInput) return;

        searchInput.addEventListener('input', (e) => {
            const query = e.target.value.toLowerCase().trim();
            const activeView = document.querySelector('.tab-view[style*="block"], .tab-view:not([style*="none"])');
            if (!activeView) return;

            activeView.querySelectorAll('tbody tr').forEach(row => {
                row.style.display = row.innerText.toLowerCase().includes(query) ? '' : 'none';
            });
        });
    }

    console.log("Difan Logistics Core App Initialized with RBAC & Incident Tracking.");
});