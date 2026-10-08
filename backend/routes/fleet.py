import math
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from backend.models.payroll import db
from backend.routes.auth import ADMIN_ROLES, UserAccount
from backend.routes.shipments import TRUCK_TYPES

fleet_bp = Blueprint('fleet', __name__, url_prefix='/api/fleet')
FLEET_MANAGER_ROLES = ADMIN_ROLES
VEHICLE_STATUSES = {'AVAILABLE', 'ASSIGNED', 'MAINTENANCE', 'BREAKDOWN'}
BREAKDOWN_SEVERITIES = {'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'}


class FleetVehicle(db.Model):
    __tablename__ = 'fleet_vehicles'

    id = db.Column(db.Integer, primary_key=True)
    registration = db.Column(db.String(20), unique=True, nullable=False, index=True)
    truck_type = db.Column(db.String(20), nullable=False)
    make = db.Column(db.String(80), nullable=True)
    model = db.Column(db.String(80), nullable=True)
    capacity_tonnes = db.Column(db.Float, nullable=False)
    current_odometer_km = db.Column(db.Float, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default='AVAILABLE')
    assigned_driver_id = db.Column(
        db.Integer, db.ForeignKey('user_accounts.id'), nullable=True, unique=True,
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    assigned_driver = db.relationship('UserAccount', foreign_keys=[assigned_driver_id])
    mileage_records = db.relationship(
        'VehicleMileageRecord', backref='vehicle', lazy=True, cascade='all, delete-orphan',
    )
    spare_changes = db.relationship(
        'VehicleSpareChange', backref='vehicle', lazy=True, cascade='all, delete-orphan',
    )
    breakdowns = db.relationship(
        'VehicleBreakdown', backref='vehicle', lazy=True, cascade='all, delete-orphan',
    )

    def to_dict(self):
        last_mileage = VehicleMileageRecord.query.filter_by(
            vehicle_id=self.id,
        ).order_by(VehicleMileageRecord.recorded_at.desc(), VehicleMileageRecord.id.desc()).first()
        breakdown_count = VehicleBreakdown.query.filter(
            VehicleBreakdown.vehicle_id == self.id,
            VehicleBreakdown.reported_at >= datetime.now(timezone.utc) - timedelta(days=365),
        ).count()
        latest_changes = {}
        for change in VehicleSpareChange.query.filter_by(vehicle_id=self.id).order_by(
            VehicleSpareChange.changed_at_odometer.desc(),
        ).all():
            latest_changes.setdefault(change.spare_part_id, change)

        parts_due = []
        for change in latest_changes.values():
            next_due = change.changed_at_odometer + change.spare_part.service_interval_km
            remaining = next_due - self.current_odometer_km
            parts_due.append({
                'part_number': change.spare_part.part_number,
                'name': change.spare_part.name,
                'last_changed_at_odometer': change.changed_at_odometer,
                'service_interval_km': change.spare_part.service_interval_km,
                'next_due_at_odometer': next_due,
                'remaining_km': remaining,
                'status': 'OVERDUE' if remaining <= 0 else 'DUE_SOON' if remaining <= 1000 else 'OK',
            })
        spare_history = VehicleSpareChange.query.filter_by(vehicle_id=self.id).order_by(
            VehicleSpareChange.changed_at.desc(), VehicleSpareChange.id.desc(),
        ).limit(50).all()
        breakdown_history = VehicleBreakdown.query.filter_by(vehicle_id=self.id).order_by(
            VehicleBreakdown.reported_at.desc(), VehicleBreakdown.id.desc(),
        ).limit(50).all()

        return {
            'id': self.id,
            'registration': self.registration,
            'truck_type': self.truck_type,
            'truck_name': TRUCK_TYPES[self.truck_type]['name'],
            'make': self.make,
            'model': self.model,
            'capacity_tonnes': self.capacity_tonnes,
            'current_odometer_km': self.current_odometer_km,
            'status': self.status,
            'assigned_driver_id': self.assigned_driver_id,
            'assigned_driver_name': (
                self.assigned_driver.display_name or self.assigned_driver.driver_name or self.assigned_driver.email
                if self.assigned_driver else None
            ),
            'last_mileage_recorded_at': last_mileage.recorded_at.isoformat() if last_mileage else None,
            'breakdowns_last_12_months': breakdown_count,
            'parts_due': parts_due,
            'spare_history': [change.to_dict() for change in spare_history],
            'breakdown_history': [breakdown.to_dict() for breakdown in breakdown_history],
        }


class VehicleMileageRecord(db.Model):
    __tablename__ = 'vehicle_mileage_records'

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('fleet_vehicles.id'), nullable=False, index=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False, index=True)
    turnman_name = db.Column(db.String(120), nullable=True)
    odometer_km = db.Column(db.Float, nullable=False)
    distance_since_last_km = db.Column(db.Float, nullable=False, default=0)
    trip_reference = db.Column(db.String(40), nullable=True)
    notes = db.Column(db.String(500), nullable=True)
    recorded_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    driver = db.relationship('UserAccount', foreign_keys=[driver_id])

    def to_dict(self):
        return {
            'id': self.id,
            'vehicle_registration': self.vehicle.registration,
            'driver_id': self.driver_id,
            'driver_name': self.driver.display_name or self.driver.driver_name or self.driver.email,
            'turnman_name': self.turnman_name,
            'odometer_km': self.odometer_km,
            'distance_since_last_km': self.distance_since_last_km,
            'trip_reference': self.trip_reference,
            'notes': self.notes,
            'recorded_at': self.recorded_at.isoformat(),
        }


