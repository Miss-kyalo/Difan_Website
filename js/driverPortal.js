document.addEventListener('DOMContentLoaded', () => {
    const switchForm = document.getElementById('vehicle-switch-form');
    const returnForm = document.getElementById('goods-return-form');
    const driverSwitchPanel = document.getElementById('driver-switch-panel');
    const switchLoadButton = document.getElementById('show-switch-load-form');
    const switchFormContent = document.getElementById('switch-load-form-content');
    const managerReview = document.getElementById('fleet-manager-review');
    const fleetNavigation = document.getElementById('fleet-navigation');
    const fleetView = document.getElementById('view-fleet');
    const fleetVehicleTable = document.getElementById('fleet-vehicle-table');
    const fleetVehicleRows = document.getElementById('fleet-vehicle-rows');
    const switchRequestsView = document.getElementById('fleet-switch-requests');
    const goodsReturnsView = document.getElementById('fleet-goods-returns');
    const driverSwitchHistory = document.getElementById('driver-switch-history');
    const driverReturnHistory = document.getElementById('driver-return-history');
    const driverGoodsWorkflow = document.getElementById('driver-goods-workflow');
    const fleetGoodsReturnsPanel = document.getElementById('fleet-goods-returns-panel');
    const roleSwitcher = document.getElementById('role-switcher-select');
    const goodsNavigation = document.getElementById('goods-navigation');
    const goodsView = document.getElementById('view-goods');
    const goodsDocumentUploadPanel = document.getElementById('goods-document-upload-panel');
    const goodsDocumentAccessPanel = document.getElementById('goods-document-access-panel');

    if (!switchForm || !returnForm || !driverSwitchPanel || !driverGoodsWorkflow ||
        !fleetGoodsReturnsPanel || !goodsNavigation || !goodsView ||
        !goodsDocumentUploadPanel || !goodsDocumentAccessPanel || !switchLoadButton ||
        !switchFormContent || !managerReview || !fleetNavigation ||
        !fleetView || !fleetVehicleTable || !fleetVehicleRows || !roleSwitcher) return;

    const STORAGE_KEYS = {
        switches: 'difan_vehicle_switch_requests',
        returns: 'difan_goods_returns'
    };
    const INITIAL_VEHICLES = {
        'peter ochieng': 'KCB-402L'
    };

    function showError(message) {
        window.DifanApp?.showToast(message, 'error');
    }

    function readRecords(key) {
        try {
            const stored = localStorage.getItem(key);
            if (!stored) return [];
            const records = JSON.parse(stored);
            if (!Array.isArray(records)) throw new Error('Stored workflow data is not a list.');
            return records;
        } catch (error) {
            console.error(`Unable to read ${key}:`, error);
            showError('Could not load driver workflow records from this browser.');
            return [];
        }
    }

    function saveRecords(key, records) {
        try {
            localStorage.setItem(key, JSON.stringify(records));
            return true;
        } catch (error) {
            console.error(`Unable to save ${key}:`, error);
            showError('Could not save this record in the browser. Check available storage and try again.');
            return false;
        }
    }

    function escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, character => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        })[character]);
    }

    function makeId() {
        return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }

    function getCurrentUser() {
        return window.DifanApp?.state?.currentUser || { name: 'Driver', role: 'client' };
    }

    function getCurrentVehicle(driverName, requests = readRecords(STORAGE_KEYS.switches)) {
        const approved = requests
            .filter(request => request.driverName === driverName && request.status === 'APPROVED')
            .sort((left, right) => new Date(right.approvedAt || right.createdAt) - new Date(left.approvedAt || left.createdAt));
        return approved[0]?.requestedVehicle || INITIAL_VEHICLES[driverName.toLowerCase()] || '';
    }

    function formatDate(value) {
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? 'Date unavailable' : date.toLocaleString();
    }

    function statusBadge(status) {
        const safeStatus = String(status || 'UNKNOWN').toLowerCase();
        return `<span class="workflow-status workflow-status-${escapeHtml(safeStatus)}">${escapeHtml(status || 'Unknown')}</span>`;
    }

    function recordCard(title, status, details, actions = '') {
        return `
            <article class="workflow-card">
                <h3><span>${escapeHtml(title)}</span>${statusBadge(status)}</h3>
                ${details}
                ${actions ? `<div class="workflow-card-actions">${actions}</div>` : ''}
            </article>
        `;
    }

    function detail(label, value) {
        return `<p><strong>${escapeHtml(label)}:</strong> ${escapeHtml(value || '—')}</p>`;
    }

    function renderDriverViews() {
        const user = getCurrentUser();
        const driverName = user.name || 'Driver';
        const requests = readRecords(STORAGE_KEYS.switches);
        const returns = readRecords(STORAGE_KEYS.returns);
        const currentVehicle = getCurrentVehicle(driverName, requests);
        const currentVehicleInput = document.getElementById('switch-current-vehicle');
        const currentVehicleBadge = document.getElementById('driver-current-vehicle');
        const handoverDriverInput = document.getElementById('switch-driver-from');

        if (currentVehicleInput) currentVehicleInput.value = currentVehicle || 'Not assigned';
        if (currentVehicleBadge) currentVehicleBadge.textContent = `Current: ${currentVehicle || 'Not assigned'}`;
        if (handoverDriverInput) handoverDriverInput.value = driverName;

        const ownRequests = requests
            .filter(request => request.driverName === driverName)
            .sort((left, right) => new Date(right.createdAt) - new Date(left.createdAt));
        driverSwitchHistory.innerHTML = ownRequests.length
            ? ownRequests.map(request => recordCard(
                `${request.currentVehicle} → ${request.requestedVehicle}`,
                request.status,
                [
                    detail('Goods', request.goodsStatus),
                    detail('Driver handover', `${request.handedOverFrom} → ${request.handedOverTo}`),
                    detail('Cargo weight', `${request.cargoWeight} tonnes`),
                    detail('Fuel', `${request.fuelLevel}%`),
                    detail('Requested', formatDate(request.createdAt)),
                    request.notes ? detail('Notes', request.notes) : ''
                ].join('')
            )).join('')
            : '<p class="workflow-empty">No vehicle switch requests yet.</p>';

        const ownReturns = returns
            .filter(record => record.driverName === driverName)
            .sort((left, right) => new Date(right.createdAt) - new Date(left.createdAt));
        driverReturnHistory.innerHTML = ownReturns.length
            ? ownReturns.map(record => recordCard(
                record.deliveryReferences.join(', '),
                'Recorded',
                [
                    detail('Goods returned', record.goodsReturned),
                    detail('Weight', `${record.returnedWeight} kg`),
                    detail('Condition', record.goodsCondition),
                    detail('Returned by', record.returnedBy),
                    detail('Handed over to', record.handedOverTo),
                    detail('Recorded', formatDate(record.createdAt))
                ].join('')
            )).join('')
            : '<p class="workflow-empty">No returned goods have been recorded yet.</p>';
    }

    function renderManagerViews() {
        const requests = readRecords(STORAGE_KEYS.switches)
            .sort((left, right) => new Date(right.createdAt) - new Date(left.createdAt));
        const returns = readRecords(STORAGE_KEYS.returns)
            .sort((left, right) => new Date(right.createdAt) - new Date(left.createdAt));
        const pendingRequests = requests.filter(request => request.status === 'PENDING_APPROVAL');

        switchRequestsView.innerHTML = requests.length
            ? requests.map(request => {
                const actions = request.status === 'PENDING_APPROVAL'
                    ? `<button type="button" class="btn btn-success" data-switch-action="approve" data-switch-id="${escapeHtml(request.id)}">Approve switch</button>
                       <button type="button" class="btn btn-danger" data-switch-action="reject" data-switch-id="${escapeHtml(request.id)}">Reject</button>`
                    : '';
                return recordCard(
                    `${request.driverName}: ${request.currentVehicle} → ${request.requestedVehicle}`,
                    request.status,
                    [
                        detail('Goods status', request.goodsStatus),
                        detail('Driver handover', `${request.handedOverFrom} → ${request.handedOverTo}`),
                        detail('Cargo weight', `${request.cargoWeight} tonnes`),
                        detail('Fuel level', `${request.fuelLevel}%`),
                        detail('Condition notes', request.notes),
                        detail('Submitted', formatDate(request.createdAt)),
                        request.reviewedBy ? detail('Reviewed by', request.reviewedBy) : ''
                    ].join(''),
                    actions
                );
            }).join('')
            : '<p class="workflow-empty">No vehicle switch requests are waiting for review.</p>';

        const pendingNote = document.getElementById('fleet-pending-switch-count');
        if (pendingNote) {
            pendingNote.textContent = `${pendingRequests.length} pending`;
        }

        goodsReturnsView.innerHTML = returns.length
            ? returns.map(record => recordCard(
                record.deliveryReferences.join(', '),
                'Recorded',
                [
                    detail('Driver', record.driverName),
                    detail('Goods returned', record.goodsReturned),
                    detail('Weight', `${record.returnedWeight} kg`),
                    detail('Condition', record.goodsCondition),
                    detail('Returned by', record.returnedBy),
                    detail('Handed over to', record.handedOverTo),
                    detail('Recorded', formatDate(record.createdAt)),
                    record.notes ? detail('Notes', record.notes) : ''
                ].join('')
            )).join('')
            : '<p class="workflow-empty">No goods return records have been submitted.</p>';
    }

    function renderFleetBoard() {
        const isAdmin = ['admin', 'hr'].includes(getCurrentUser().role);
        const vehicles = [
            { registration: 'KDA-482P', driver: 'John Doe', status: 'In Transit', destination: 'Mombasa', location: 'Athi River' },
            { registration: 'KDA-8821', driver: 'John Mwangi', status: 'Breakdown', destination: '', location: 'Salama Corridor (A109)' },
            { registration: 'KDB-911X', driver: 'Peter Kamau', status: 'Breakdown', destination: '', location: 'Location unavailable' },
            { registration: 'KDD-119P', driver: 'Samuel Gitau', status: 'Awaiting Dispatch', destination: '', location: 'Athi River depot' }
        ];
        const locationHeader = isAdmin ? '<th scope="col">Location / Destination</th>' : '';
        fleetVehicleTable.querySelector('thead').innerHTML = `
            <tr>
                <th scope="col">Truck</th>
                <th scope="col">Driver</th>
                <th scope="col">Status</th>
                ${locationHeader}
            </tr>
        `;
        fleetVehicleRows.innerHTML = vehicles.map(vehicle => {
            const statusClass = vehicle.status === 'Breakdown' ? 'badge-danger'
                : vehicle.status === 'In Transit' ? 'badge-info' : 'badge-warning';
            return `
                <tr>
                    <td><strong>${escapeHtml(vehicle.registration)}</strong></td>
                    <td>${escapeHtml(vehicle.driver)}</td>
                    <td><span class="badge ${statusClass}">${escapeHtml(vehicle.status)}</span></td>
                    ${isAdmin ? `<td>${vehicle.status === 'In Transit'
                        ? `In transit to <strong>${escapeHtml(vehicle.destination)}</strong><br><small>Last known location: ${escapeHtml(vehicle.location)}</small>`
                        : escapeHtml(vehicle.location)}</td>` : ''}
                </tr>
            `;
        }).join('');
    }

    function render() {
        const role = getCurrentUser().role;
        const isDriver = role === 'driver';
        const isFleetManager = role === 'admin' || role === 'hr';
        const isClient = role === 'client';
        driverGoodsWorkflow.hidden = !isDriver;
        fleetGoodsReturnsPanel.hidden = !isFleetManager;
        driverSwitchPanel.hidden = !isDriver;
        managerReview.hidden = !isFleetManager;
        fleetNavigation.hidden = isClient;
        fleetView.hidden = isClient;
        const canAccessGoods = ['client', 'driver', 'admin', 'hr'].includes(role);
        goodsNavigation.hidden = !canAccessGoods;
        goodsView.hidden = !canAccessGoods;
        goodsDocumentUploadPanel.hidden = !isDriver;
        goodsDocumentAccessPanel.hidden = !(isClient || isFleetManager);
        if (!isDriver) {
            switchFormContent.hidden = true;
            switchLoadButton.setAttribute('aria-expanded', 'false');
        }
        if (isClient && window.DifanApp?.state?.activeTab === 'fleet') {
            document.querySelector('.nav-link[data-target-tab="dashboard"]')?.click();
        }
        if (isClient && window.DifanApp?.state?.activeTab === 'goods') {
            document.querySelector('.nav-link[data-target-tab="dashboard"]')?.click();
        }
        renderFleetBoard();
        if (isDriver) renderDriverViews();
        if (isFleetManager) renderManagerViews();
    }

    switchForm.addEventListener('submit', event => {
        event.preventDefault();
        const user = getCurrentUser();
        const formData = new FormData(switchForm);
        const requests = readRecords(STORAGE_KEYS.switches);
        const requestedVehicle = String(formData.get('requestedVehicle') || '').trim().toUpperCase();
        const currentVehicle = getCurrentVehicle(user.name, requests);

        if (requestedVehicle === currentVehicle.toUpperCase()) {
            showError('Choose a different vehicle from your current assignment.');
            return;
        }
        if (requests.some(request => request.driverName === user.name && request.status === 'PENDING_APPROVAL')) {
            showError('You already have a vehicle switch waiting for Fleet Manager approval.');
            return;
        }

        const request = {
            id: makeId(),
            driverName: user.name,
            currentVehicle,
            requestedVehicle,
            handedOverFrom: user.driver_name || user.name,
            handedOverTo: String(formData.get('handedOverTo') || '').trim(),
            goodsStatus: formData.get('goodsStatus'),
            cargoWeight: Number(formData.get('cargoWeight')),
            fuelLevel: Number(formData.get('fuelLevel')),
            notes: String(formData.get('notes') || '').trim(),
            status: 'PENDING_APPROVAL',
            createdAt: new Date().toISOString()
        };

        if (!Number.isFinite(request.cargoWeight) || request.cargoWeight < 0 ||
            !Number.isFinite(request.fuelLevel) || request.fuelLevel < 0 || request.fuelLevel > 100) {
            showError('Enter a valid cargo weight and a fuel level between 0 and 100%.');
            return;
        }

        if (!saveRecords(STORAGE_KEYS.switches, [request, ...requests])) return;
        switchForm.reset();
        render();
        window.DifanApp?.showToast('Vehicle switch submitted for Fleet Manager approval.', 'success');
    });

    returnForm.addEventListener('submit', event => {
        event.preventDefault();
        const user = getCurrentUser();
        const formData = new FormData(returnForm);
        const deliveryReferences = String(formData.get('deliveryReferences') || '')
            .split(/[,\n]+/)
            .map(reference => reference.trim())
            .filter(Boolean);
        const returnedWeight = Number(formData.get('returnedWeight'));

        if (!deliveryReferences.length || !Number.isFinite(returnedWeight) || returnedWeight < 0) {
            showError('Enter at least one delivery reference and a valid returned weight.');
            return;
        }

        const record = {
            id: makeId(),
            driverName: user.name,
            deliveryReferences: [...new Set(deliveryReferences)],
            goodsReturned: String(formData.get('goodsReturned') || '').trim(),
            returnedWeight,
            goodsCondition: formData.get('goodsCondition'),
            returnedBy: String(formData.get('returnedBy') || '').trim(),
            handedOverTo: String(formData.get('handedOverTo') || '').trim(),
            notes: String(formData.get('notes') || '').trim(),
            createdAt: new Date().toISOString()
        };
        const returns = readRecords(STORAGE_KEYS.returns);
        if (!saveRecords(STORAGE_KEYS.returns, [record, ...returns])) return;
        returnForm.reset();
        document.getElementById('return-returned-by').value = user.name || '';
        render();
        window.DifanApp?.showToast('Returned goods recorded.', 'success');
    });

    switchRequestsView.addEventListener('click', event => {
        const button = event.target.closest('[data-switch-action]');
        if (!button || !['admin', 'hr'].includes(getCurrentUser().role)) return;

        const requests = readRecords(STORAGE_KEYS.switches);
        const request = requests.find(item => item.id === button.dataset.switchId);
        if (!request || request.status !== 'PENDING_APPROVAL') return;

        const approved = button.dataset.switchAction === 'approve';
        const updatedRequests = requests.map(item => item.id === request.id
            ? {
                ...item,
                status: approved ? 'APPROVED' : 'REJECTED',
                reviewedBy: getCurrentUser().name,
                reviewedAt: new Date().toISOString(),
                ...(approved ? { approvedAt: new Date().toISOString() } : {})
            }
            : item
        );
        if (!saveRecords(STORAGE_KEYS.switches, updatedRequests)) return;
        render();
        window.DifanApp?.showToast(
            approved ? 'Vehicle switch approved; assignment updated.' : 'Vehicle switch rejected.',
            approved ? 'success' : 'warning'
        );
    });

    roleSwitcher.addEventListener('change', render);
    window.addEventListener('difan:session-ready', render);
    switchLoadButton.addEventListener('click', () => {
        const isOpening = switchFormContent.hidden;
        switchFormContent.hidden = !isOpening;
        switchLoadButton.setAttribute('aria-expanded', String(isOpening));
        if (isOpening) {
            document.getElementById('switch-requested-vehicle').focus();
        }
    });
    document.getElementById('return-returned-by').value = getCurrentUser().name || '';
    render();
});
