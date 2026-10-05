import calendar
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from backend.models.payroll import db
from backend.routes.auth import UserAccount

portal_bp = Blueprint('portal', __name__, url_prefix='/api/portal')
CONTAINER_SIZES = {'20ft', '40ft'}
EMPLOYEE_ROLES = {'admin', 'driver', 'mechanic'}


class ContainerQuoteRate(db.Model):
    __tablename__ = 'container_quote_rates'

    container_size = db.Column(db.String(12), primary_key=True)
    rate_kes = db.Column(db.Float, nullable=False)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {'size': self.container_size, 'rate_kes': self.rate_kes}


class PayrollSlip(db.Model):
    __tablename__ = 'payroll_slips'
    __table_args__ = (
        db.UniqueConstraint('employee_id', 'pay_period', name='uq_payroll_slip_employee_period'),
    )

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False, index=True)
    pay_period = db.Column(db.String(20), nullable=False)
    basic_pay = db.Column(db.Float, nullable=False)
    allowances = db.Column(db.Float, nullable=False, default=0)
    bonus = db.Column(db.Float, nullable=False, default=0)
    deductions = db.Column(db.Float, nullable=False, default=0)
    gross_pay = db.Column(db.Float, nullable=False)
    net_pay = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(24), nullable=False, default='PENDING_APPROVAL')
    created_by_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=True)
    approved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    receipt_signed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    paystub_signed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    employee = db.relationship('UserAccount', foreign_keys=[employee_id])

    def to_dict(self):
        employee_name = self.employee.display_name or self.employee.driver_name or self.employee.email
        return {
            'id': self.id,
            'employee_id': self.employee_id,
            'employee_name': employee_name,
            'employee_email': self.employee.email,
            'pay_period': self.pay_period,
            'basic_pay': self.basic_pay,
            'allowances': self.allowances,
            'bonus': self.bonus,
            'deductions': self.deductions,
            'gross_pay': self.gross_pay,
            'net_pay': self.net_pay,
            'status': self.status,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'receipt_signed_at': self.receipt_signed_at.isoformat() if self.receipt_signed_at else None,
            'paystub_signed_at': self.paystub_signed_at.isoformat() if self.paystub_signed_at else None,
        }