class SparePart(db.Model):
    __tablename__ = 'fleet_spare_parts'

    id = db.Column(db.Integer, primary_key=True)
    part_number = db.Column(db.String(80), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    service_interval_km = db.Column(db.Integer, nullable=False)
    stock_quantity = db.Column(db.Integer, nullable=False, default=0)
    reorder_level = db.Column(db.Integer, nullable=False, default=0)
    changes = db.relationship(
        'VehicleSpareChange', backref='spare_part', lazy=True, cascade='all, delete-orphan',
    )

    def to_dict(self):
        return {
            'id': self.id,
            'part_number': self.part_number,
            'name': self.name,
            'service_interval_km': self.service_interval_km,
            'stock_quantity': self.stock_quantity,
            'reorder_level': self.reorder_level,
            'stock_status': 'REORDER' if self.stock_quantity <= self.reorder_level else 'IN_STOCK',
        }


class VehicleSpareChange(db.Model):
    __tablename__ = 'vehicle_spare_changes'

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('fleet_vehicles.id'), nullable=False, index=True)
    spare_part_id = db.Column(db.Integer, db.ForeignKey('fleet_spare_parts.id'), nullable=False, index=True)
    changed_at_odometer = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    replaced_by = db.Column(db.String(120), nullable=False)
    notes = db.Column(db.String(500), nullable=True)
    changed_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'part_number': self.spare_part.part_number,
            'part_name': self.spare_part.name,
            'vehicle_registration': self.vehicle.registration,
            'quantity': self.quantity,
            'changed_at_odometer': self.changed_at_odometer,
            'replaced_by': self.replaced_by,
            'notes': self.notes,
            'changed_at': self.changed_at.isoformat(),
        }


class VehicleBreakdown(db.Model):
    __tablename__ = 'fleet_breakdowns'

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('fleet_vehicles.id'), nullable=False, index=True)
    reported_by_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False)
    severity = db.Column(db.String(20), nullable=False)
    location = db.Column(db.String(200), nullable=True)
    description = db.Column(db.String(1000), nullable=False)
    incident_date = db.Column(db.String(10), nullable=True)
    symptoms = db.Column(db.String(1000), nullable=True)
    findings = db.Column(db.String(2000), nullable=True)
    action_taken = db.Column(db.String(2000), nullable=True)
    parts_used = db.Column(db.String(1000), nullable=True)
    odometer_km = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='OPEN')
    reported_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    repairs = db.relationship(
        'VehicleRepair', backref='breakdown', lazy=True, cascade='all, delete-orphan',
    )
    reported_by = db.relationship('UserAccount', foreign_keys=[reported_by_id])

    def to_dict(self):
        return {
            'id': self.id,
            'vehicle_registration': self.vehicle.registration,
            'severity': self.severity,
            'location': self.location,
            'description': self.description,
            'incident_date': self.incident_date,
            'symptoms': self.symptoms,
            'findings': self.findings,
            'action_taken': self.action_taken,
            'parts_used': self.parts_used,
            'odometer_km': self.odometer_km,
            'status': self.status,
            'reported_by': self.reported_by.display_name or self.reported_by.email,
            'reported_at': self.reported_at.isoformat(),
            'repairs': [repair.to_dict() for repair in sorted(self.repairs, key=lambda item: item.created_at)],
        }


