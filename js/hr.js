/**
 * DIFAN LOGISTICS (K) LTD - Human Resources & Payroll Module (hr.js)
 * Manages employee rosters, duty status updates, automated Kenyan statutory 
 * tax deductions (PAYE, SHIF, NSSF, Housing Levy), digital payslip signing, 
 * self-service P9 generation, and OCR delivery note scanning.
 */

document.addEventListener('DOMContentLoaded', () => {

    // Safe helper for Toast Notifications
    const showToast = (message, type = 'success') => {
        if (window.DifanApp && typeof window.DifanApp.showToast === 'function') {
            window.DifanApp.showToast(message, type);
        } else {
            console.log(`[Toast ${type}]: ${message}`);
        }
    };

    // Safe helper for Currency Formatting
    const formatCurrency = (amount) => {
        if (window.DifanApp && typeof window.DifanApp.formatCurrency === 'function') {
            return window.DifanApp.formatCurrency(amount);
        }
        return `KES ${Number(amount).toLocaleString('en-KE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    };

    // Get current session role from global app state if available, default to accountant
    const getCurrentUser = () => {
        if (window.DifanApp && window.DifanApp.state && window.DifanApp.state.currentUser) {
            return window.DifanApp.state.currentUser;
        }
        return { name: "Mary Wambui", role: "accountant" };
    };

    // 1. TOP DRIVERS LEADERBOARD
    const topDriversData = [
        { rank: 1, name: "Peter Ochieng", trips: 42, rating: "99.2%", truck: "KCB-402L" },
        { rank: 2, name: "Samuel Gitau", trips: 38, rating: "97.8%", truck: "KDD-119P" },
        { rank: 3, name: "John Mwangi", trips: 31, rating: "91.0%", truck: "KDA-8821" }
    ];

    // 2. EMPLOYEE & STAFF DIRECTORY
    const staffRoster = [
        { id: 101, name: "Peter Ochieng", role: "Long-Haul Driver", truck: "KCB-402L", phone: "+254 712 345678", status: "active", pin: "A012345678Z" },
        { id: 102, name: "John Mwangi", role: "Articulated Driver", truck: "KDA-8821", phone: "+254 722 987654", status: "maintenance", pin: "A098765432X" },
        { id: 103, name: "Samuel Gitau", role: "Rigid Truck Driver", truck: "KDD-119P", phone: "+254 733 112233", status: "active", pin: "A055667788Y" },
        { id: 104, name: "Mary Wambui", role: "Chief Accountant", truck: "N/A (HQ)", phone: "+254 720 001122", status: "active", pin: "P051122334M" },
        { id: 105, name: "David Kiprop", role: "Fleet HR Officer", truck: "N/A (HQ)", phone: "+254 711 445566", status: "leave", pin: "P099887766K" },
        { id: 106, name: "Erick Omondi", role: "Lead Mechanic", truck: "N/A (Yard)", phone: "+254 721 554433", status: "active", pin: "M012345678Q" },
        { id: 107, name: "Josephat Mutua", role: "Yard Assistant", truck: "N/A (Yard)", phone: "+254 731 223344", status: "active", pin: "M087654321R" }
    ];

    // 3. PAYROLL DATASET
    const payrollData = [
        {
            id: 1,
            driver: "Peter Ochieng",
            base: 65000,
            bonus: 12000,
            bonusReason: "Top Trip Efficiency & Safety",
            docked: 0,
            dockedReason: "Clean Record",
            acknowledged: false,
            signed: false,
            signedTimestamp: null
        },
        {
            id: 2,
            driver: "John Mwangi",
            base: 60000,
            bonus: 3000,
            bonusReason: "On-time Deliveries",
            docked: 7500,
            dockedReason: "OBD Overheat Negligence",
            acknowledged: false,
            signed: false,
            signedTimestamp: null
        },
        {
            id: 3,
            driver: "Samuel Gitau",
            base: 58000,
            bonus: 5500,
            bonusReason: "Zero Idle Time Bonus",
            docked: 1500,
            dockedReason: "Harsh Braking Event",
            acknowledged: false,
            signed: false,
            signedTimestamp: null
        }
    ];

    // KENYA STATUTORY DEDUCTION ENGINE (2026 Tax Bands)
    function calculateStatutories(grossPay) {
        const safeGross = Math.max(0, Number(grossPay) || 0);

        const nssf = Math.min(safeGross * 0.06, 2160);
        const shif = safeGross * 0.0275;
        const hlevy = safeGross * 0.015;
        const nita = 50;

        const taxablePay = Math.max(0, safeGross - nssf - shif);

        let payeGross = 0;
        if (taxablePay <= 24000) {
            payeGross = taxablePay * 0.10;
        } else if (taxablePay <= 32333) {
            payeGross = (24000 * 0.10) + ((taxablePay - 24000) * 0.25);
        } else if (taxablePay <= 500000) {
            payeGross = (24000 * 0.10) + (8333 * 0.25) + ((taxablePay - 32333) * 0.30);
        } else if (taxablePay <= 800000) {
            payeGross = (24000 * 0.10) + (8333 * 0.25) + (467667 * 0.30) + ((taxablePay - 500000) * 0.325);
        } else {
            payeGross = (24000 * 0.10) + (8333 * 0.25) + (467667 * 0.30) + (300000 * 0.325) + ((taxablePay - 800000) * 0.35);
        }

        const personalRelief = 2400;
        const paye = Math.max(0, payeGross - personalRelief);

        const totalEmployeeDeductions = nssf + shif + hlevy + paye;
        const expectedNetPay = safeGross - totalEmployeeDeductions;

        return {
            nssf,
            shif,
            hlevy,
            paye,
            nita,
            totalEmployeeDeductions,
            expectedNetPay
        };
    }

    // RENDER LEADERBOARD
    window.renderLeaderboard = function() {
        const container = document.getElementById('leaderboard-container');
        if (!container) return;
        container.innerHTML = '';

        const fragment = document.createDocumentFragment();
        topDriversData.forEach(d => {
            const card = document.createElement('div');
            card.className = 'leader-card';
            card.innerHTML = `
                <div class="leader-rank">#${d.rank}</div>
                <div>
                    <strong>${d.name}</strong> (${d.truck})
                    <div style="font-size:0.85rem; color: #666;">
                        Trips: <strong>${d.trips}</strong> | Rating: <span style="color: #28a745;">${d.rating}</span>
                    </div>
                </div>
            `;
            fragment.appendChild(card);
        });
        container.appendChild(fragment);
    };

    // RENDER STAFF ROSTER
    window.renderRoster = function() {
        const container = document.getElementById('roster-rows');
        if (!container) return;
        container.innerHTML = '';

        const currentUser = getCurrentUser();
        const canManage = currentUser.role === 'admin' || currentUser.role === 'accountant';
        const fragment = document.createDocumentFragment();

        staffRoster.forEach(emp => {
            let icon = '🟢';
            let statusText = 'On Duty';
            if (emp.status === 'leave') {
                icon = '🟠';
                statusText = 'On Leave';
            } else if (emp.status === 'maintenance') {
                icon = '🔴';
                statusText = 'Off-Duty (Truck Fault)';
            }

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><span title="${statusText}">${icon}</span></td>
                <td><strong>${emp.name}</strong></td>
                <td>${emp.role}</td>
                <td><code>${emp.truck}</code></td>
                <td><a href="tel:${emp.phone}">${emp.phone}</a></td>
                <td>
                    ${canManage ? `
                        <button class="btn btn-sm btn-secondary toggle-leave-btn" data-id="${emp.id}">
                            ${emp.status === 'leave' ? 'Return Duty' : 'Mark Leave'}
                        </button>
                    ` : '<span style="color:#666; font-size:0.85rem;">View Only</span>'}
                </td>
            `;
            fragment.appendChild(tr);
        });
        container.appendChild(fragment);
    };

    // RENDER PAYROLL TABLE (ACCOUNTANT SEES ALL; DRIVERS SEE ONLY THEIR OWN PAY SUMMARY, PAYSLIP & P9)
    window.renderPayroll = function() {
        const container = document.getElementById('hr-payroll-rows');
        const batchBtn = document.getElementById('btn-batch-payroll');
        if (!container) return;
        container.innerHTML = '';

        const currentUser = getCurrentUser();
        const isAccountant = currentUser.role === 'accountant';

        if (batchBtn) {
            batchBtn.style.display = isAccountant ? 'inline-block' : 'none';
        }

        let visiblePayroll = [];
        if (isAccountant) {
            // Accountant sees everyone's payroll summary
            visiblePayroll = payrollData;
        } else {
            // Drivers and other staff see ONLY their own respective pay entry
            visiblePayroll = payrollData.filter(item => item.driver.toLowerCase() === currentUser.name.toLowerCase());
        }

        if (visiblePayroll.length === 0) {
            container.innerHTML = `
                <tr>
                    <td colspan="15" style="text-align:center; padding: 2rem; color: #666;">
                        No active payroll record found assigned to user <strong>${currentUser.name}</strong>.
                    </td>
                </tr>`;
            return;
        }

        const fragment = document.createDocumentFragment();
        visiblePayroll.forEach(item => {
            const grossPay = item.base + item.bonus - item.docked;
            const stats = calculateStatutories(grossPay);

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><strong>${item.driver}</strong></td>
                <td>${formatCurrency(item.base)}</td>
                <td><span style="color:#28a745;">+${formatCurrency(item.bonus)}</span><br><small>(${item.bonusReason})</small></td>
                <td><span style="color:#dc3545;">-${formatCurrency(item.docked)}</span><br><small>(${item.dockedReason})</small></td>
                <td><strong>${formatCurrency(grossPay)}</strong></td>
                <td>${formatCurrency(stats.nssf)}</td>
                <td>${formatCurrency(stats.shif)}</td>
                <td>${formatCurrency(stats.hlevy)}</td>
                <td>${formatCurrency(stats.paye)}</td>
                <td>${formatCurrency(stats.nita)}</td>
                <td style="color:#dc3545;">${formatCurrency(stats.totalEmployeeDeductions)}</td>
                <td style="color:#28a745;"><strong>${formatCurrency(stats.expectedNetPay)}</strong></td>
                <td>
                    <div style="display:flex; flex-direction:column; gap:0.3rem;">
                        <label style="font-size:0.75rem; cursor:pointer;">
                            <input type="checkbox" class="ack-checkbox" data-id="${item.id}" ${item.acknowledged ? 'checked' : ''} ${item.signed ? 'disabled' : ''}>
                            Accept Payslip
                        </label>
                        <button class="btn btn-sm btn-success sign-pay-btn" data-id="${item.id}" ${(!item.acknowledged || item.signed) ? 'disabled' : ''}>
                            ${item.signed ? '✍️ Signed' : 'Sign Payslip'}
                        </button>
                        <button class="btn btn-sm btn-secondary download-payslip-btn" data-id="${item.id}" ${!item.signed ? 'disabled' : ''}>
                            📄 Download PDF
                        </button>
                        <button class="btn btn-sm btn-outline generate-p9-btn" data-id="${item.id}">
                            📊 P9 Form
                        </button>
                    </div>
                </td>
            `;
            fragment.appendChild(tr);
        });
        container.appendChild(fragment);
    };

    // EVENT LISTENERS FOR HR ACTIONS
    document.addEventListener('click', (e) => {
        const target = e.target;
        const currentUser = getCurrentUser();

        // Toggle leave status
        if (target.classList.contains('toggle-leave-btn')) {
            const id = parseInt(target.getAttribute('data-id'), 10);
            const emp = staffRoster.find(s => s.id === id);
            if (emp) {
                emp.status = emp.status === 'leave' ? 'active' : 'leave';
                showToast(`Duty status updated for ${emp.name}`);
                renderRoster();
            }
        }

        // Sign payslip digitally
        if (target.classList.contains('sign-pay-btn')) {
            const id = parseInt(target.getAttribute('data-id'), 10);
            const p = payrollData.find(item => item.id === id);
            if (p && p.acknowledged) {
                p.signed = true;
                p.signedTimestamp = new Date().toLocaleString();
                showToast(`Payslip signed digitally successfully!`);
                renderPayroll();
            }
        }

        // Download signed payslip
        if (target.classList.contains('download-payslip-btn')) {
            const id = parseInt(target.getAttribute('data-id'), 10);
            const p = payrollData.find(item => item.id === id);
            if (p && p.signed) generatePayslipWindow(p);
        }

        // Generate P9 tax form
        if (target.classList.contains('generate-p9-btn')) {
            const id = parseInt(target.getAttribute('data-id'), 10);
            const p = payrollData.find(item => item.id === id);
            if (p) generateP9FormWindow(p);
        }
    });

    document.addEventListener('change', (e) => {
        if (e.target.classList.contains('ack-checkbox')) {
            const id = parseInt(e.target.getAttribute('data-id'), 10);
            const p = payrollData.find(item => item.id === id);
            if (p) {
                p.acknowledged = e.target.checked;
                renderPayroll();
            }
        }
    });

    // POPUP PAYSLIP WINDOW
    function generatePayslipWindow(item) {
        const grossPay = item.base + item.bonus - item.docked;
        const stats = calculateStatutories(grossPay);

        const win = window.open('', '_blank', 'width=800,height=900');
        if (!win) {
            alert("Popup blocked! Please allow popups.");
            return;
        }

        win.document.write(`
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <title>Payslip - ${item.driver}</title>
                <style>
                    body { font-family: Arial, sans-serif; padding: 2rem; color: #333; line-height: 1.4; }
                    .header { text-align: center; border-bottom: 2px solid #0056b3; padding-bottom: 1rem; margin-bottom: 1.5rem; }
                    .table-summary { width: 100%; border-collapse: collapse; margin-bottom: 1.5rem; }
                    .table-summary th, .table-summary td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; }
                    .table-summary th { background-color: #f2f2f2; }
                    .sig { border: 1px dashed #28a745; background: #e8f8f5; padding: 1rem; margin-top: 2rem; border-radius: 6px; }
                    button { background: #0056b3; color: white; border: none; padding: 10px 20px; cursor: pointer; border-radius: 4px; }
                    @media print { button { display: none; } }
                </style>
            </head>
            <body>
                <div class="header">
                    <h2>DIFAN LOGISTICS (K) LTD</h2>
                    <p>Athi River Yard | Tel: +254 720 001122</p>
                    <h3>MONTHLY PAYSLIP</h3>
                </div>
                <p><strong>Employee:</strong> ${item.driver} | <strong>Designation:</strong> Heavy Commercial Driver</p>
                
                <h3>1. Earnings</h3>
                <table class="table-summary">
                    <tr><th>Component</th><th>Amount (KES)</th></tr>
                    <tr><td>Basic Salary</td><td>${item.base.toLocaleString()}</td></tr>
                    <tr><td>Bonus (${item.bonusReason})</td><td>+${item.bonus.toLocaleString()}</td></tr>
                    <tr><td>Deductions (${item.dockedReason})</td><td>-${item.docked.toLocaleString()}</td></tr>
                    <tr><th>Gross Pay</th><th>${grossPay.toLocaleString()}</th></tr>
                </table>

                <h3>2. Statutory Deductions</h3>
                <table class="table-summary">
                    <tr><td>NSSF (Tier I & II)</td><td>${stats.nssf.toLocaleString()}</td></tr>
                    <tr><td>SHIF (2.75%)</td><td>${stats.shif.toLocaleString()}</td></tr>
                    <tr><td>Housing Levy (1.5%)</td><td>${stats.hlevy.toLocaleString()}</td></tr>
                    <tr><td>PAYE (Net Relief)</td><td>${stats.paye.toLocaleString()}</td></tr>
                    <tr><th>Total Deductions</th><th>${stats.totalEmployeeDeductions.toLocaleString()}</th></tr>
                </table>

                <h3 style="color: #28a745;">NET TAKE HOME PAY: KES ${stats.expectedNetPay.toLocaleString()}</h3>

                <div class="sig">
                    <p><strong>✍️ Digitally Signed</strong></p>
                    <p>By: ${item.driver} on ${item.signedTimestamp}</p>
                </div>
                <br>
                <button onclick="window.print()">🖨️ Print / Save PDF</button>
            </body>
            </html>
        `);
        win.document.close();
    }

    // POPUP P9 FORM WINDOW
    function generateP9FormWindow(item) {
        const emp = staffRoster.find(s => s.name === item.driver) || { pin: 'A000000000Z' };
        const grossMonthly = item.base + item.bonus - item.docked;
        const stats = calculateStatutories(grossMonthly);
        const months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

        let rows = '';
        months.forEach(m => {
            rows += `<tr><td>${m}</td><td>${item.base.toLocaleString()}</td><td>${grossMonthly.toLocaleString()}</td><td>${stats.nssf.toLocaleString()}</td><td>${stats.paye.toLocaleString()}</td></tr>`;
        });

        const win = window.open('', '_blank', 'width=900,height=900');
        if (!win) return;

        win.document.write(`
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8"><title>KRA P9 Form - ${item.driver}</title>
                <style>
                    body { font-family: Arial, sans-serif; padding: 1.5rem; font-size: 12px; }
                    table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
                    th, td { border: 1px solid #000; padding: 6px; text-align: right; }
                    th { background: #f0f0f0; text-align: center; }
                    td:first-child { text-align: left; }
                    button { background: #0056b3; color: white; border: none; padding: 10px 20px; cursor: pointer; margin-top: 1rem; }
                    @media print { button { display: none; } }
                </style>
            </head>
            <body>
                <h2 align="center">KENYA REVENUE AUTHORITY - P9A TAX DEDUCTION CARD 2026</h2>
                <p><strong>Employer:</strong> DIFAN LOGISTICS (K) LTD | <strong>PIN:</strong> P051234567Z</p>
                <p><strong>Employee:</strong> ${item.driver} | <strong>PIN:</strong> ${emp.pin}</p>
                <table>
                    <thead><tr><th>Month</th><th>Basic (Kshs)</th><th>Gross (Kshs)</th><th>NSSF (Kshs)</th><th>PAYE (Kshs)</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table>
                <br><button onclick="window.print()">🖨️ Print P9 Form</button>
            </body>
            </html>
        `);
        win.document.close();
    }

    // OCR DELIVERY NOTE SCANNER SETUP
    function setupDeliveryNoteOCR() {
        const fileInput = document.getElementById('dn-ocr-file');
        const statusDisplay = document.getElementById('ocr-status');
        if (!fileInput) return;

        fileInput.addEventListener('change', async (event) => {
            const file = event.target.files[0];
            if (!file || typeof Tesseract === 'undefined') return;

            if (statusDisplay) statusDisplay.innerText = "🔍 Processing OCR scan...";
            try {
                const result = await Tesseract.recognize(file, 'eng');
                if (statusDisplay) statusDisplay.innerText = "✅ OCR Extraction Complete!";
                showToast("Delivery Note parsed successfully via OCR!");
            } catch (err) {
                if (statusDisplay) statusDisplay.innerText = "⚠️ OCR scan failed.";
            }
        });
    }

    // INITIALIZE HR MODULE
    renderLeaderboard();
    renderRoster();
    renderPayroll();
    setupDeliveryNoteOCR();
});