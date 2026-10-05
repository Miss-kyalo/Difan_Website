import datetime
from flask import Blueprint, jsonify, request

hr_bp = Blueprint('hr', __name__, url_prefix='/api/v1/hr')

# Extended mock database stores
DRIVERS = {
    "DRV-008": {
        "driverId": "DRV-008",
        "driverName": "John Doe",
        "kraPin": "A012345678Z",
        "basicPay": 45000,
        "housingAllowance": 12000,
        "consentSigned": True,
        "consentTimestamp": "2026-01-15T08:30:00Z"
    },
    "DRV-014": {
        "driverId": "DRV-014",
        "driverName": "Peter Kamau",
        "kraPin": "A087654321X",
        "basicPay": 48000,
        "housingAllowance": 12000,
        "consentSigned": False,
        "consentTimestamp": None
    }
}

TIMECARDS = [
    {
        "id": 101,
        "driverId": "DRV-008",
        "driverName": "John Doe",
        "kraPin": "A012345678Z",
        "vehicleReg": "KDA 482P",
        "detentionHours": 8,
        "status": "PAYROLL_PROCESSED",
        "payPeriod": "September 2026",
        "telematicsHold": False,
        "isOnLeave": False,
        "dtcCode": None,
        "basicPay": 45000,
        "housingAllowance": 12000,
        "grossPay": 60600.0,
        "netPay": 47250.0
    },
    {
        "id": 102,
        "driverId": "DRV-014",
        "driverName": "Peter Kamau",
        "kraPin": "A087654321X",
        "vehicleReg": "KDB 911X",
        "detentionHours": 14,
        "status": "PENDING_APPROVAL",
        "payPeriod": "September 2026",
        "telematicsHold": True,
        "isOnLeave": True,
        "dtcCode": "P0217",
        "basicPay": 48000,
        "housingAllowance": 12000,
        "grossPay": 66300.0,
        "netPay": 50800.0
    }
]

# Track signed timecards per driver: {(driverId, timecardId)}
SIGNED_PAYSLIPS = set()


def calculate_statutory_deductions(gross_pay: float) -> dict:
    """
    Calculates Kenyan statutory payroll deductions:
    - NSSF (6% capped at KES 2,160)
    - SHIF (2.75% of Gross, min KES 300)
    - Affordable Housing Levy (1.5% of Gross)
    - PAYE (Progressive tax bands with KES 2,400 monthly personal relief)
    """
    nssf = min(2160.0, gross_pay * 0.06)
    shif = max(300.0, round(gross_pay * 0.0275, 2))
    housing_levy = round(gross_pay * 0.015, 2)
    taxable_pay = gross_pay - nssf

    paye = 0.0
    rem = taxable_pay

    if rem > 0:
        band1 = min(rem, 24000)
        paye += band1 * 0.10
        rem -= band1

    if rem > 0:
        band2 = min(rem, 8333)
        paye += band2 * 0.25
        rem -= band2

    if rem > 0:
        band3 = min(rem, 467667)
        paye += band3 * 0.30
        rem -= band3

    if rem > 0:
        band4 = min(rem, 300000)
        paye += band4 * 0.325
        rem -= band4

    if rem > 0:
        paye += rem * 0.35

    personal_relief = 2400.0
    net_paye = max(0.0, round(paye - personal_relief, 2))

    total_deductions = round(nssf + shif + housing_levy + net_paye, 2)
    net_pay = round(gross_pay - total_deductions, 2)

    return {
        "nssf": round(nssf, 2),
        "shif": shif,
        "housing_levy": housing_levy,
        "paye": net_paye,
        "total_deductions": total_deductions,
        "net_pay": net_pay
    }


# -------------------------------------------------------------------
# TIMECARDS & PAYROLL ROUTES
# -------------------------------------------------------------------
@hr_bp.route('/timecards', methods=['GET'])
def get_timecards():
    return jsonify({"success": True, "data": TIMECARDS}), 200


@hr_bp.route('/timecards/<int:tc_id>/status', methods=['PATCH'])
def update_status(tc_id: int):
    data = request.get_json() or {}
    new_status = data.get('status')

    if not new_status:
        return jsonify({"success": False, "error": "Field 'status' is required"}), 400

    card = next((c for c in TIMECARDS if c['id'] == tc_id), None)
    if not card:
        return jsonify({"success": False, "error": "Timecard not found"}), 404

    # 1. Block approval if driver is on leave
    if new_status == 'APPROVED' and card.get('isOnLeave'):
        return jsonify({
            "success": False,
            "error": f"Blocked: {card['driverName']} is currently on approved leave."
        }), 400

    # 2. Block approval if telematics hold / DTC engine fault is flagged
    if new_status == 'APPROVED' and card.get('telematicsHold'):
        return jsonify({
            "success": False,
            "error": f"Blocked: {card['driverName']} has an active vehicle fault ({card.get('dtcCode', 'Unknown DTC')})."
        }), 400

    card['status'] = new_status
    return jsonify({"success": True, "data": card}), 200


