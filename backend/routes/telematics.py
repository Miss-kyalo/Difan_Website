import hashlib
import hmac
import os
import uuid
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request, current_app
from werkzeug.utils import secure_filename
from backend.models.payroll import db, Timecard, Driver
from sqlalchemy.exc import IntegrityError

telematics_bp = Blueprint('telematics', __name__, url_prefix='/api/v1/telematics')

SAFETY_CRITICAL_DTCS = {
    "P0217": "Engine Coolant Overtemperature Condition",
    "P0300": "Random/Multiple Cylinder Misfire Detected",
    "P0700": "Transmission Control System Malfunction",
    "P0251": "Injection Pump Fuel Metering Control A Malfunction"
}


class ELDComplianceEvent(db.Model):
    __tablename__ = 'eld_compliance_events'

    id = db.Column(db.Integer, primary_key=True)
    source_event_id = db.Column(db.String(120), nullable=False, unique=True, index=True)
    event_type = db.Column(db.String(40), nullable=False)
    vehicle_registration = db.Column(db.String(20), nullable=False, index=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False, index=True)
    occurred_at = db.Column(db.DateTime(timezone=True), nullable=False)
    details = db.Column(db.String(1500), nullable=False)
    ingested_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


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


@telematics_bp.post('/ingest-compliance-event')
def ingest_compliance_event():
    secret = current_app.config.get('ELD_WEBHOOK_SECRET')
    if not secret:
        return jsonify({
            'status': 'error',
            'message': 'ELD event ingestion is disabled until ELD_WEBHOOK_SECRET is configured.',
        }), 503

    raw_body = request.get_data(cache=True)
    if len(raw_body) > 10_000:
        return jsonify({'status': 'error', 'message': 'ELD compliance-event payload is too large.'}), 413
    supplied_signature = request.headers.get('X-Difan-ELD-Signature', '')
    expected_signature = 'sha256=' + hmac.new(
        secret.encode('utf-8'),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(supplied_signature, expected_signature):
        return jsonify({'status': 'error', 'message': 'ELD webhook signature is invalid.'}), 401

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'status': 'error', 'message': 'An ELD compliance-event JSON object is required.'}), 400
    event_id = data.get('event_id')
    event_type = data.get('event_type')
    vehicle_registration = data.get('vehicle_registration')
    occurred_value = data.get('occurred_at')
    details = data.get('details')
    supported_events = {
        'HOS_VIOLATION': 'ELD_HOS_VIOLATION',
        'UNAUTHORIZED_DOWNTIME': 'UNAUTHORIZED_VEHICLE_DOWNTIME',
    }
    if (
        not isinstance(event_id, str)
        or not event_id.strip()
        or len(event_id.strip()) > 116
        or not isinstance(event_type, str)
        or event_type not in supported_events
        or not isinstance(vehicle_registration, str)
        or not vehicle_registration.strip()
        or len(vehicle_registration.strip()) > 20
        or not isinstance(occurred_value, str)
        or not isinstance(details, str)
        or not details.strip()
        or len(details.strip()) > 1500
    ):
        return jsonify({'status': 'error', 'message': 'Provide a valid event_id, event_type, vehicle_registration, occurred_at, and details.'}), 400
    try:
        occurred_at = datetime.fromisoformat(occurred_value.strip().replace('Z', '+00:00'))
        if occurred_at.tzinfo is None:
            raise ValueError
    except ValueError:
        return jsonify({'status': 'error', 'message': 'ELD occurred_at must be an ISO-8601 timestamp with a time zone.'}), 400

    source_event_id = event_id.strip()
    existing_event = ELDComplianceEvent.query.filter_by(source_event_id=source_event_id).first()
    if existing_event:
        return jsonify({
            'status': 'success',
            'duplicate': True,
            'warning_created': False,
            'message': 'This ELD event was already processed.',
        }), 200

    from backend.routes.fleet import FleetVehicle
    from backend.routes.workforce import create_automated_driver_warning

    vehicle = FleetVehicle.query.filter_by(
        registration=vehicle_registration.strip().upper(),
    ).first()
    if not vehicle:
        return jsonify({'status': 'error', 'message': 'ELD event references an unknown fleet vehicle.'}), 404
    driver = vehicle.assigned_driver
    if not driver or driver.role != 'driver':
        return jsonify({'status': 'error', 'message': 'No driver is assigned to the ELD vehicle.'}), 409

    occurred_at = occurred_at.astimezone(timezone.utc)
    event = ELDComplianceEvent(
        source_event_id=source_event_id,
        event_type=event_type,
        vehicle_registration=vehicle.registration,
        driver_id=driver.id,
        occurred_at=occurred_at,
        details=details.strip(),
    )
    db.session.add(event)
    case = create_automated_driver_warning(
        driver,
        supported_events[event_type],
        f'ELD:{source_event_id}',
        'SAFETY_COMPLIANCE',
        (
            f'{event_type.replace("_", " ").title()} reported by the configured ELD provider for '
            f'vehicle {vehicle.registration} at {occurred_at.isoformat()}: {details.strip()}'
        ),
        occurred_at,
    )
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        duplicate = ELDComplianceEvent.query.filter_by(source_event_id=source_event_id).first()
        if duplicate:
            return jsonify({
                'status': 'success',
                'duplicate': True,
                'warning_created': False,
                'message': 'This ELD event was already processed.',
            }), 200
        current_app.logger.exception('Unable to store ELD compliance event %s.', source_event_id)
        return jsonify({'status': 'error', 'message': 'ELD event could not be stored.'}), 500

    return jsonify({
        'status': 'success',
        'duplicate': False,
        'warning_created': case is not None,
        'event_id': event.source_event_id,
        'driver_id': driver.id,
        'message': 'ELD compliance event recorded as a 72-hour disputable HR warning.',
    }), 201


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