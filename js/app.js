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
            station: "Athi River HQ",
            company_name: "",
            email: ""
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
    initQuoteBuilder();
    initRoleSwitcher();
    initIncidentTable();
    initQuickSearch();

    window.addEventListener('difan:session-ready', () => {
        initDashboardMetrics();
    });

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
        const isClient = user.role === 'client';
        const roleName = String(user.role || 'employee');

        const setElemText = (id, text) => {
            const el = document.getElementById(id);
            if (el) el.innerText = text;
        };

        setElemText('stat-total-trailers', metrics.totalTrailers);
        setElemText('stat-active-transit', metrics.activeOnTransit);
        setElemText('stat-maintenance', metrics.inMaintenance);
        setElemText('stat-yard-idle', metrics.yardIdle);
        setElemText('current-user-badge', `${user.name} (${isClient ? 'CLIENT PORTAL' : user.role.toUpperCase()})`);
        const clientProfile = document.getElementById('client-profile');
        const employeeProfile = document.getElementById('employee-profile');
        if (clientProfile) clientProfile.hidden = !isClient;
        if (employeeProfile) employeeProfile.hidden = isClient;

        setElemText('client-profile-name', user.company_name || user.name || 'Client');
        setElemText('client-profile-email', user.email || 'Not provided');
        setElemText('employee-profile-name', user.name || 'Employee');
        setElemText('employee-profile-role', roleName.charAt(0).toUpperCase() + roleName.slice(1));
        setElemText('employee-profile-station', user.station || 'Not provided');

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
        switcher.disabled = true;
        switcher.setAttribute('aria-label', 'Portal role assigned to your account');
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

    function renderQuote(resultBox, title, breakdown) {
        resultBox.replaceChildren();
        const heading = document.createElement('h4');
        heading.textContent = title;
        resultBox.appendChild(heading);
        breakdown.forEach(([label, value]) => {
            const line = document.createElement('p');
            line.textContent = `${label}: ${value}`;
            resultBox.appendChild(line);
        });
        resultBox.style.display = 'block';
    }

    async function calculateQuote(service, amount, resultBox) {
        if (service === '20ft' || service === '40ft') {
            const token = localStorage.getItem('jwt_token');
            if (!Number.isInteger(amount) || amount < 1 || amount > 100) {
                throw new Error('Enter a container quantity between 1 and 100.');
            }
            const headers = { 'Content-Type': 'application/json' };
            if (token) headers.Authorization = `Bearer ${token}`;
            const response = await fetch('http://localhost:5000/api/portal/container-quote', {
                method: 'POST',
                headers,
                body: JSON.stringify({ size: service, quantity: amount }),
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.message || 'Unable to calculate the container quote.');
            const quote = data.quote;
            renderQuote(resultBox, `${amount} × ${quote.size} container quote`, [
                ['VAT-exclusive total', window.DifanApp.formatCurrency(quote.total_kes)],
                ['Estimated VAT (16%)', window.DifanApp.formatCurrency(quote.vat_amount_kes)],
                ['Estimated VAT-inclusive total', window.DifanApp.formatCurrency(quote.total_including_vat_kes)],
            ]);
            return;
        }

        const origin = document.getElementById('calc-origin')?.value;
        const destination = document.getElementById('calc-destination')?.value;
        if (!origin || !destination) {
            throw new Error('Choose both an origin and destination.');
        }
        const tonnage = Number(amount);
        if (!Number.isFinite(tonnage) || tonnage < 1 || tonnage > 100) {
            throw new Error('Enter a valid cargo weight between 1 and 100 tonnes.');
        }
        const corridors = {
            'Athi River-Mombasa': { km: 480, rate: 14 },
            'Athi River-Kisumu': { km: 355, rate: 16 },
            'Athi River-Malaba': { km: 440, rate: 15 },
            'Athi River-Nakuru': { km: 160, rate: 18 },
        };
        const route = corridors[`${origin}-${destination}`] || { km: 300, rate: 15 };
        const freight = route.km * tonnage * route.rate;
        const totalExcludingVat = Math.round(freight + (freight * 0.05) + 3500);
        const vatAmount = Math.round(totalExcludingVat * 0.16);
        renderQuote(resultBox, `Freight quote: ${origin} to ${destination}`, [
            ['Distance and load', `${route.km} km · ${tonnage} tonnes`],
            ['VAT-exclusive total', window.DifanApp.formatCurrency(totalExcludingVat)],
            ['Estimated VAT (16%)', window.DifanApp.formatCurrency(vatAmount)],
            ['Estimated VAT-inclusive total', window.DifanApp.formatCurrency(totalExcludingVat + vatAmount)],
        ]);
    }

    // --- FREIGHT CORRIDOR QUOTATION CALCULATOR ---
    function initFreightCalculator() {
        const calcForm = document.getElementById('freight-calc-form');
        if (!calcForm) return;

        const serviceSelect = document.getElementById('calc-quote-service');
        const tonnageField = document.getElementById('calc-tonnage-field');
        const quantityField = document.getElementById('calc-container-quantity-field');
        const resultBox = document.getElementById('calc-result-output');
        const submitButton = calcForm.querySelector('button[type="submit"]');

        function updateQuoteInputs() {
            const isContainer = serviceSelect.value === '20ft' || serviceSelect.value === '40ft';
            tonnageField.hidden = isContainer;
            quantityField.hidden = !isContainer;
            document.getElementById('calc-tonnage').required = !isContainer;
            document.getElementById('calc-container-quantity').required = isContainer;
            resultBox.style.display = 'none';
            resultBox.replaceChildren();
        }

        serviceSelect.addEventListener('change', updateQuoteInputs);
        updateQuoteInputs();
        calcForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            submitButton.disabled = true;
            resultBox.replaceChildren();
            try {
                const service = serviceSelect.value;
                const amount = service === '20ft' || service === '40ft'
                    ? Number(document.getElementById('calc-container-quantity').value)
                    : Number(document.getElementById('calc-tonnage').value);
                await calculateQuote(service, amount, resultBox);
                if (service === 'freight') window.DifanApp.showToast('Freight quotation calculated!');
            } catch (error) {
                renderQuote(resultBox, 'Quote unavailable', [['Details', error.message || 'Please try again.']]);
            } finally {
                submitButton.disabled = false;
            }
        });
    }

    function initQuoteBuilder() {
        const form = document.getElementById('uber-booking-form');
        if (!form) return;
        const serviceSelect = document.getElementById('tonnage-select');
        const quantityField = document.getElementById('booking-container-quantity-field');
        const quantityInput = document.getElementById('booking-container-quantity');
        const resultBox = document.getElementById('booking-quote-box');
        const submitButton = form.querySelector('button[type="submit"]');

        function updateContainerQuantityVisibility() {
            const isContainer = ['20ft', '40ft'].includes(serviceSelect.value);
            quantityField.hidden = !isContainer;
            quantityInput.required = isContainer;
        }

        serviceSelect.addEventListener('change', updateContainerQuantityVisibility);
        updateContainerQuantityVisibility();
        form.addEventListener('submit', async (event) => {
            event.preventDefault();
            submitButton.disabled = true;
            const service = ['20ft', '40ft'].includes(serviceSelect.value) ? serviceSelect.value : 'freight';
            const amount = service === 'freight'
                ? Number(serviceSelect.value)
                : Number(quantityInput.value);
            try {
                await calculateQuote(service, amount, resultBox);
            } catch (error) {
                renderQuote(resultBox, 'Quote unavailable', [['Details', error.message || 'Please try again.']]);
            } finally {
                submitButton.disabled = false;
            }
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