class VehicleRepair(db.Model):
    __tablename__ = 'fleet_repairs'

    id = db.Column(db.Integer, primary_key=True)
    breakdown_id = db.Column(db.Integer, db.ForeignKey('fleet_breakdowns.id'), nullable=False, index=True)
    description = db.Column(db.String(1000), nullable=False)
    technician_name = db.Column(db.String(120), nullable=False)
    cost_kes = db.Column(db.Float, nullable=False, default=0)
    odometer_km = db.Column(db.Float, nullable=False)
    completed = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'description': self.description,
            'technician_name': self.technician_name,
            'cost_kes': self.cost_kes,
            'odometer_km': self.odometer_km,
            'completed': self.completed,
            'created_at': self.created_at.isoformat(),
        }


def current_user():
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        return None
    return db.session.get(UserAccount, user_id)


def manager_required():
    user = current_user()
    return user if user and user.account_status == 'active' and user.role in FLEET_MANAGER_ROLES else None


def service_manager_required():
    user = current_user()
    return user if (
        user and user.account_status == 'active'
        and user.role in (FLEET_MANAGER_ROLES | {'mechanic'})
    ) else None


def parse_number(value, label, minimum=0, maximum=100_000_000):
    if isinstance(value, bool):
        raise ValueError(f'{label} must be a number.')
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f'{label} must be a number.') from error
    if not math.isfinite(number) or number < minimum or number > maximum:
        raise ValueError(f'{label} must be between {minimum} and {maximum}.')
    return number


def get_vehicle(registration):
    if not isinstance(registration, str) or not registration.strip():
        return None
    return FleetVehicle.query.filter_by(registration=registration.strip().upper()).first()


def vehicle_access(user, vehicle):
    return user.role in FLEET_MANAGER_ROLES | {'mechanic'} or (
        user.role == 'driver' and vehicle.assigned_driver_id == user.id
    )


@fleet_bp.get('/vehicles')
@jwt_required()
def list_vehicles():
    user = current_user()
    if not user or user.account_status != 'active' or (
        user.role not in FLEET_MANAGER_ROLES | {'mechanic', 'driver'}
    ):
        return jsonify({'status': 'error', 'message': 'Fleet access is not available for this account.'}), 403
    query = FleetVehicle.query
    if user.role == 'driver':
        query = query.filter_by(assigned_driver_id=user.id)
    vehicles = query.order_by(FleetVehicle.registration).all()
    return jsonify({'status': 'success', 'vehicles': [vehicle.to_dict() for vehicle in vehicles]}), 200


@fleet_bp.post('/vehicles')
@jwt_required()
def create_vehicle():
    manager = manager_required()
    if not manager:
        return jsonify({'status': 'error', 'message': 'Fleet manager access is required.'}), 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'status': 'error', 'message': 'A JSON vehicle record is required.'}), 400
    registration = data.get('registration')
    truck_type = data.get('truck_type')
    if not isinstance(registration, str) or not registration.strip() or len(registration.strip()) > 20:
        return jsonify({'status': 'error', 'message': 'Enter a vehicle registration of at most 20 characters.'}), 400
    registration = registration.strip().upper()
    if truck_type not in TRUCK_TYPES:
        return jsonify({'status': 'error', 'message': 'Choose a supported truck type.'}), 400
    if get_vehicle(registration):
        return jsonify({'status': 'error', 'message': 'A truck with this registration already exists.'}), 409

    make = data.get('make', '')
    model = data.get('model', '')
    if not isinstance(make, str) or not isinstance(model, str) or len(make) > 80 or len(model) > 80:
        return jsonify({'status': 'error', 'message': 'Truck make and model must be at most 80 characters.'}), 400
    try:
        odometer = parse_number(data.get('current_odometer_km', 0), 'Odometer')
    except ValueError as error:
        return jsonify({'status': 'error', 'message': str(error)}), 400

    driver_id = data.get('assigned_driver_id')
    driver = None
    if driver_id not in (None, ''):
        try:
            if isinstance(driver_id, bool):
                raise ValueError
            driver = db.session.get(UserAccount, int(driver_id))
        except (TypeError, ValueError):
            driver = None
        if (
            not driver or driver.role != 'driver' or driver.account_status != 'active'
            or driver.employment_status != 'ACTIVE'
        ):
            return jsonify({'status': 'error', 'message': 'Choose an active and available driver.'}), 400
        if FleetVehicle.query.filter_by(assigned_driver_id=driver.id).first():
            return jsonify({'status': 'error', 'message': 'This driver is already assigned to another truck.'}), 409

    vehicle = FleetVehicle(
        registration=registration,
        truck_type=truck_type,
        make=make.strip() or None,
        model=model.strip() or None,
        capacity_tonnes=TRUCK_TYPES[truck_type]['capacity'],
        current_odometer_km=odometer,
        status='ASSIGNED' if driver else 'AVAILABLE',
        assigned_driver_id=driver.id if driver else None,
    )
    db.session.add(vehicle)
    db.session.commit()
    return jsonify({'status': 'success', 'vehicle': vehicle.to_dict()}), 201