@hr_bp.route('/batch-payroll', methods=['POST'])
def batch_payroll():
    data = request.get_json() or {}
    ids = data.get('timecardIds', [])

    if not isinstance(ids, list) or not ids:
        return jsonify({"success": False, "error": "A list of 'timecardIds' is required"}), 400

    processed = []
    detention_rate_per_hour = 450

    for card in TIMECARDS:
        if card['id'] in ids:
            if card['status'] != 'APPROVED' or card.get('isOnLeave'):
                continue

            gross = card['basicPay'] + card['housingAllowance'] + (card['detentionHours'] * detention_rate_per_hour)
            deductions = calculate_statutory_deductions(gross)
            card['status'] = 'PAYROLL_PROCESSED'
            card['grossPay'] = gross
            card['netPay'] = deductions['net_pay']

            processed.append({
                "timecardId": card['id'],
                "driverId": card['driverId'],
                "driverName": card['driverName'],
                "grossPay": gross,
                "netPay": deductions['net_pay'],
                "deductions": deductions
            })

    return jsonify({"success": True, "count": len(processed), "payroll": processed}), 200


# -------------------------------------------------------------------
# MANDATORY PAYSLIP SIGN-OFF & CONSENT ROUTES
# -------------------------------------------------------------------
@hr_bp.route('/drivers/<driver_id>/pending-signatures', methods=['GET'])
def check_pending_signatures(driver_id: str):
    """
    Called when app opens to block access if any published payslip is unsigned.
    """
    driver = DRIVERS.get(driver_id)
    if not driver:
        return jsonify({"success": False, "error": "Driver not found"}), 404

    unsigned = []
    for card in TIMECARDS:
        if card['driverId'] == driver_id and card['status'] == 'PAYROLL_PROCESSED':
            if (driver_id, card['id']) not in SIGNED_PAYSLIPS:
                unsigned.append(card)

    must_sign = len(unsigned) > 0
    return jsonify({
        "success": True,
        "mustSign": must_sign,
        "pendingPayslip": unsigned[0] if must_sign else None
    }), 200


@hr_bp.route('/payslips/<int:timecard_id>/sign', methods=['POST'])
def sign_payslip(timecard_id: int):
    """
    Submits signature, fulfills statutory consent, and unlocks app access.
    """
    data = request.get_json() or {}
    driver_id = data.get('driverId')
    signature = data.get('signature')

    if not signature or not driver_id:
        return jsonify({"success": False, "error": "Signature and driverId are required"}), 400

    SIGNED_PAYSLIPS.add((driver_id, timecard_id))

    return jsonify({
        "success": True,
        "message": f"Payslip #{timecard_id} successfully signed.",
        "signedAt": datetime.datetime.utcnow().isoformat() + "Z"
    }), 200


@hr_bp.route('/drivers/<driver_id>/p9/<int:year>', methods=['GET'])
def generate_p9(driver_id: str, year: int):
    """
    Generates statutory KRA P9 Tax Certificate monthly breakdown.
    """
    driver = DRIVERS.get(driver_id)
    if not driver:
        return jsonify({"success": False, "error": "Driver not found"}), 404

    monthly_gross = driver['basicPay'] + driver['housingAllowance']
    deductions = calculate_statutory_deductions(monthly_gross)

    months = ["January", "February", "March", "April", "May", "June", 
              "July", "August", "September", "October", "November", "December"]
    
    breakdown = []
    for m in months:
        breakdown.append({
            "month": m,
            "basicPay": driver['basicPay'],
            "benefits": driver['housingAllowance'],
            "grossPay": monthly_gross,
            "definedContribution": deductions['nssf'],
            "taxablePay": monthly_gross - deductions['nssf'],
            "personalRelief": 2400.0,
            "payeDeducted": deductions['paye']
        })

    return jsonify({
        "success": True,
        "p9": {
            "employerName": "Logistics Ltd",
            "employeeName": driver['driverName'],
            "employeeKraPin": driver['kraPin'],
            "taxYear": year,
            "monthlyBreakdown": breakdown
        }
    }), 200