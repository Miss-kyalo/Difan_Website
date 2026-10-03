from datetime import datetime
import os
from flask import Blueprint, jsonify, request, current_app
from backend.models.payroll import db, Timecard, Driver

telematics_bp = Blueprint('telematics', __name__, url_prefix='/api/v1/telematics')

# Severe OBD-II DTC codes that trigger an automatic HR/Payroll hold
SAFETY_CRITICAL_DTCS = {
    "P0217": "Engine Coolant Overtemperature Condition",
    "P0300": "Random/Multiple Cylinder Misfire Detected",
    "P0700": "Transmission Control System Malfunction",
    "P0251": "Injection Pump Fuel Metering Control A Malfunction"
}

@telematics_bp.route('/ingest-dtc', methods=['POST'])
def ingest_dtc():
    """
    Ingests OBD-II telemetry from vehicle hardware. If a safety-critical 
    fault is detected, it locks the associated driver's timecard.
    """
    data = request.get_json() or {}
    vehicle_reg = data.get('vehicleReg')
    dtc_code = data.get('dtcCode')

    if not vehicle_reg or not dtc_code:
        return jsonify({"success": False, "error": "Missing vehicleReg or dtcCode"}), 400

    driver = Driver.query.filter_by(assigned_vehicle_reg=vehicle_reg, is_active=True).first()
    if not driver:
        return jsonify({"success": False, "error": f"No active driver assigned to vehicle {vehicle_reg}"}), 404

    # Fetch active or latest timecard for driver
    timecard = Timecard.query.filter_by(driver_id=driver.id, status='PENDING_APPROVAL').first()
    if not timecard:
        return jsonify({"success": False, "error": "No open timecard found for driver"}), 404

    # Check for safety critical fault
    if dtc_code in SAFETY_CRITICAL_DTCS:
        timecard.telematics_hold = True
        timecard.active_dtc_code = dtc_code
        db.session.commit()
        
        return jsonify({
            "success": True,
            "safetyHoldApplied": True,
            "message": f"Critical fault {dtc_code} ({SAFETY_CRITICAL_DTCS[dtc_code]}) applied to driver {driver.full_name}."
        })

    return jsonify({"success": True, "safetyHoldApplied": False, "message": "Telemetry logged normal operating parameters."})


@telematics_bp.route('/geofence-detention', methods=['POST'])
def calculate_geofence_detention():
    """
    Calculates detention hours based on warehouse/terminal arrival and departure timestamps.
    """
    data = request.get_json() or {}
    driver_id = data.get('driverId')
    arrival_iso = data.get('arrivalTimestamp')
    departure_iso = data.get('departureTimestamp')

    if not all([driver_id, arrival_iso, departure_iso]):
        return jsonify({"success": False, "error": "Missing driverId, arrivalTimestamp, or departureTimestamp"}), 400

    if not isinstance(arrival_iso, str) or not isinstance(departure_iso, str):
        return jsonify({"success": False, "error": "Invalid timestamp format"}), 400

    try:
        arrival = datetime.fromisoformat(arrival_iso)
        departure = datetime.fromisoformat(departure_iso)
        
        # Calculate total hours spent at destination
        duration_seconds = (departure - arrival).total_seconds()
        total_hours = round(max(0.0, duration_seconds / 3600.0), 2)
        
        # Standard free waiting time is 2 hours; excess is detention
        detention_hours = max(0.0, total_hours - 2.0)

        timecard = Timecard.query.filter_by(driver_id=driver_id, status='PENDING_APPROVAL').first()
        if timecard:
            timecard.detention_hours += detention_hours
            db.session.commit()

        return jsonify({
            "success": True,
            "totalHoursAtFacility": total_hours,
            "billableDetentionHours": detention_hours,
            "updatedTotalDetentionHours": timecard.detention_hours if timecard else detention_hours
        })
    except ValueError:
        return jsonify({"success": False, "error": "Invalid ISO timestamp format"}), 400


@telematics_bp.route('/clear-fault/<int:timecard_id>', methods=['POST'])
def clear_fault(timecard_id):
    """
    Allows fleet managers to override/clear a telematics hold after vehicle maintenance.
    """
    timecard = Timecard.query.get(timecard_id)
    if not timecard:
        return jsonify({"success": False, "error": "Timecard not found"}), 404

    timecard.telematics_hold = False
    timecard.active_dtc_code = None
    db.session.commit()

    return jsonify({"success": True, "message": "Telematics fault hold cleared successfully."})


@telematics_bp.route('/log-incident', methods=['POST'])
def log_incident():
    """
    Logs a roadside or yard incident report tied to a specific truck, capturing 
    replaced parts, source (yard stock vs purchased), notes, and storing uploaded purchase receipts.
    """
    vehicle_reg = request.form.get('truck')
    incident_type = request.form.get('type')
    severity = request.form.get('severity')
    mechanic = request.form.get('mechanic')
    replaced_part = request.form.get('replacedPart')
    part_source = request.form.get('partSource')
    notes = request.form.get('notes')
    receipt_file = request.files.get('receipt')

    if not all([vehicle_reg, incident_type, severity, notes]):
        return jsonify({"success": False, "error": "Missing required incident fields"}), 400

    receipt_filename = ""
    if part_source == 'Purchased' and receipt_file:
        upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'receipts')
        os.makedirs(upload_folder, exist_ok=True)
        receipt_filename = str(receipt_file.filename or 'receipt.pdf')
        receipt_path = os.path.join(upload_folder, receipt_filename)
        receipt_file.save(receipt_path)

    print(f"[INCIDENT LOG] Truck: {vehicle_reg} | Type: {incident_type} | Severity: {severity} | Parts: {replaced_part} | Source: {part_source} | Receipt: {receipt_filename}")

    return jsonify({
        "success": True,
        "message": f"Incident report and parts log for truck {vehicle_reg} saved successfully."
    })