@fleet_bp.post('/vehicles/<registration>/mileage')
@jwt_required()
def record_mileage(registration):
    user = current_user()
    vehicle = get_vehicle(registration)
    if not user or not vehicle or not vehicle_access(user, vehicle):
        return jsonify({'status': 'error', 'message': 'Truck was not found or is not assigned to this driver.'}), 404
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'status': 'error', 'message': 'A JSON mileage record is required.'}), 400

    driver_id = user.id if user.role == 'driver' else data.get('driver_id')
    driver = db.session.get(UserAccount, driver_id) if isinstance(driver_id, int) and not isinstance(driver_id, bool) else None
    if not driver or driver.role != 'driver' or driver.account_status != 'active':
        return jsonify({'status': 'error', 'message': 'Select an active driver to record the mileage.'}), 400
    try:
        odometer = parse_number(data.get('odometer_km'), 'Odometer')
    except ValueError as error:
        return jsonify({'status': 'error', 'message': str(error)}), 400
    if odometer < vehicle.current_odometer_km:
        return jsonify({'status': 'error', 'message': 'Odometer readings cannot be lower than the last recorded reading.'}), 409

    turnman = data.get('turnman_name', '')
    trip_reference = data.get('trip_reference', '')
    notes = data.get('notes', '')
    if not all(isinstance(value, str) for value in (turnman, trip_reference, notes)):
        return jsonify({'status': 'error', 'message': 'Turnman, trip reference, and notes must be text.'}), 400
    if len(turnman) > 120 or len(trip_reference) > 40 or len(notes) > 500:
        return jsonify({'status': 'error', 'message': 'One or more mileage details exceed the supported length.'}), 400

    record = VehicleMileageRecord(
        vehicle_id=vehicle.id,
        driver_id=driver.id,
        turnman_name=turnman.strip() or None,
        odometer_km=odometer,
        distance_since_last_km=odometer - vehicle.current_odometer_km,
        trip_reference=trip_reference.strip() or None,
        notes=notes.strip() or None,
    )
    vehicle.current_odometer_km = odometer
    db.session.add(record)
    db.session.commit()
    return jsonify({'status': 'success', 'record': record.to_dict(), 'vehicle': vehicle.to_dict()}), 201


@fleet_bp.get('/vehicles/<registration>/mileage')
@jwt_required()
def list_mileage(registration):
    user = current_user()
    vehicle = get_vehicle(registration)
    if not user or not vehicle or not vehicle_access(user, vehicle):
        return jsonify({'status': 'error', 'message': 'Truck was not found or is not assigned to this driver.'}), 404
    records = VehicleMileageRecord.query.filter_by(vehicle_id=vehicle.id).order_by(
        VehicleMileageRecord.recorded_at.desc(), VehicleMileageRecord.id.desc(),
    ).limit(100).all()
    return jsonify({'status': 'success', 'records': [record.to_dict() for record in records]}), 200


