/**
 * DIFAN LOGISTICS (K) LTD - Fleet Dispatch & Telematics Module (dispatch.js)
 */

(function() {
    function initDispatchModule() {
        const container = document.getElementById('fleet-dispatch-rows');
        if (!container) {
            console.warn("[DIFAN Dispatch] #fleet-dispatch-rows not found yet. Retrying...");
            return false;
        }

        console.log("[DIFAN Dispatch] Fleet dispatch container located. Initializing interface...");

        const showToast = (message, type = 'success') => {
            if (window.DifanApp && typeof window.DifanApp.showToast === 'function') {
                window.DifanApp.showToast(message, type);
            } else {
                console.log(`[Toast ${type}]: ${message}`);
                alert(`[${type.toUpperCase()}] ${message}`);
            }
        };

        // Role state: 'employee' or 'client'
        let currentUserRole = 'employee'; 

        const truckIncidentHistories = {
            "KCB-402L": [
                { id: 101, type: "Overheating Alert", severity: "Medium", mechanic: "Erick Omondi", notes: "Thermostat stuck in closed position.", parts: "Thermostat (1)", source: "Yard Stock", date: "2026-08-14" }
            ],
            "KDA-8821": [],
            "KDD-119P": []
        };

        const activeFleet = [
            { id: 1, truck: "KCB-402L", driver: "Peter Ochieng", route: "Athi River ➔ Kisumu", status: "In Transit", speed: "78 km/h", fuel: "68%", temp: "89°C" },
            { id: 2, truck: "KDA-8821", driver: "John Mwangi", route: "Mombasa Port ➔ Nairobi", status: "Maintenance", speed: "0 km/h", fuel: "12%", temp: "105°C" },
            { id: 3, truck: "KDD-119P", driver: "Samuel Gitau", route: "Nakuru ➔ Eldoret", status: "In Transit", speed: "65 km/h", fuel: "45%", temp: "85°C" }
        ];

        const availableMechanics = [
            { id: 201, name: "Erick Omondi", specialty: "Lead Engine & Transmission Specialist" },
            { id: 202, name: "Josephat Mutua", specialty: "Electrical & Telematics Assistant" },
            { id: 203, name: "Brian Kiprono", specialty: "Mobile Breakdown Response Unit" }
        ];

        // RENDER INTERFACE BASED ON ROLE
        window.renderFleetDispatch = function() {
            const dispatchContainer = document.getElementById('fleet-dispatch-rows');
            if (!dispatchContainer) return;
            dispatchContainer.innerHTML = '';

            // Inject role switcher toolbar
            let roleToolbar = document.getElementById('role-toolbar');
            if (!roleToolbar) {
                roleToolbar = document.createElement('div');
                roleToolbar.id = 'role-toolbar';
                roleToolbar.style.cssText = "margin-bottom: 1rem; display: flex; justify-content: flex-end; gap: 1rem; align-items: center;";
                dispatchContainer.parentNode.parentNode.insertBefore(roleToolbar, dispatchContainer.parentNode.closest('.card') || dispatchContainer.parentNode);
            }
            roleToolbar.innerHTML = `
                <span style="font-size: 0.85rem; font-weight: bold; color: #555;">View As:</span>
                <select id="portal-role-switch" class="form-control" style="width: 220px; display: inline-block;">
                    <option value="employee" ${currentUserRole === 'employee' ? 'selected' : ''}>Internal Employee (Full)</option>
                    <option value="client" ${currentUserRole === 'client' ? 'selected' : ''}>Client Portal (Summary Only)</option>
                </select>
            `;

            document.getElementById('portal-role-switch').onchange = (e) => {
                currentUserRole = e.target.value;
                renderFleetDispatch();
                renderIncidentSection();
            };

            const parentCard = dispatchContainer.closest('.card') || dispatchContainer.parentNode;

            if (currentUserRole === 'client') {
                parentCard.style.display = 'none'; 
                
                let clientView = document.getElementById('client-portal-summary');
                if (!clientView) {
                    clientView = document.createElement('div');
                    clientView.id = 'client-portal-summary';
                    clientView.style.cssText = "padding: 2rem; background: #fff; border: 1px solid #e0e0e0; border-radius: 8px; margin-top: 1rem;";
                    parentCard.parentNode.insertBefore(clientView, parentCard);
                }
                clientView.style.display = 'block';
                clientView.innerHTML = `
                    <h3 style="color: #333; margin-bottom: 0.5rem;">📦 DIFAN LOGISTICS - Client Shipment Tracking</h3>
                    <p style="color: #666; font-size: 0.9rem; margin-bottom: 1.5rem;">Live transit status for your active cargo movements.</p>
                    <table class="table" style="width: 100%; border-collapse: collapse;">
                        <thead>
                            <tr style="background: #f8f9fa; text-align: left; border-bottom: 2px solid #ddd;">
                                <th style="padding: 10px;">Truck Reg</th>
                                <th style="padding: 10px;">Assigned Route</th>
                                <th style="padding: 10px;">Delivery Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${activeFleet.map(f => `
                                <tr style="border-bottom: 1px solid #eee;">
                                    <td style="padding: 10px;"><code>${f.truck}</code></td>
                                    <td style="padding: 10px;">${f.route}</td>
                                    <td style="padding: 10px;">
                                        <span style="color: ${f.status === 'In Transit' ? '#28a745;' : '#e0a800;'} font-weight: bold;">
                                            ● ${f.status}
                                        </span>
                                    </td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                `;
                return;
            } else {
                parentCard.style.display = 'block';
                const clientView = document.getElementById('client-portal-summary');
                if (clientView) clientView.style.display = 'none';
            }

            const tableHead = document.querySelector('thead tr');
            if (tableHead) {
                tableHead.innerHTML = `<th>Truck Reg</th><th>Driver</th><th>Route</th><th>Status</th><th>Speed</th><th>Fuel</th><th>Temp</th><th>Actions / Dispatch</th>`;
            }

            const fragment = document.createDocumentFragment();
            activeFleet.forEach(fleet => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td><code>${fleet.truck}</code></td>
                    <td><strong>${fleet.driver}</strong></td>
                    <td>${fleet.route}</td>
                    <td><span style="color: ${fleet.status === 'In Transit' ? '#28a745;' : '#dc3545;'}">● ${fleet.status}</span></td>
                    <td>${fleet.speed}</td>
                    <td>${fleet.fuel}</td>
                    <td>${fleet.temp}</td>
                    <td>
                        <div style="display: flex; flex-direction: column; gap: 0.4rem;">
                            <select class="form-control form-control-sm mechanic-select" data-truck-id="${fleet.id}">
                                <option value="">-- Select Mechanic Sent --</option>
                                ${availableMechanics.map(m => `<option value="${m.name}">${m.name} (${m.specialty.split(' ')[0]})</option>`).join('')}
                            </select>
                            <button class="btn btn-sm btn-outline dispatch-mechanic-btn" data-truck="${fleet.truck}">
                                🔧 Dispatch Mechanic
                            </button>
                            <button class="btn btn-sm btn-secondary view-history-btn" data-truck="${fleet.truck}">
                                📋 Incident History
                            </button>
                        </div>
                    </td>
                `;
                fragment.appendChild(tr);
            });
            dispatchContainer.appendChild(fragment);
            return true;
        };

        window.renderIncidentSection = function() {
            let incidentWrapper = document.getElementById('incident-report-wrapper');
            if (!incidentWrapper) {
                const tableCard = document.querySelector('.card') || document.body;
                incidentWrapper = document.createElement('div');
                incidentWrapper.id = 'incident-report-wrapper';
                tableCard.parentNode.appendChild(incidentWrapper);
            }

            if (currentUserRole === 'client') {
                incidentWrapper.style.display = 'none';
                return;
            }

            incidentWrapper.style.display = 'block';
            incidentWrapper.style.cssText = "margin-top: 2rem; padding: 1.5rem; background: #f8f9fa; border: 1px solid #ddd; border-radius: 8px;";
            incidentWrapper.innerHTML = `
                <h3>🚨 Internal Roadside / Yard Incident Report & Spare Parts Log</h3>
                <p style="font-size: 0.9rem; color: #666;">Restricted to company employees and mechanics. Log mechanical failures, parts usage, and receipts.</p>
                
                <form id="incident-form" style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-top: 1rem;">
                    <div>
                        <label style="font-size: 0.85rem; font-weight: bold;">Truck Registration</label>
                        <select id="incident-truck" class="form-control" required>
                            <option value="">-- Choose Truck --</option>
                            ${activeFleet.map(f => `<option value="${f.truck}">${f.truck} (${f.driver})</option>`).join('')}
                        </select>
                    </div>
                    <div>
                        <label style="font-size: 0.85rem; font-weight: bold;">Incident Type</label>
                        <select id="incident-type" class="form-control" required>
                            <option value="Mechanical Breakdown">Mechanical Breakdown (Engine/Gearbox)</option>
                            <option value="Overheating Alert">Overheating Alert (OBD Trigger)</option>
                            <option value="Tyre Blowout">Tyre Blowout / Puncture</option>
                            <option value="Road Accident">Road Accident / Collision</option>
                            <option value="Transit Delay">Transit Delay / Border Hold-up</option>
                        </select>
                    </div>
                    <div>
                        <label style="font-size: 0.85rem; font-weight: bold;">Severity Level</label>
                        <select id="incident-severity" class="form-control" required>
                            <option value="Low">Low (Minor Delay)</option>
                            <option value="Medium">Medium (Requires Yard Support)</option>
                            <option value="Critical">Critical (Immediate Tow / Medical Assistance)</option>
                        </select>
                    </div>
                    <div>
                        <label style="font-size: 0.85rem; font-weight: bold;">Assigned Mechanic / Responder</label>
                        <select id="incident-mechanic" class="form-control">
                            <option value="None">-- Select Responding Mechanic --</option>
                            ${availableMechanics.map(m => `<option value="${m.name}">${m.name}</option>`).join('')}
                        </select>
                    </div>

                    <div>
                        <label style="font-size: 0.85rem; font-weight: bold;">Part / Item Replaced</label>
                        <input type="text" id="replaced-part" class="form-control" placeholder="e.g., Heavy Duty Tubeless Tyres">
                    </div>
                    <div>
                        <label style="font-size: 0.85rem; font-weight: bold;">Quantity Replaced</label>
                        <input type="number" id="part-qty" class="form-control" min="1" value="1">
                    </div>
                    <div>
                        <label style="font-size: 0.85rem; font-weight: bold;">Source of Parts</label>
                        <select id="part-source" class="form-control">
                            <option value="Yard Stock">Yard Stock (In-House Inventory)</option>
                            <option value="Purchased">Purchased Externally</option>
                        </select>
                    </div>
                    <div id="receipt-upload-container" style="display: none;">
                        <label style="font-size: 0.85rem; font-weight: bold; color: #0056b3;">Attach Purchase Receipt / Invoice</label>
                        <input type="file" id="receipt-file" class="form-control" accept="image/*,.pdf">
                    </div>

                    <div style="grid-column: span 2;">
                        <label style="font-size: 0.85rem; font-weight: bold;">Detailed Description & Corrective Actions</label>
                        <textarea id="incident-notes" class="form-control" rows="3" placeholder="Describe exact location, symptoms, and immediate actions taken..." required></textarea>
                    </div>
                    <div style="grid-column: span 2;">
                        <button type="submit" class="btn btn-danger">Submit Internal Incident Report</button>
                    </div>
                </form>

                <div id="truck-history-display" style="margin-top: 1.5rem; display: none;">
                    <hr>
                    <h4 id="history-title"></h4>
                    <div id="history-content" style="max-height: 250px; overflow-y: auto;"></div>
                </div>
            `;

            const sourceSelect = document.getElementById('part-source');
            const receiptContainer = document.getElementById('receipt-upload-container');
            if (sourceSelect && receiptContainer) {
                sourceSelect.addEventListener('change', () => {
                    receiptContainer.style.display = sourceSelect.value === 'Purchased' ? 'block' : 'none';
                });
            }
        };

        // Event delegation
        document.addEventListener('click', (e) => {
            const target = e.target;
            if (target.classList.contains('dispatch-mechanic-btn')) {
                const truckName = target.getAttribute('data-truck');
                const row = target.closest('tr');
                const selectDropdown = row ? row.querySelector('.mechanic-select') : null;
                const chosenMechanic = selectDropdown ? selectDropdown.value : '';

                if (!chosenMechanic) {
                    showToast("Please select a mechanic from the dropdown first!", "error");
                    return;
                }
                showToast(`Successfully dispatched mechanic ${chosenMechanic} to truck ${truckName}!`, "success");
            }

            if (target.classList.contains('view-history-btn')) {
                const truckName = target.getAttribute('data-truck');
                const historyDisplay = document.getElementById('truck-history-display');
                const historyTitle = document.getElementById('history-title');
                const historyContent = document.getElementById('history-content');

                if (historyDisplay && historyTitle && historyContent) {
                    historyDisplay.style.display = 'block';
                    historyTitle.innerText = `📁 Internal Incident History & Spare Parts Log: ${truckName}`;
                    
                    const records = truckIncidentHistories[truckName] || [];
                    if (records.length === 0) {
                        historyContent.innerHTML = `<p style="color: #666; font-style: italic; padding: 0.5rem 0;">No prior incident records found for ${truckName}.</p>`;
                    } else {
                        let html = '<table class="table table-sm" style="width:100%; font-size:0.85rem; border-collapse: collapse;">';
                        html += '<tr style="background:#eee;"><th>Date</th><th>Type</th><th>Severity</th><th>Mechanic</th><th>Replaced Parts</th><th>Source</th><th>Notes</th></tr>';
                        records.forEach(r => {
                            html += `<tr>
                                <td>${r.date}</td>
                                <td>${r.type}</td>
                                <td>${r.severity}</td>
                                <td>${r.mechanic}</td>
                                <td>${r.parts}</td>
                                <td>${r.source}</td>
                                <td>${r.notes}</td>
                            </tr>`;
                        });
                        html += '</table>';
                        historyContent.innerHTML = html;
                    }
                    historyDisplay.scrollIntoView({ behavior: 'smooth' });
                }
            }
        });

        renderFleetDispatch();
        renderIncidentSection();
        return true;
    }

    // Try immediately, then retry on DOMContentLoaded if not ready
    if (!initDispatchModule()) {
        document.addEventListener('DOMContentLoaded', initDispatchModule);
    }
})();