# backend/routes/hr.py
from flask import Blueprint, jsonify, request

hr_bp = Blueprint('hr', __name__, url_prefix='/api/v1/hr')

# Mock storage / SQLite DB interface
TIMECARDS = [
    {
        "id": 101,
        "driverId": "DRV-008",
        "driverName": "John Doe",
        "kraPin": "A012345678Z",
        "vehicleReg": "KDA 482P",
        "detentionHours": 8,
        "status": "PENDING_APPROVAL",
        "telematicsHold": False,
        "dtcCode": None,
        "basicPay": 45000,
        "housingAllowance": 12000
    },
    {
        "id": 102,
        "driverId": "DRV-014",
        "driverName": "Peter Kamau",
        "kraPin": "A087654321X",
        "vehicleReg": "KDB 911X",
        "detentionHours": 14,
        "status": "PENDING_APPROVAL",
        "telematicsHold": True,
        "dtcCode": "P0217", # Engine Overheat
        "basicPay": 48000,
        "housingAllowance": 12000
    }
]

def calculate_statutory_deductions(gross_pay):
    nssf = min(2160, gross_pay * 0.06)
    shif = round(gross_pay * 0.0275)
    housing_levy = round(gross_pay * 0.015)
    taxable_pay = gross_pay - nssf

    if taxable_pay <= 24000:
        paye = taxable_pay * 0.10
    elif taxable_pay <= 32333:
        paye = (24000 * 0.10) + ((taxable_pay - 24000) * 0.25)
    elif taxable_pay <= 500000:
        paye = (24000 * 0.10) + ((32333 - 24000) * 0.25) + ((taxable_pay - 32333) * 0.30)
    else:
        paye = (24000 * 0.10) + ((32333 - 24000) * 0.25) + ((500000 - 32333) * 0.30) + ((taxable_pay - 500000) * 0.35)

    paye = max(0, round(paye - 2400)) # Personal relief
    total_deductions = nssf + shif + housing_levy + paye
    
    return {
        "nssf": nssf,
        "shif": shif,
        "housing_levy": housing_levy,
        "paye": paye,
        "total_deductions": total_deductions,
        "net_pay": gross_pay - total_deductions
    }

@hr_bp.route('/timecards', methods=['GET'])
def get_timecards():
    return jsonify({"success": True, "data": TIMECARDS})

@hr_bp.route('/timecards/<int:tc_id>/status', methods=['PATCH'])
def update_status(tc_id):
    data = request.get_json() or {}
    new_status = data.get('status')
    
    for card in TIMECARDS:
        if card['id'] == tc_id:
            if new_status == 'APPROVED' and card['telematicsHold']:
                return jsonify({
                    "success": False, 
                    "error": f"Blocked: {card['driverName']} has an active vehicle fault ({card['dtcCode']})."
                }), 400
            
            card['status'] = new_status
            return jsonify({"success": True, "data": card})

    return jsonify({"success": False, "error": "Timecard not found"}), 404

@hr_bp.route('/batch-payroll', methods=['POST'])
def batch_payroll():
    data = request.get_json() or {}
    ids = data.get('timecardIds', [])
    processed = []
    
    for card in TIMECARDS:
        if card['id'] in ids and card['status'] == 'APPROVED':
            gross = card['basicPay'] + card['housingAllowance'] + (card['detentionHours'] * 450)
            deductions = calculate_statutory_deductions(gross)
            card['status'] = 'PAYROLL_PROCESSED'
            processed.append({
                "driverName": card['driverName'],
                "grossPay": gross,
                "netPay": deductions['net_pay'],
                "deductions": deductions
            })

    return jsonify({
        "success": True,
        "count": len(processed),
        "payroll": processed
    })