@fleet_bp.route('/spares', methods=['GET', 'POST'])
@jwt_required()
def manage_spares():
    manager = service_manager_required()
    if not manager:
        return jsonify({'status': 'error', 'message': 'Fleet manager or mechanic access is required.'}), 403

    if request.method == 'GET':
        parts = SparePart.query.order_by(SparePart.name, SparePart.part_number).all()
        return jsonify({'status': 'success', 'spares': [part.to_dict() for part in parts]}), 200

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'status': 'error', 'message': 'A JSON spare inventory record is required.'}), 400
    part_number = data.get('part_number')
    name = data.get('name')
    if not isinstance(part_number, str) or not part_number.strip() or len(part_number.strip()) > 80:
        return jsonify({'status': 'error', 'message': 'Enter a part number of at most 80 characters.'}), 400
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
        return jsonify({'status': 'error', 'message': 'Enter a spare-part name of at most 120 characters.'}), 400
    try:
        interval = int(data.get('service_interval_km'))
        stock_quantity = int(data.get('stock_quantity', 0))
        reorder_level = int(data.get('reorder_level', 0))
        if any(isinstance(data.get(field), bool) for field in (
            'service_interval_km', 'stock_quantity', 'reorder_level',
        )):
            raise ValueError
        if not 1 <= interval <= 2_000_000 or not 0 <= stock_quantity <= 1_000_000 or not 0 <= reorder_level <= 1_000_000:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Enter a valid service interval, stock quantity, and reorder level.'}), 400

    part = SparePart.query.filter_by(part_number=part_number.strip().upper()).first()
    if part:
        return jsonify({'status': 'error', 'message': 'That part number already exists. Use the restock action to add stock.'}), 409
    part = SparePart(
        part_number=part_number.strip().upper(),
        name=name.strip(),
        service_interval_km=interval,
        stock_quantity=stock_quantity,
        reorder_level=reorder_level,
    )
    db.session.add(part)
    db.session.commit()
    return jsonify({'status': 'success', 'spare': part.to_dict()}), 201


@fleet_bp.post('/spares/<int:part_id>/restock')
@jwt_required()
def restock_spare(part_id):
    manager = service_manager_required()
    if not manager:
        return jsonify({'status': 'error', 'message': 'Fleet manager or mechanic access is required.'}), 403
    part = db.session.get(SparePart, part_id)
    if not part:
        return jsonify({'status': 'error', 'message': 'Spare part was not found.'}), 404
    data = request.get_json(silent=True)
    quantity = data.get('quantity') if isinstance(data, dict) else None
    if isinstance(quantity, bool):
        return jsonify({'status': 'error', 'message': 'Enter a positive restock quantity.'}), 400
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        quantity = 0
    if quantity < 1 or quantity > 1_000_000:
        return jsonify({'status': 'error', 'message': 'Enter a positive restock quantity within the stock limit.'}), 400
    updated = db.session.query(SparePart).filter(
        SparePart.id == part.id,
        SparePart.stock_quantity <= 1_000_000 - quantity,
    ).update(
        {SparePart.stock_quantity: SparePart.stock_quantity + quantity},
        synchronize_session=False,
    )
    if not updated:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': 'Restocking would exceed the stock limit.'}), 400
    db.session.commit()
    db.session.refresh(part)
    return jsonify({'status': 'success', 'spare': part.to_dict()}), 200


