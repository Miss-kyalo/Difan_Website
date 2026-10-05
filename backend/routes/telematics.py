import os
import uuid
from datetime import datetime
from flask import Blueprint, jsonify, request, current_app
from werkzeug.utils import secure_filename
from backend.models.payroll import db, Timecard, Driver

telematics_bp = Blueprint('telematics', __name__, url_prefix='/api/v1/telematics')

SAFETY_CRITICAL_DTCS = {
    "P0217": "Engine Coolant Overtemperature Condition",
    "P0300": "Random/Multiple Cylinder Misfire Detected",
    "P0700": "Transmission Control System Malfunction",
    "P0251": "Injection Pump Fuel Metering Control A Malfunction"
}

@telematics_bp.route('/ingest-dtc', methods=['POST'])
def ingest_dtc():
    data = request.get_json() or {}
    vehicle_reg = data.get('vehicleReg')
    dtc_code = data.get('dtcCode')

    if not vehicle_reg or not dtc_code:
        return jsonify({"success": False, "error": "Missing vehicleReg or dtcCode"}), 400

    driver = Driver.query.filter_by(assigned_vehicle_reg=vehicle_reg, is_active=True).first()
    if not driver:
        return jsonify({"success": False, "error": f"No active driver assigned to vehicle {vehicle_reg}"}), 404

    timecard = Timecard.query.filter_by(driver_id=driver.id, status='PENDING_APPROVAL').first()
    if not timecard:
        return jsonify({"success": False, "error": "No open timecard found for driver"}), 404

    if dtc_code in SAFETY_CRITICAL_DTCS:
        if not timecard.telematics_hold or timecard.active_dtc_code != dtc_code:
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
        
        if departure < arrival:
            return jsonify({"success": False, "error": "Departure timestamp cannot precede arrival timestamp"}), 400

        duration_seconds = (departure - arrival).total_seconds()
        total_hours = round(duration_seconds / 3600.0, 2)
        detention_hours = max(0.0, round(total_hours - 2.0, 2))

        timecard = Timecard.query.filter_by(driver_id=driver_id, status='PENDING_APPROVAL').first()
        if timecard:
            current_detention = timecard.detention_hours or 0.0
            timecard.detention_hours = current_detention + detention_hours
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
    timecard = db.session.get(Timecard, timecard_id)
    if not timecard:
        return jsonify({"success": False, "error": "Timecard not found"}), 404

    timecard.telematics_hold = False
    timecard.active_dtc_code = None
    db.session.commit()

    return jsonify({"success": True, "message": "Telematics fault hold cleared successfully."})


@telematics_bp.route('/log-incident', methods=['POST'])
def log_incident():
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

    receipt_filename = None
    if part_source == 'Purchased' and receipt_file:
        upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'receipts')
        os.makedirs(upload_folder, exist_ok=True)
        
        safe_name = secure_filename(receipt_file.filename or 'receipt.pdf')
        receipt_filename = f"{uuid.uuid4().hex}_{safe_name}"
        receipt_path = os.path.join(upload_folder, receipt_filename)
        receipt_file.save(receipt_path)

    return jsonify({
        "success": True,
        "message": f"Incident report and parts log for truck {vehicle_reg} saved successfully.",
        "receiptPath": receipt_filename
    })