class MechanicIncidentReport(db.Model):
    __tablename__ = 'mechanic_incident_reports'

    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(36), unique=True, nullable=False, index=True)
    mechanic_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False, index=True)
    vehicle_registration = db.Column(db.String(24), nullable=False)
    incident_date = db.Column(db.String(32), nullable=False)
    location = db.Column(db.String(180), nullable=False)
    severity = db.Column(db.String(24), nullable=False)
    symptoms = db.Column(db.String(1000), nullable=False)
    findings = db.Column(db.String(2000), nullable=False)
    action_taken = db.Column(db.String(2000), nullable=False)
    parts_used = db.Column(db.String(1000), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    mechanic = db.relationship('UserAccount', foreign_keys=[mechanic_id])

    def to_dict(self):
        return {
            'id': self.id,
            'reference': self.reference,
            'mechanic_name': self.mechanic.display_name or self.mechanic.email,
            'vehicle_registration': self.vehicle_registration,
            'incident_date': self.incident_date,
            'location': self.location,
            'severity': self.severity,
            'symptoms': self.symptoms,
            'findings': self.findings,
            'action_taken': self.action_taken,
            'parts_used': self.parts_used,
            'created_at': self.created_at.isoformat(),
        }


def current_user():
    try:
        return db.session.get(UserAccount, int(get_jwt_identity()))
    except (TypeError, ValueError):
        return None


def employee_payroll_status(user):
    if not user or user.role not in EMPLOYEE_ROLES:
        return {'must_sign': False, 'pending': []}
    now = datetime.now(timezone.utc)
    is_month_end = now.day == calendar.monthrange(now.year, now.month)[1]
    if not is_month_end:
        return {'must_sign': False, 'pending': []}
    pending = PayrollSlip.query.filter(
        PayrollSlip.employee_id == user.id,
        PayrollSlip.status == 'APPROVED',
        db.or_(
            PayrollSlip.receipt_signed_at.is_(None),
            PayrollSlip.paystub_signed_at.is_(None),
        ),
    ).order_by(PayrollSlip.pay_period).all()
    return {'must_sign': bool(pending), 'pending': pending}


@portal_bp.get('/container-rates')
@jwt_required()
def get_container_rates():
    rates = ContainerQuoteRate.query.order_by(ContainerQuoteRate.container_size).all()
    return jsonify({'status': 'success', 'rates': [rate.to_dict() for rate in rates]}), 200


@portal_bp.put('/container-rates/<container_size>')
@jwt_required()
def set_container_rate(container_size):
    user = current_user()
    if not user or user.role != 'admin':
        return jsonify({'status': 'error', 'message': 'Admin access is required.'}), 403
    container_size = container_size.strip().lower()
    if container_size not in CONTAINER_SIZES:
        return jsonify({'status': 'error', 'message': 'Choose a supported container size.'}), 400
    data = request.get_json(silent=True) or {}
    try:
        rate_kes = float(data.get('rate_kes'))
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Enter a valid KES rate.'}), 400
    if not 0 < rate_kes <= 10_000_000:
        return jsonify({'status': 'error', 'message': 'The rate must be greater than zero and at most KES 10,000,000.'}), 400

    rate = db.session.get(ContainerQuoteRate, container_size)
    if rate is None:
        rate = ContainerQuoteRate(container_size=container_size, rate_kes=rate_kes, updated_by_id=user.id)
        db.session.add(rate)
    else:
        rate.rate_kes = rate_kes
        rate.updated_by_id = user.id
        rate.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({'status': 'success', 'rate': rate.to_dict()}), 200


@portal_bp.post('/container-quote')
@jwt_required()
def quote_containers():
    data = request.get_json(silent=True) or {}
    size = data.get('size')
    try:
        quantity = int(data.get('quantity'))
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Enter a valid container quantity.'}), 400
    if size not in CONTAINER_SIZES or not 1 <= quantity <= 100:
        return jsonify({'status': 'error', 'message': 'Choose a supported container size and quantity between 1 and 100.'}), 400
    rate = db.session.get(ContainerQuoteRate, size)
    if rate is None:
        return jsonify({
            'status': 'error',
            'message': f'No rate is configured for {size} containers yet. Please contact Difan Logistics.',
        }), 409
    return jsonify({
        'status': 'success',
        'quote': {'size': size, 'quantity': quantity, 'rate_per_container_kes': rate.rate_kes,
                  'total_kes': round(rate.rate_kes * quantity, 2)},
    }), 200


@portal_bp.get('/payroll')
@jwt_required()
def list_payroll():
    user = current_user()
    if not user or user.role not in EMPLOYEE_ROLES:
        return jsonify({'status': 'error', 'message': 'Employee payroll access is required.'}), 403
    query = PayrollSlip.query
    if user.role != 'admin':
        query = query.filter_by(employee_id=user.id)
    slips = query.order_by(PayrollSlip.pay_period.desc(), PayrollSlip.id.desc()).all()
    status = employee_payroll_status(user)
    return jsonify({
        'status': 'success',
        'slips': [slip.to_dict() for slip in slips],
        'must_sign': status['must_sign'],
        'pending_slips': [slip.to_dict() for slip in status['pending']],
    }), 200


@portal_bp.post('/payroll')
@jwt_required()
def create_payroll_slip():
    admin = current_user()
    if not admin or admin.role != 'admin':
        return jsonify({'status': 'error', 'message': 'Admin access is required.'}), 403
    data = request.get_json(silent=True) or {}
    try:
        employee_id = int(data.get('employee_id'))
        basic_pay = float(data.get('basic_pay', 0))
        allowances = float(data.get('allowances', 0))
        bonus = float(data.get('bonus', 0))
        deductions = float(data.get('deductions', 0))
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Enter valid employee and payroll amounts.'}), 400
    period = data.get('pay_period', '').strip()
    employee = db.session.get(UserAccount, employee_id)
    if not employee or employee.role not in EMPLOYEE_ROLES:
        return jsonify({'status': 'error', 'message': 'Choose an existing employee account.'}), 400
    if not period or len(period) > 20:
        return jsonify({'status': 'error', 'message': 'Enter a payroll period of 20 characters or fewer.'}), 400
    if min(basic_pay, allowances, bonus, deductions) < 0 or max(basic_pay, allowances, bonus, deductions) > 100_000_000:
        return jsonify({'status': 'error', 'message': 'Payroll amounts must be non-negative and within the supported limit.'}), 400
    if PayrollSlip.query.filter_by(employee_id=employee.id, pay_period=period).first():
        return jsonify({'status': 'error', 'message': 'A payslip already exists for this employee and period.'}), 409

    gross_pay = round(basic_pay + allowances + bonus, 2)
    if deductions > gross_pay:
        return jsonify({'status': 'error', 'message': 'Deductions cannot exceed gross pay.'}), 400
    slip = PayrollSlip(
        employee_id=employee.id, pay_period=period, basic_pay=basic_pay,
        allowances=allowances, bonus=bonus, deductions=deductions,
        gross_pay=gross_pay, net_pay=round(gross_pay - deductions, 2),
        status='PENDING_APPROVAL', created_by_id=admin.id,
    )
    db.session.add(slip)
    db.session.commit()
    return jsonify({'status': 'success', 'slip': slip.to_dict()}), 201


@portal_bp.patch('/payroll/<int:slip_id>/approve')
@jwt_required()
def approve_payroll_slip(slip_id):
    admin = current_user()
    if not admin or admin.role != 'admin':
        return jsonify({'status': 'error', 'message': 'Admin access is required.'}), 403
    slip = db.session.get(PayrollSlip, slip_id)
    if not slip:
        return jsonify({'status': 'error', 'message': 'Payslip not found.'}), 404
    if slip.status != 'PENDING_APPROVAL':
        return jsonify({'status': 'error', 'message': 'Only pending payslips can be approved.'}), 409
    slip.status = 'APPROVED'
    slip.approved_by_id = admin.id
    slip.approved_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({'status': 'success', 'slip': slip.to_dict()}), 200


@portal_bp.post('/payroll/<int:slip_id>/sign')
@jwt_required()
def sign_payroll_slip(slip_id):
    user = current_user()
    slip = db.session.get(PayrollSlip, slip_id)
    if not user or not slip or slip.employee_id != user.id:
        return jsonify({'status': 'error', 'message': 'Payslip was not found for this account.'}), 404
    if slip.status != 'APPROVED':
        return jsonify({'status': 'error', 'message': 'This payslip must be approved before it can be signed.'}), 409
    data = request.get_json(silent=True) or {}
    if data.get('receipt_confirmed') is not True or data.get('paystub_confirmed') is not True:
        return jsonify({'status': 'error', 'message': 'Confirm both payslip receipt and paystub agreement.'}), 400
    signed_at = datetime.now(timezone.utc)
    slip.receipt_signed_at = slip.receipt_signed_at or signed_at
    slip.paystub_signed_at = slip.paystub_signed_at or signed_at
    db.session.commit()
    return jsonify({'status': 'success', 'slip': slip.to_dict()}), 200


@portal_bp.get('/mechanic-reports')
@jwt_required()
def list_mechanic_reports():
    user = current_user()
    if not user or user.role not in {'mechanic', 'admin'}:
        return jsonify({'status': 'error', 'message': 'Mechanic or Admin access is required.'}), 403
    query = MechanicIncidentReport.query
    if user.role == 'mechanic':
        query = query.filter_by(mechanic_id=user.id)
    reports = query.order_by(MechanicIncidentReport.created_at.desc()).all()
    return jsonify({'status': 'success', 'reports': [report.to_dict() for report in reports]}), 200


@portal_bp.post('/mechanic-reports')
@jwt_required()
def create_mechanic_report():
    user = current_user()
    if not user or user.role != 'mechanic':
        return jsonify({'status': 'error', 'message': 'Only Mechanics may submit incident reports.'}), 403
    data = request.get_json(silent=True) or {}
    required = {
        'vehicle_registration': (24, 'Vehicle registration'),
        'incident_date': (32, 'Incident date'),
        'location': (180, 'Location'),
        'severity': (24, 'Severity'),
        'symptoms': (1000, 'Symptoms'),
        'findings': (2000, 'Mechanic findings'),
        'action_taken': (2000, 'Action taken'),
    }
    values = {}
    for field, (max_length, label) in required.items():
        value = data.get(field)
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_length:
            return jsonify({'status': 'error', 'message': f'{label} is required and must be at most {max_length} characters.'}), 400
        values[field] = value.strip()
    if values['severity'] not in {'Low', 'Moderate', 'High', 'Critical'}:
        return jsonify({'status': 'error', 'message': 'Choose a valid incident severity.'}), 400
    parts_used = data.get('parts_used', '')
    if not isinstance(parts_used, str) or len(parts_used.strip()) > 1000:
        return jsonify({'status': 'error', 'message': 'Parts used must be at most 1,000 characters.'}), 400
    reference = f"MECH-{datetime.now(timezone.utc):%Y%m%d}-{user.id}-{int(datetime.now(timezone.utc).timestamp())}"
    report = MechanicIncidentReport(
        reference=reference, mechanic_id=user.id, parts_used=parts_used.strip() or None, **values,
    )
    db.session.add(report)
    db.session.commit()
    return jsonify({'status': 'success', 'report': report.to_dict()}), 201