@fleet_bp.post('/vehicles/<registration>/spare-changes')
@jwt_required()
def record_spare_change(registration):
    manager = service_manager_required()
    if not manager:
        return jsonify({'status': 'error', 'message': 'Fleet manager or mechanic access is required.'}), 403
    vehicle = get_vehicle(registration)
    if not vehicle:
        return jsonify({'status': 'error', 'message': 'Truck was not found.'}), 404
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'status': 'error', 'message': 'A JSON spare-part change record is required.'}), 400

    replaced_by = data.get('replaced_by')
    if not isinstance(replaced_by, str) or not replaced_by.strip() or len(replaced_by) > 120:
        return jsonify({'status': 'error', 'message': 'Enter the technician or staff member who replaced the part.'}), 400
    try:
        changed_at = parse_number(data.get('changed_at_odometer'), 'Replacement odometer')
        quantity = int(data.get('quantity', 1))
        if isinstance(data.get('quantity', 1), bool) or quantity < 1 or quantity > 100:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Enter a valid replacement odometer and quantity.'}), 400
    if changed_at > vehicle.current_odometer_km:
        return jsonify({'status': 'error', 'message': 'Replacement odometer cannot exceed the truck’s current odometer.'}), 400

    part_id = data.get('spare_part_id')
    if isinstance(part_id, bool):
        part_id = None
    try:
        part = db.session.get(SparePart, int(part_id)) if part_id is not None else None
    except (TypeError, ValueError):
        part = None
    if part_id is not None and not part:
        return jsonify({'status': 'error', 'message': 'Select a valid spare part from inventory.'}), 400

    if not part:
        part_number = data.get('part_number')
        name = data.get('name')
        if not all(isinstance(value, str) and value.strip() for value in (part_number, name)):
            return jsonify({'status': 'error', 'message': 'Select a spare part from inventory.'}), 400
        try:
            interval = int(data.get('service_interval_km'))
            if isinstance(data.get('service_interval_km'), bool) or not 1 <= interval <= 2_000_000:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({'status': 'error', 'message': 'Enter a valid spare-part service interval.'}), 400
        part = SparePart.query.filter_by(part_number=part_number.strip().upper()).first()
    if not part:
        return jsonify({'status': 'error', 'message': 'Create the spare part in inventory before recording a replacement.'}), 400
    if part_id is None and part.service_interval_km != interval:
        return jsonify({
            'status': 'error',
            'message': f'This part is already configured for replacement every {part.service_interval_km} km.',
        }), 409
    if part.stock_quantity < quantity:
        return jsonify({'status': 'error', 'message': f'Only {part.stock_quantity} unit(s) of {part.name} are in stock.'}), 409
    notes = data.get('notes', '')
    if not isinstance(notes, str) or len(notes) > 500:
        return jsonify({'status': 'error', 'message': 'Part usage notes must be at most 500 characters.'}), 400
    change = VehicleSpareChange(
        vehicle_id=vehicle.id,
        spare_part_id=part.id,
        changed_at_odometer=changed_at,
        quantity=quantity,
        replaced_by=replaced_by.strip(),
        notes=notes.strip() or None,
    )
    stock_updated = db.session.query(SparePart).filter(
        SparePart.id == part.id,
        SparePart.stock_quantity >= quantity,
    ).update(
        {SparePart.stock_quantity: SparePart.stock_quantity - quantity},
        synchronize_session=False,
    )
    if not stock_updated:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': 'There is not enough stock left to record this part usage.'}), 409
    db.session.add(change)
    db.session.commit()
    return jsonify({
        'status': 'success',
        'message': f'{part.name} replacement recorded for {vehicle.registration}.',
        'vehicle': vehicle.to_dict(),
    }), 201


@fleet_bp.post('/vehicles/<registration>/breakdowns')
@jwt_required()
def report_breakdown(registration):
    user = current_user()
    vehicle = get_vehicle(registration)
    if not user or not vehicle or not vehicle_access(user, vehicle):
        return jsonify({'status': 'error', 'message': 'Truck was not found or is not assigned to this driver.'}), 404
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'status': 'error', 'message': 'A JSON breakdown report is required.'}), 400
    severity = data.get('severity')
    location = data.get('location', '')
    text_fields = {
        'symptoms': (data.get('symptoms', ''), 1000),
        'findings': (data.get('findings', ''), 2000),
        'action_taken': (data.get('action_taken', ''), 2000),
        'parts_used': (data.get('parts_used', ''), 1000),
    }
    description = data.get('description', '')
    if severity not in BREAKDOWN_SEVERITIES:
        return jsonify({'status': 'error', 'message': 'Choose a severity for the incident.'}), 400
    if not isinstance(location, str) or len(location) > 200:
        return jsonify({'status': 'error', 'message': 'Breakdown details exceed the supported length.'}), 400
    if not isinstance(description, str) or len(description) > 1000:
        return jsonify({'status': 'error', 'message': 'Incident summary must be at most 1,000 characters.'}), 400
    if any(not isinstance(value, str) or len(value) > maximum for value, maximum in text_fields.values()):
        return jsonify({'status': 'error', 'message': 'Incident details exceed the supported length.'}), 400
    description = description.strip() or text_fields['symptoms'][0].strip()
    if not description:
        return jsonify({'status': 'error', 'message': 'Describe the incident or vehicle symptoms.'}), 400
    incident_date = data.get('incident_date')
    if incident_date is not None:
        if not isinstance(incident_date, str):
            return jsonify({'status': 'error', 'message': 'Enter a valid incident date.'}), 400
        try:
            incident_date = datetime.strptime(incident_date, '%Y-%m-%d').date().isoformat()
        except ValueError:
            return jsonify({'status': 'error', 'message': 'Enter a valid incident date.'}), 400
    else:
        incident_date = datetime.now(timezone.utc).date().isoformat()
    try:
        odometer = parse_number(data.get('odometer_km', vehicle.current_odometer_km), 'Incident odometer')
    except ValueError as error:
        return jsonify({'status': 'error', 'message': str(error)}), 400

    breakdown = VehicleBreakdown(
        vehicle_id=vehicle.id,
        reported_by_id=user.id,
        severity=severity,
        location=location.strip() or None,
        description=description,
        incident_date=incident_date,
        symptoms=text_fields['symptoms'][0].strip() or None,
        findings=text_fields['findings'][0].strip() or None,
        action_taken=text_fields['action_taken'][0].strip() or None,
        parts_used=text_fields['parts_used'][0].strip() or None,
        odometer_km=odometer,
    )
    vehicle.status = 'BREAKDOWN'
    db.session.add(breakdown)
    db.session.commit()
    return jsonify({
        'status': 'success',
        'message': 'Breakdown reported. The truck has been marked unavailable for dispatch.',
        'breakdown': breakdown.to_dict(),
    }), 201


@fleet_bp.get('/breakdowns')
@jwt_required()
def list_breakdowns():
    user = current_user()
    if not user or user.account_status != 'active' or (
        user.role not in FLEET_MANAGER_ROLES | {'mechanic', 'driver'}
    ):
        return jsonify({'status': 'error', 'message': 'Fleet access is not available for this account.'}), 403
    query = VehicleBreakdown.query.join(FleetVehicle)
    if user.role == 'driver':
        query = query.filter(FleetVehicle.assigned_driver_id == user.id)
    breakdowns = query.order_by(VehicleBreakdown.reported_at.desc()).limit(200).all()
    return jsonify({'status': 'success', 'breakdowns': [breakdown.to_dict() for breakdown in breakdowns]}), 200


@fleet_bp.post('/breakdowns/<int:breakdown_id>/repairs')
@jwt_required()
def record_repair(breakdown_id):
    manager = service_manager_required()
    if not manager:
        return jsonify({'status': 'error', 'message': 'Fleet manager or mechanic access is required.'}), 403
    breakdown = db.session.get(VehicleBreakdown, breakdown_id)
    if not breakdown:
        return jsonify({'status': 'error', 'message': 'Breakdown record was not found.'}), 404
    if breakdown.status == 'RESOLVED':
        return jsonify({'status': 'error', 'message': 'This breakdown is already resolved.'}), 409

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'status': 'error', 'message': 'A JSON repair record is required.'}), 400
    description = data.get('description')
    technician = data.get('technician_name')
    completed = data.get('completed', False)
    if not isinstance(description, str) or not description.strip() or not isinstance(technician, str) or not technician.strip():
        return jsonify({'status': 'error', 'message': 'Repair work and technician name are required.'}), 400
    if len(description) > 1000 or len(technician) > 120 or not isinstance(completed, bool):
        return jsonify({'status': 'error', 'message': 'Repair details are invalid or exceed the supported length.'}), 400
    try:
        cost = parse_number(data.get('cost_kes', 0), 'Repair cost')
    except ValueError as error:
        return jsonify({'status': 'error', 'message': str(error)}), 400

    repair = VehicleRepair(
        breakdown_id=breakdown.id,
        description=description.strip(),
        technician_name=technician.strip(),
        cost_kes=cost,
        odometer_km=breakdown.vehicle.current_odometer_km,
        completed=completed,
    )
    db.session.add(repair)
    if completed:
        breakdown.status = 'RESOLVED'
        if not VehicleBreakdown.query.filter(
            VehicleBreakdown.vehicle_id == breakdown.vehicle_id,
            VehicleBreakdown.status == 'OPEN',
            VehicleBreakdown.id != breakdown.id,
        ).first():
            breakdown.vehicle.status = (
                'ASSIGNED' if breakdown.vehicle.assigned_driver_id else 'AVAILABLE'
            )
    db.session.commit()
    return jsonify({
        'status': 'success',
        'message': 'Repair log saved.' if not completed else 'Repair completed and truck returned to service.',
        'repair': repair.to_dict(),
        'breakdown': breakdown.to_dict(),
    }), 201
