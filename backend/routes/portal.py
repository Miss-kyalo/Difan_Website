import io
import math
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, jsonify, request, send_file
from flask_jwt_extended import get_jwt_identity, jwt_required
from PIL import Image, UnidentifiedImageError
import pymupdf as fitz
from sqlalchemy.exc import SQLAlchemyError

from backend.models.payroll import db
from backend.routes.auth import ADMIN_ROLES, HR_ROLES, UserAccount
from backend.routes.shipments import Shipment, ShipmentGeofenceEvent

portal_bp = Blueprint('portal', __name__, url_prefix='/api/portal')
CONTAINER_SIZES = {'20ft', '40ft'}
EMPLOYEE_ROLES = ADMIN_ROLES | {'hr', 'driver', 'mechanic', 'accountant'}
FINANCE_VIEW_ROLES = ADMIN_ROLES | {'accountant', 'client'}
FINANCE_UPDATE_ROLES = ADMIN_ROLES | {'accountant'}
CLIENT_COMMUNICATION_ROLES = ADMIN_ROLES | HR_ROLES | {'accountant'}
MESSAGE_CONTACT_ROLES = {'admin', 'hr', 'boss', 'accountant'}
RATE_MANAGER_ROLES = ADMIN_ROLES | {'hr'}
REPORT_MAX_MEDIA_BYTES = 15 * 1024 * 1024
REPORT_MAX_MEDIA_FILES = 5
REPORT_MAX_IMAGE_PIXELS = 40_000_000
REPORT_MEDIA_FORMATS = {
    '.jpg': ('image', 'image/jpeg'),
    '.jpeg': ('image', 'image/jpeg'),
    '.png': ('image', 'image/png'),
    '.webp': ('image', 'image/webp'),
    '.mp4': ('video', 'video/mp4'),
    '.mov': ('video', 'video/quicktime'),
    '.webm': ('video', 'video/webm'),
    '.m4a': ('audio', 'audio/mp4'),
    '.mp3': ('audio', 'audio/mpeg'),
    '.wav': ('audio', 'audio/wav'),
    '.ogg': ('audio', 'audio/ogg'),
    '.opus': ('audio', 'audio/ogg'),
}
VAT_RATE = 0.16
REPORT_STATUSES = ('RECEIVED', 'UNDER_REVIEW', 'INVESTIGATING', 'ACTION_TAKEN', 'CLOSED')


class AnonymousReport(db.Model):
    __tablename__ = 'anonymous_reports'

    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(32), unique=True, nullable=False, index=True)
    description = db.Column(db.String(5000), nullable=False, default='')
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    status = db.Column(db.String(20), nullable=False, default='RECEIVED')
    status_updated_at = db.Column(db.DateTime(timezone=True), nullable=True)
    attachments = db.relationship('AnonymousReportAttachment', backref='report', lazy=True, cascade='all, delete-orphan')

    def status_dict(self):
        status = self.status if self.status in REPORT_STATUSES else 'RECEIVED'
        updated_at = self.status_updated_at or self.created_at
        return {
            'status': status,
            'status_step': REPORT_STATUSES.index(status) + 1,
            'status_total_steps': len(REPORT_STATUSES),
            'status_updated_at': updated_at.isoformat() if updated_at else None,
        }

    def to_dict(self):
        return {
            'id': self.id,
            'reference': self.reference,
            'description': self.description,
            'created_at': self.created_at.isoformat(),
            **self.status_dict(),
            'attachments': [attachment.to_dict() for attachment in self.attachments],
        }


class AnonymousReportAttachment(db.Model):
    __tablename__ = 'anonymous_report_attachments'

    id = db.Column(db.String(36), primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey('anonymous_reports.id'), nullable=False, index=True)
    storage_filename = db.Column(db.String(80), unique=True, nullable=False)
    media_type = db.Column(db.String(12), nullable=False)
    mime_type = db.Column(db.String(80), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'media_type': self.media_type,
            'mime_type': self.mime_type,
            'size_bytes': self.size_bytes,
        }


def inspect_report_media(contents, filename):
    extension = os.path.splitext(filename or '')[1].lower()
    media_format = REPORT_MEDIA_FORMATS.get(extension)
    if not media_format:
        raise ValueError('Use JPEG, PNG, WEBP, MP4, MOV, WEBM, M4A, MP3, WAV, OGG, or OPUS files.')

    media_type, mime_type = media_format
    if media_type == 'image':
        try:
            with Image.open(io.BytesIO(contents)) as image:
                if image.width * image.height > REPORT_MAX_IMAGE_PIXELS:
                    raise ValueError('Image dimensions exceed the supported limit.')
                actual_format = image.format
                image.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValueError('An image attachment is not a valid image file.') from exc
        expected_formats = {
            '.jpg': 'JPEG',
            '.jpeg': 'JPEG',
            '.png': 'PNG',
            '.webp': 'WEBP',
        }
        if actual_format != expected_formats[extension]:
            raise ValueError('The image contents do not match the file extension.')
    elif extension in {'.mp4', '.mov', '.m4a'}:
        if len(contents) < 12 or contents[4:8] != b'ftyp':
            raise ValueError('The video or audio attachment is not a valid media file.')
    elif extension == '.webm':
        if not contents.startswith(b'\x1a\x45\xdf\xa3'):
            raise ValueError('The WebM attachment is not a valid media file.')
    elif extension in {'.ogg', '.opus'}:
        if not contents.startswith(b'OggS'):
            raise ValueError('The OGG/OPUS attachment is not a valid audio file.')
    elif extension == '.wav':
        if len(contents) < 12 or contents[:4] != b'RIFF' or contents[8:12] != b'WAVE':
            raise ValueError('The WAV attachment is not a valid audio file.')
    elif extension == '.mp3':
        has_id3_header = contents.startswith(b'ID3')
        has_mpeg_frame = (
            len(contents) >= 2
            and contents[0] == 0xFF
            and contents[1] & 0xE0 == 0xE0
        )
        if not has_id3_header and not has_mpeg_frame:
            raise ValueError('The MP3 attachment is not a valid audio file.')

    return media_type, mime_type, extension


class ClientNotice(db.Model):
    __tablename__ = 'client_notices'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    body = db.Column(db.String(2000), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    author = db.relationship('UserAccount', foreign_keys=[author_id])

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'body': self.body,
            'author_name': self.author.display_name or self.author.email,
            'author_role': self.author.role,
            'created_at': self.created_at.isoformat(),
        }


class TransportEnquiry(db.Model):
    __tablename__ = 'transport_enquiries'

    id = db.Column(db.Integer, primary_key=True)
    contact_name = db.Column(db.String(120), nullable=False)
    company_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(254), nullable=False)
    phone = db.Column(db.String(40), nullable=False)
    origin = db.Column(db.String(200), nullable=False)
    destination = db.Column(db.String(200), nullable=False)
    cargo_description = db.Column(db.String(500), nullable=False)
    tonnage = db.Column(db.Float, nullable=True)
    pickup_date = db.Column(db.String(10), nullable=True)
    notes = db.Column(db.String(2000), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='OPEN')
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    handled_by_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=True)
    handled_by = db.relationship('UserAccount', foreign_keys=[handled_by_id])

    def to_dict(self):
        return {
            'id': self.id,
            'contact_name': self.contact_name,
            'company_name': self.company_name,
            'email': self.email,
            'phone': self.phone,
            'origin': self.origin,
            'destination': self.destination,
            'cargo_description': self.cargo_description,
            'tonnage': self.tonnage,
            'pickup_date': self.pickup_date,
            'notes': self.notes,
            'status': self.status,
            'created_at': self.created_at.isoformat(),
            'handled_by': self.handled_by.display_name if self.handled_by else None,
        }


class ClientConversation(db.Model):
    __tablename__ = 'client_conversations'
    __table_args__ = (
        db.UniqueConstraint('client_user_id', 'staff_user_id', name='uq_client_conversation_pair'),
    )

    id = db.Column(db.Integer, primary_key=True)
    client_user_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False, index=True)
    staff_user_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False, index=True)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    client = db.relationship('UserAccount', foreign_keys=[client_user_id])
    staff = db.relationship('UserAccount', foreign_keys=[staff_user_id])
    messages = db.relationship('ClientMessage', backref='conversation', lazy=True, cascade='all, delete-orphan')


class ClientMessage(db.Model):
    __tablename__ = 'client_messages'

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('client_conversations.id'), nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False)
    body = db.Column(db.String(2000), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    sender = db.relationship('UserAccount', foreign_keys=[sender_id])

    def to_dict(self):
        return {
            'id': self.id,
            'sender_id': self.sender_id,
            'sender_name': self.sender.display_name or self.sender.email,
            'body': self.body,
            'created_at': self.created_at.isoformat(),
        }


class ShipmentFinance(db.Model):
    __tablename__ = 'shipment_finance'

    tracking_number = db.Column(
        db.String(40),
        db.ForeignKey('shipments.tracking_number'),
        primary_key=True,
    )
    invoice_amount_kes = db.Column(db.Float, nullable=True)
    paid_amount_kes = db.Column(db.Float, nullable=False, default=0)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=True)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=True)
    updated_by = db.relationship('UserAccount', foreign_keys=[updated_by_id])
    shipment = db.relationship('Shipment', foreign_keys=[tracking_number])

    def to_dict(self):
        invoice_amount = self.invoice_amount_kes
        if invoice_amount is None and self.shipment:
            invoice_amount = self.shipment.quoted_amount_kes
        paid_amount = round(self.paid_amount_kes, 2)
        balance = round(max((invoice_amount or 0) - paid_amount, 0), 2)
        if invoice_amount is None:
            payment_status = 'not_invoiced'
        elif balance == 0:
            payment_status = 'paid'
        elif paid_amount > 0:
            payment_status = 'partially_paid'
        else:
            payment_status = 'pending'

        return {
            'tracking_number': self.tracking_number,
            'company_name': self.shipment.company_name or '',
            'destination': self.shipment.destination,
            'shipment_status': self.shipment.status,
            'invoice_amount_kes': invoice_amount,
            'paid_amount_kes': paid_amount,
            'balance_kes': balance,
            'payment_status': payment_status,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


def parse_amount(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError
    amount = float(value)
    if not math.isfinite(amount):
        raise ValueError
    return amount


def parse_integer(value):
    if isinstance(value, bool):
        raise ValueError
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        return int(value)
    raise ValueError


def request_data():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


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
    salary_advance = db.Column(db.Float, nullable=False, default=0)
    housing_allowance = db.Column(db.Float, nullable=False, default=0)
    off_duty_days = db.Column(db.Float, nullable=False, default=0)
    off_duty_pay = db.Column(db.Float, nullable=False, default=0)
    nssf_deduction = db.Column(db.Float, nullable=True)
    shif_deduction = db.Column(db.Float, nullable=True)
    housing_levy_deduction = db.Column(db.Float, nullable=True)
    taxable_pay = db.Column(db.Float, nullable=True)
    tax_charged = db.Column(db.Float, nullable=True)
    personal_relief = db.Column(db.Float, nullable=True)
    other_reliefs = db.Column(db.Float, nullable=True)
    paye_tax = db.Column(db.Float, nullable=True)
    gross_pay = db.Column(db.Float, nullable=False)
    net_pay = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(24), nullable=False, default='PENDING_APPROVAL')
    created_by_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=True)
    approved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    receipt_signed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    paystub_signed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    advance_signed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    signed_pdf_object_key = db.Column(db.String(512), nullable=True)
    signed_pdf_version_id = db.Column(db.String(256), nullable=True)
    signed_pdf_sha256 = db.Column(db.String(64), nullable=True)
    signature_device_id = db.Column(db.String(120), nullable=True)
    signature_ip_address = db.Column(db.String(64), nullable=True)
    signature_latitude = db.Column(db.Float, nullable=True)
    signature_longitude = db.Column(db.Float, nullable=True)
    dispute_message = db.Column(db.String(2000), nullable=True)
    dispute_submitted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    dispute_status = db.Column(db.String(24), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    employee = db.relationship('UserAccount', foreign_keys=[employee_id])

    def to_dict(self):
        employee_name = self.employee.display_name or self.employee.driver_name or self.employee.email
        dispute_deadline = payroll_dispute_deadline(self.pay_period)
        return {
            'id': self.id,
            'employee_id': self.employee_id,
            'employee_name': employee_name,
            'employee_email': self.employee.email,
            'pay_period': self.pay_period,
            'basic_pay': self.basic_pay,
            'allowances': self.allowances,
            'housing_allowance': self.housing_allowance,
            'off_duty_days': self.off_duty_days,
            'off_duty_pay': self.off_duty_pay,
            'bonus': self.bonus,
            'deductions': self.deductions,
            'salary_advance': self.salary_advance,
            'salary_advance_label': 'Salary Advance / Early Cashout',
            'nssf_deduction': self.nssf_deduction,
            'shif_deduction': self.shif_deduction,
            'housing_levy_deduction': self.housing_levy_deduction,
            'taxable_pay': self.taxable_pay,
            'tax_charged': self.tax_charged,
            'personal_relief': self.personal_relief,
            'other_reliefs': self.other_reliefs,
            'paye_tax': self.paye_tax,
            'gross_pay': self.gross_pay,
            'net_pay': self.net_pay,
            'status': self.status,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'receipt_signed_at': self.receipt_signed_at.isoformat() if self.receipt_signed_at else None,
            'paystub_signed_at': self.paystub_signed_at.isoformat() if self.paystub_signed_at else None,
            'advance_signed_at': self.advance_signed_at.isoformat() if self.advance_signed_at else None,
            'signed_pdf_sha256': self.signed_pdf_sha256,
            'dispute_message': self.dispute_message,
            'dispute_submitted_at': self.dispute_submitted_at.isoformat() if self.dispute_submitted_at else None,
            'dispute_status': self.dispute_status,
            'dispute_deadline_at': dispute_deadline.isoformat() if dispute_deadline else None,
            'dispute_window_open': bool(
                dispute_deadline
                and datetime.now(ZoneInfo('Africa/Nairobi')) <= dispute_deadline
            ),
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


@portal_bp.post('/transport-enquiries')
def create_transport_enquiry():
    data = request_data()
    string_fields = {
        'contact_name': (120, 'Your name'),
        'company_name': (120, 'Company'),
        'email': (254, 'Email'),
        'phone': (40, 'Phone'),
        'origin': (200, 'Pickup location'),
        'destination': (200, 'Destination'),
        'cargo_description': (500, 'Cargo description'),
    }
    values = {}
    for field, (max_length, label) in string_fields.items():
        value = data.get(field)
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_length:
            return jsonify({'status': 'error', 'message': f'{label} is required and must be at most {max_length} characters.'}), 400
        values[field] = value.strip()
    if '@' not in values['email'] or values['email'].startswith('@') or values['email'].endswith('@'):
        return jsonify({'status': 'error', 'message': 'Enter a valid email address.'}), 400
    if not re.fullmatch(r'[+0-9() .-]{7,40}', values['phone']):
        return jsonify({'status': 'error', 'message': 'Enter a valid phone number.'}), 400

    try:
        tonnage = parse_amount(data.get('tonnage')) if data.get('tonnage') not in (None, '') else None
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Cargo weight must be a valid number of tonnes.'}), 400
    if tonnage is not None and not 0 < tonnage <= 100:
        return jsonify({'status': 'error', 'message': 'Cargo weight must be greater than zero and no more than 100 tonnes.'}), 400

    pickup_date = data.get('pickup_date', '')
    if pickup_date:
        if not isinstance(pickup_date, str):
            return jsonify({'status': 'error', 'message': 'Choose a valid requested pickup date.'}), 400
        try:
            datetime.strptime(pickup_date, '%Y-%m-%d')
        except ValueError:
            return jsonify({'status': 'error', 'message': 'Choose a valid requested pickup date.'}), 400
    notes = data.get('notes', '')
    if not isinstance(notes, str) or len(notes.strip()) > 2000:
        return jsonify({'status': 'error', 'message': 'Additional details must be at most 2,000 characters.'}), 400

    enquiry = TransportEnquiry(
        **values,
        tonnage=tonnage,
        pickup_date=pickup_date or None,
        notes=notes.strip() or None,
    )
    db.session.add(enquiry)
    db.session.commit()
    return jsonify({
        'status': 'success',
        'message': 'Your transport enquiry was sent to the Difan team.',
        'reference': f'TE-{enquiry.id:06d}',
    }), 201


@portal_bp.get('/transport-enquiries')
@jwt_required()
def list_transport_enquiries():
    user = current_user()
    if not user or user.account_status != 'active' or user.role not in ADMIN_ROLES:
        return jsonify({'status': 'error', 'message': 'HR or management access is required to view transport enquiries.'}), 403
    enquiries = TransportEnquiry.query.order_by(
        TransportEnquiry.created_at.desc(),
        TransportEnquiry.id.desc(),
    ).limit(200).all()
    return jsonify({'status': 'success', 'enquiries': [item.to_dict() for item in enquiries]}), 200


@portal_bp.patch('/transport-enquiries/<int:enquiry_id>')
@jwt_required()
def update_transport_enquiry(enquiry_id):
    user = current_user()
    if not user or user.account_status != 'active' or user.role not in ADMIN_ROLES:
        return jsonify({'status': 'error', 'message': 'HR or management access is required to update transport enquiries.'}), 403
    enquiry = db.session.get(TransportEnquiry, enquiry_id)
    if not enquiry:
        return jsonify({'status': 'error', 'message': 'Transport enquiry was not found.'}), 404
    data = request_data()
    status = data.get('status')
    if status not in {'OPEN', 'CONTACTED', 'CLOSED'}:
        return jsonify({'status': 'error', 'message': 'Choose Open, Contacted, or Closed.'}), 400
    enquiry.status = status
    enquiry.handled_by_id = user.id
    db.session.commit()
    return jsonify({'status': 'success', 'enquiry': enquiry.to_dict()}), 200


def employee_payroll_status(user):
    from backend.routes.workforce import employee_acknowledgement_status

    pending = employee_acknowledgement_status(user)
    return {
        'must_sign': pending['must_acknowledge'],
        'pending': pending['pending_slips'],
        'pending_notices': pending['pending_notices'],
    }


def conversation_for_user(conversation_id, user):
    conversation = db.session.get(ClientConversation, conversation_id)
    if not conversation:
        return None
    if user.role == 'client' and conversation.client_user_id == user.id:
        return conversation
    if user.role in CLIENT_COMMUNICATION_ROLES and conversation.staff_user_id == user.id:
        return conversation
    return None


@portal_bp.post('/anonymous-reports')
def submit_anonymous_report():
    description = request.form.get('description', '')
    if not isinstance(description, str) or len(description.strip()) > 5000:
        return jsonify({'status': 'error', 'message': 'Report details must be at most 5,000 characters.'}), 400
    uploads = [file for file in request.files.getlist('attachments') if file and file.filename]
    if not description.strip() and not uploads:
        return jsonify({'status': 'error', 'message': 'Add a written report or at least one attachment.'}), 400
    if len(uploads) > REPORT_MAX_MEDIA_FILES:
        return jsonify({'status': 'error', 'message': f'Attach no more than {REPORT_MAX_MEDIA_FILES} files.'}), 400

    prepared = []
    try:
        for uploaded in uploads:
            contents = uploaded.read(REPORT_MAX_MEDIA_BYTES + 1)
            if len(contents) > REPORT_MAX_MEDIA_BYTES:
                return jsonify({'status': 'error', 'message': 'Each report attachment must be 15 MB or smaller.'}), 413
            media_type, mime_type, extension = inspect_report_media(contents, uploaded.filename or '')
            prepared.append({
                'id': str(uuid.uuid4()),
                'storage_filename': f'{uuid.uuid4().hex}{extension}',
                'media_type': media_type,
                'mime_type': mime_type,
                'size_bytes': len(contents),
                'contents': contents,
            })
    except ValueError as exc:
        return jsonify({'status': 'error', 'message': str(exc)}), 422

    report = AnonymousReport()
    report.reference = f"AR-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:10].upper()}"
    report.description = description.strip()
    report.status = 'RECEIVED'
    db.session.add(report)
    report_directory = current_app.config['ANONYMOUS_REPORTS_DIR']
    os.makedirs(report_directory, mode=0o700, exist_ok=True)
    os.chmod(report_directory, 0o700)
    written_paths = []
    try:
        for item in prepared:
            path = os.path.join(report_directory, item['storage_filename'])
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'wb') as media_file:
                media_file.write(item['contents'])
            written_paths.append(path)
            attachment = AnonymousReportAttachment()
            attachment.id = item['id']
            attachment.report = report
            attachment.storage_filename = item['storage_filename']
            attachment.media_type = item['media_type']
            attachment.mime_type = item['mime_type']
            attachment.size_bytes = item['size_bytes']
            db.session.add(attachment)
        db.session.commit()
    except OSError:
        db.session.rollback()
        for path in written_paths:
            if os.path.exists(path):
                os.remove(path)
        current_app.logger.exception('Failed to securely store an anonymous report attachment.')
        return jsonify({'status': 'error', 'message': 'The report could not be securely stored. Please try again.'}), 500
    except SQLAlchemyError:
        db.session.rollback()
        for path in written_paths:
            if os.path.exists(path):
                os.remove(path)
        current_app.logger.exception('Failed to save an anonymous report.')
        return jsonify({'status': 'error', 'message': 'The report could not be saved. Please try again.'}), 500

    return jsonify({
        'status': 'success',
        'message': 'Your report was submitted anonymously.',
        'reference': report.reference,
        'report_status': report.status_dict(),
    }), 201


@portal_bp.get('/anonymous-reports/status/<reference>')
def anonymous_report_status(reference):
    report = AnonymousReport.query.filter_by(reference=reference.strip().upper()).first()
    if not report:
        return jsonify({'status': 'error', 'message': 'No report was found with that reference.'}), 404
    return jsonify({
        'status': 'success',
        'reference': report.reference,
        'report_status': report.status_dict(),
        'statuses': list(REPORT_STATUSES),
    }), 200


@portal_bp.patch('/anonymous-reports/<int:report_id>/status')
@jwt_required()
def update_anonymous_report_status(report_id):
    user = current_user()
    if not user or user.account_status != 'active' or user.role != 'boss':
        return jsonify({'status': 'error', 'message': 'Only the Boss can update anonymous report progress.'}), 403
    report = db.session.get(AnonymousReport, report_id)
    if not report:
        return jsonify({'status': 'error', 'message': 'Report was not found.'}), 404
    payload = request.get_json(silent=True)
    new_status = payload.get('status') if isinstance(payload, dict) else None
    if new_status not in REPORT_STATUSES:
        return jsonify({'status': 'error', 'message': 'Choose a valid report status.'}), 400
    report.status = new_status
    report.status_updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({'status': 'success', 'report': report.to_dict()}), 200


@portal_bp.get('/anonymous-reports')
@jwt_required()
def list_anonymous_reports():
    user = current_user()
    if not user or user.account_status != 'active' or user.role != 'boss':
        return jsonify({'status': 'error', 'message': 'Only the Boss can view anonymous reports.'}), 403

    reports = AnonymousReport.query.order_by(
        AnonymousReport.created_at.desc(),
        AnonymousReport.id.desc(),
    ).limit(200).all()
    return jsonify({'status': 'success', 'reports': [report.to_dict() for report in reports]}), 200


@portal_bp.get('/anonymous-reports/<int:report_id>/attachments/<attachment_id>')
@jwt_required()
def download_anonymous_report_attachment(report_id, attachment_id):
    user = current_user()
    if not user or user.account_status != 'active' or user.role != 'boss':
        return jsonify({'status': 'error', 'message': 'Only the Boss can access anonymous report attachments.'}), 403

    attachment = db.session.get(AnonymousReportAttachment, attachment_id)
    if not attachment or attachment.report_id != report_id:
        return jsonify({'status': 'error', 'message': 'Report attachment was not found.'}), 404

    path = os.path.join(current_app.config['ANONYMOUS_REPORTS_DIR'], attachment.storage_filename)
    if not os.path.isfile(path):
        return jsonify({'status': 'error', 'message': 'Report attachment is unavailable.'}), 404

    extension = os.path.splitext(attachment.storage_filename)[1]
    return send_file(
        path,
        mimetype=attachment.mime_type,
        as_attachment=True,
        download_name=f'report-{report_id}-attachment{extension}',
        conditional=True,
    )


@portal_bp.get('/client-notices')
@jwt_required()
def list_client_notices():
    user = current_user()
    if not user or user.account_status != 'active' or (
        user.role != 'client' and user.role not in CLIENT_COMMUNICATION_ROLES
    ):
        return jsonify({'status': 'error', 'message': 'Client notice access is not available for this account.'}), 403

    notices = ClientNotice.query.order_by(ClientNotice.created_at.desc(), ClientNotice.id.desc()).limit(100).all()
    return jsonify({'status': 'success', 'notices': [notice.to_dict() for notice in notices]}), 200


@portal_bp.post('/client-notices')
@jwt_required()
def create_client_notice():
    user = current_user()
    if not user or user.account_status != 'active' or user.role not in CLIENT_COMMUNICATION_ROLES:
        return jsonify({'status': 'error', 'message': 'Only Admin, HR, or Accounts may publish client notices.'}), 403

    data = request_data()
    title = data.get('title')
    body = data.get('body')
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 120:
        return jsonify({'status': 'error', 'message': 'Notice title is required and must be at most 120 characters.'}), 400
    if not isinstance(body, str) or not body.strip() or len(body.strip()) > 2000:
        return jsonify({'status': 'error', 'message': 'Notice text is required and must be at most 2,000 characters.'}), 400

    notice = ClientNotice()
    notice.title = title.strip()
    notice.body = body.strip()
    notice.author_id = user.id
    db.session.add(notice)
    db.session.commit()
    return jsonify({'status': 'success', 'notice': notice.to_dict()}), 201


@portal_bp.get('/client-conversations')
@jwt_required()
def list_client_conversations():
    user = current_user()
    if not user or user.account_status != 'active' or (
        user.role != 'client' and user.role not in CLIENT_COMMUNICATION_ROLES
    ):
        return jsonify({'status': 'error', 'message': 'Client messages are not available for this account.'}), 403

    query = ClientConversation.query
    if user.role == 'client':
        query = query.filter_by(client_user_id=user.id)
        contacts = UserAccount.query.filter(
            UserAccount.role.in_(MESSAGE_CONTACT_ROLES),
            UserAccount.account_status == 'active',
        ).order_by(UserAccount.role, UserAccount.display_name, UserAccount.email).all()
        contact_rows = [
            {
                'id': contact.id,
                'display_name': contact.display_name or contact.email,
                'role': contact.role,
            }
            for contact in contacts
        ]
    else:
        query = query.filter_by(staff_user_id=user.id)
        contacts = UserAccount.query.filter_by(
            role='client',
            account_status='active',
        ).order_by(UserAccount.company_name, UserAccount.display_name, UserAccount.email).all()
        contact_rows = [
            {
                'id': contact.id,
                'display_name': contact.company_name or contact.display_name or contact.email,
                'role': contact.role,
            }
            for contact in contacts
        ]

    conversations = query.order_by(ClientConversation.updated_at.desc(), ClientConversation.id.desc()).all()
    conversation_rows = []
    for conversation in conversations:
        latest_message = ClientMessage.query.filter_by(
            conversation_id=conversation.id,
        ).order_by(ClientMessage.created_at.desc(), ClientMessage.id.desc()).first()
        peer = conversation.staff if user.role == 'client' else conversation.client
        conversation_rows.append({
            'id': conversation.id,
            'peer_name': peer.display_name or peer.email,
            'peer_role': peer.role,
            'last_message': latest_message.body if latest_message else '',
            'updated_at': conversation.updated_at.isoformat(),
        })

    return jsonify({
        'status': 'success',
        'contacts': contact_rows,
        'conversations': conversation_rows,
    }), 200


@portal_bp.post('/client-conversations')
@jwt_required()
def start_client_conversation():
    user = current_user()
    data = request_data()
    try:
        if user and user.role == 'client':
            client = user
            staff_user_id = parse_integer(data.get('staff_user_id'))
            staff = db.session.get(UserAccount, staff_user_id)
        elif user and user.role in CLIENT_COMMUNICATION_ROLES:
            client_user_id = parse_integer(data.get('client_user_id'))
            client = db.session.get(UserAccount, client_user_id)
            staff = user
        else:
            return jsonify({'status': 'error', 'message': 'This account cannot start a private conversation.'}), 403
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Choose a recipient for this conversation.'}), 400
    if not user or user.account_status != 'active':
        return jsonify({'status': 'error', 'message': 'This account is not active.'}), 403
    if user.role == 'client':
        if not staff or staff.account_status != 'active' or staff.role not in MESSAGE_CONTACT_ROLES:
            return jsonify({'status': 'error', 'message': 'Choose an active Admin, HR, Boss, or Accounts contact.'}), 400
    elif not client or client.account_status != 'active' or client.role != 'client':
        return jsonify({'status': 'error', 'message': 'Choose an active client account.'}), 400

    conversation = ClientConversation.query.filter_by(
        client_user_id=client.id,
        staff_user_id=staff.id,
    ).first()
    if conversation is None:
        conversation = ClientConversation()
        conversation.client_user_id = client.id
        conversation.staff_user_id = staff.id
        conversation.updated_at = datetime.now(timezone.utc)
        db.session.add(conversation)
        db.session.commit()

    peer = staff if user.role == 'client' else client
    return jsonify({
        'status': 'success',
        'conversation': {
            'id': conversation.id,
            'peer_name': peer.company_name if peer.role == 'client' else peer.display_name or peer.email,
            'peer_role': peer.role,
        },
    }), 201


@portal_bp.get('/client-conversations/<int:conversation_id>/messages')
@jwt_required()
def list_client_messages(conversation_id):
    user = current_user()
    if not user or user.account_status != 'active' or (
        user.role != 'client' and user.role not in CLIENT_COMMUNICATION_ROLES
    ):
        return jsonify({'status': 'error', 'message': 'Client messages are not available for this account.'}), 403
    conversation = conversation_for_user(conversation_id, user)
    if not conversation:
        return jsonify({'status': 'error', 'message': 'Conversation not found.'}), 404

    messages = ClientMessage.query.filter_by(
        conversation_id=conversation.id,
    ).order_by(ClientMessage.created_at.desc(), ClientMessage.id.desc()).limit(100).all()
    messages.reverse()
    return jsonify({'status': 'success', 'messages': [message.to_dict() for message in messages]}), 200


@portal_bp.post('/client-conversations/<int:conversation_id>/messages')
@jwt_required()
def send_client_message(conversation_id):
    user = current_user()
    if not user or user.account_status != 'active' or (
        user.role != 'client' and user.role not in CLIENT_COMMUNICATION_ROLES
    ):
        return jsonify({'status': 'error', 'message': 'Client messages are not available for this account.'}), 403
    conversation = conversation_for_user(conversation_id, user)
    if not conversation:
        return jsonify({'status': 'error', 'message': 'Conversation not found.'}), 404

    data = request_data()
    body = data.get('body')
    if not isinstance(body, str) or not body.strip() or len(body.strip()) > 2000:
        return jsonify({'status': 'error', 'message': 'Message is required and must be at most 2,000 characters.'}), 400

    message = ClientMessage()
    message.conversation_id = conversation.id
    message.sender_id = user.id
    message.body = body.strip()
    conversation.updated_at = datetime.now(timezone.utc)
    db.session.add(message)
    db.session.commit()
    return jsonify({'status': 'success', 'message': message.to_dict()}), 201


@portal_bp.get('/delivery-finance')
@jwt_required()
def list_delivery_finance():
    user = current_user()
    if not user or user.role not in FINANCE_VIEW_ROLES:
        return jsonify({'status': 'error', 'message': 'Finance access is not available for this account.'}), 403

    shipments = Shipment.query.order_by(Shipment.created_at.desc()).all()
    if user.role == 'client':
        company_name = (user.company_name or '').strip().casefold()
        shipments = [
            shipment for shipment in shipments
            if shipment.company_name and shipment.company_name.strip().casefold() == company_name
        ]

    records = []
    for shipment in shipments:
        finance = db.session.get(ShipmentFinance, shipment.tracking_number)
        if finance is None:
            finance = ShipmentFinance()
            finance.tracking_number = shipment.tracking_number
            finance.invoice_amount_kes = None
            finance.paid_amount_kes = 0
            finance.shipment = shipment
        records.append(finance.to_dict())

    return jsonify({
        'status': 'success',
        'deliveries': records,
        'summary': {
            'delivery_count': len(records),
            'paid_count': sum(row['payment_status'] == 'paid' for row in records),
            'pending_count': sum(row['payment_status'] in {'pending', 'partially_paid', 'not_invoiced'} for row in records),
            'paid_amount_kes': round(sum(row['paid_amount_kes'] for row in records), 2),
            'balance_kes': round(sum(row['balance_kes'] for row in records), 2),
        },
        'can_update': user.role in FINANCE_UPDATE_ROLES,
    }), 200


@portal_bp.get('/delivery-finance/monthly-statement')
@jwt_required()
def download_monthly_delivery_statement():
    user = current_user()
    if not user or user.role not in FINANCE_VIEW_ROLES:
        return jsonify({'status': 'error', 'message': 'Finance access is not available for this account.'}), 403

    month_value = request.args.get('month', '')
    try:
        month_start = datetime.strptime(month_value, '%Y-%m').replace(tzinfo=timezone.utc)
        if month_start.strftime('%Y-%m') != month_value:
            raise ValueError
    except ValueError:
        return jsonify({'status': 'error', 'message': 'Choose a statement month in YYYY-MM format.'}), 400

    if month_start.month == 12:
        month_end = month_start.replace(year=month_start.year + 1, month=1)
    else:
        month_end = month_start.replace(month=month_start.month + 1)

    shipments = Shipment.query.filter(
        Shipment.status == 'DELIVERED',
        Shipment.arrived_at >= month_start,
        Shipment.arrived_at < month_end,
    ).order_by(Shipment.arrived_at.asc()).all()
    if user.role == 'client':
        company_name = (user.company_name or '').strip().casefold()
        shipments = [
            shipment for shipment in shipments
            if shipment.client_user_id == user.id
            or (
                shipment.client_user_id is None
                and (shipment.company_name or '').strip().casefold() == company_name
            )
        ]

    tracking_numbers = [shipment.tracking_number for shipment in shipments]
    finance_by_tracking = {
        finance.tracking_number: finance
        for finance in ShipmentFinance.query.filter(
            ShipmentFinance.tracking_number.in_(tracking_numbers)
        ).all()
    } if tracking_numbers else {}
    geofence_events = ShipmentGeofenceEvent.query.filter(
        ShipmentGeofenceEvent.shipment_tracking_number.in_(tracking_numbers),
        ShipmentGeofenceEvent.site_type == 'PICKUP',
    ).order_by(ShipmentGeofenceEvent.recorded_at.asc()).all() if tracking_numbers else []

    dwell_by_tracking = {}
    open_arrivals = {}
    for event in geofence_events:
        tracking_number = event.shipment_tracking_number
        if event.event_type == 'ARRIVE':
            open_arrivals.setdefault(tracking_number, event.recorded_at)
        elif event.event_type == 'DEPART' and tracking_number in open_arrivals:
            started_at = open_arrivals.pop(tracking_number)
            dwell_seconds = (event.recorded_at - started_at).total_seconds()
            if dwell_seconds >= 0:
                dwell_by_tracking.setdefault(tracking_number, []).append(dwell_seconds)
    dwell_minutes = [
        seconds / 60
        for durations in dwell_by_tracking.values()
        for seconds in durations
    ]

    rows = []
    invoice_total = paid_total = balance_total = 0.0
    for shipment in shipments:
        finance = finance_by_tracking.get(shipment.tracking_number)
        invoice_amount = (
            finance.invoice_amount_kes
            if finance and finance.invoice_amount_kes is not None
            else shipment.quoted_amount_kes
        )
        paid_amount = finance.paid_amount_kes if finance else 0.0
        balance = max((invoice_amount or 0) - paid_amount, 0)
        invoice_total += invoice_amount or 0
        paid_total += paid_amount
        balance_total += balance
        rows.append((
            shipment.tracking_number,
            shipment.arrived_at.strftime('%Y-%m-%d'),
            f'{shipment.origin} to {shipment.destination}',
            round(invoice_amount, 2) if invoice_amount is not None else None,
            round(paid_amount, 2),
            round(balance, 2),
        ))

    average_wait_minutes = (
        sum(dwell_minutes) / len(dwell_minutes) if dwell_minutes else None
    )
    document = fitz.open()
    page = document.new_page()
    y = 48
    company_label = user.company_name if user.role == 'client' else 'All client accounts'
    page.insert_text((42, y), f'Monthly Delivery Statement - {month_value}', fontsize=16)
    y += 24
    page.insert_text((42, y), f'Account: {company_label or "Client"}', fontsize=10)
    y += 20
    page.insert_text(
        (42, y),
        f'Deliveries: {len(rows)} | Average pickup wait: '
        f'{"n/a" if average_wait_minutes is None else f"{average_wait_minutes:.1f} minutes"}',
        fontsize=10,
    )
    y += 24
    page.insert_text((42, y), 'Tracking / Date / Route / Invoice / Paid / Balance (KES)', fontsize=9)
    y += 16
    for tracking, delivered_date, route, invoice, paid, balance in rows:
        if y > 770:
            page = document.new_page()
            y = 48
            page.insert_text((42, y), f'Monthly Delivery Statement - {month_value}', fontsize=13)
            y += 24
        invoice_text = 'Not invoiced' if invoice is None else f'{invoice:,.2f}'
        page.insert_text(
            (42, y),
            f'{tracking} | {delivered_date} | {route[:42]} | {invoice_text} | {paid:,.2f} | {balance:,.2f}',
            fontsize=8,
        )
        y += 16
    if y > 770:
        page = document.new_page()
        y = 48
    page.insert_text(
        (42, y + 8),
        f'Totals (KES): Invoiced {invoice_total:,.2f} | Paid {paid_total:,.2f} | Outstanding {balance_total:,.2f}',
        fontsize=9,
    )
    pdf_bytes = document.tobytes()
    document.close()
    response = send_file(
        io.BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'delivery-statement-{month_value}.pdf',
    )
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@portal_bp.patch('/delivery-finance/<tracking_number>')
@jwt_required()
def update_delivery_finance(tracking_number):
    user = current_user()
    if not user or user.role not in FINANCE_UPDATE_ROLES:
        return jsonify({'status': 'error', 'message': 'Accountant access is required to update delivery payments.'}), 403

    shipment = db.session.get(Shipment, tracking_number.strip().upper())
    if shipment is None:
        return jsonify({'status': 'error', 'message': 'Delivery was not found.'}), 404

    data = request_data()
    try:
        invoice_amount = round(parse_amount(data.get('invoice_amount_kes')), 2)
        mark_paid = data.get('mark_paid', False)
        if not isinstance(mark_paid, bool):
            raise ValueError
        paid_amount = invoice_amount if mark_paid else round(parse_amount(data.get('paid_amount_kes')), 2)
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Enter valid invoice and paid amounts.'}), 400

    if min(invoice_amount, paid_amount) < 0 or invoice_amount > 100_000_000 or paid_amount > invoice_amount:
        return jsonify({
            'status': 'error',
            'message': 'Amounts must be non-negative, within the supported limit, and paid cannot exceed the invoice total.',
        }), 400

    finance = db.session.get(ShipmentFinance, shipment.tracking_number)
    if finance is None:
        finance = ShipmentFinance()
        finance.tracking_number = shipment.tracking_number
        db.session.add(finance)
    finance.invoice_amount_kes = invoice_amount
    finance.paid_amount_kes = paid_amount
    finance.updated_by_id = user.id
    finance.updated_at = datetime.now(timezone.utc)
    db.session.commit()

    return jsonify({'status': 'success', 'delivery': finance.to_dict()}), 200


@portal_bp.post('/delivery-finance/bulk-mark-paid')
@jwt_required()
def bulk_mark_deliveries_paid():
    user = current_user()
    if not user or user.role not in FINANCE_UPDATE_ROLES:
        return jsonify({'status': 'error', 'message': 'Accountant access is required to update delivery payments.'}), 403

    data = request_data()
    tracking_numbers = data.get('tracking_numbers')
    if (
        not isinstance(tracking_numbers, list)
        or not tracking_numbers
        or len(tracking_numbers) > 100
        or any(not isinstance(value, str) or not value.strip() for value in tracking_numbers)
    ):
        return jsonify({'status': 'error', 'message': 'Select between 1 and 100 deliveries to mark paid.'}), 400
    normalized_numbers = [value.strip().upper() for value in tracking_numbers]
    if len(set(normalized_numbers)) != len(normalized_numbers):
        return jsonify({'status': 'error', 'message': 'The selected delivery list contains duplicates.'}), 400

    shipments = Shipment.query.filter(Shipment.tracking_number.in_(normalized_numbers)).all()
    shipments_by_number = {shipment.tracking_number: shipment for shipment in shipments}
    if len(shipments_by_number) != len(normalized_numbers):
        return jsonify({'status': 'error', 'message': 'One or more selected deliveries were not found.'}), 404

    finance_rows = {
        record.tracking_number: record
        for record in ShipmentFinance.query.filter(
            ShipmentFinance.tracking_number.in_(normalized_numbers),
        ).all()
    }
    missing_invoices = []
    for number in normalized_numbers:
        finance = finance_rows.get(number)
        invoice_amount = (
            finance.invoice_amount_kes if finance
            else shipments_by_number[number].quoted_amount_kes
        )
        if invoice_amount is None:
            missing_invoices.append(number)
    if missing_invoices:
        return jsonify({
            'status': 'error',
            'message': f'Add an invoice amount before bulk-marking paid: {", ".join(missing_invoices)}.',
        }), 409

    now = datetime.now(timezone.utc)
    for number in normalized_numbers:
        finance = finance_rows.get(number)
        if finance is None:
            finance = ShipmentFinance(
                tracking_number=number,
                invoice_amount_kes=shipments_by_number[number].quoted_amount_kes,
                paid_amount_kes=0,
            )
            db.session.add(finance)
        finance.paid_amount_kes = finance.invoice_amount_kes
        finance.updated_by_id = user.id
        finance.updated_at = now

    db.session.commit()
    return jsonify({
        'status': 'success',
        'message': f'{len(normalized_numbers)} delivery payment(s) marked fully paid.',
        'updated_count': len(normalized_numbers),
    }), 200


@portal_bp.get('/container-rates')
@jwt_required()
def get_container_rates():
    rates = ContainerQuoteRate.query.order_by(ContainerQuoteRate.container_size).all()
    return jsonify({'status': 'success', 'rates': [rate.to_dict() for rate in rates]}), 200


@portal_bp.put('/container-rates')
@jwt_required()
def set_container_rates():
    user = current_user()
    if not user or user.role not in RATE_MANAGER_ROLES:
        return jsonify({'status': 'error', 'message': 'Admin or HR access is required.'}), 403
    data = request_data()
    rates = data.get('rates')
    if not isinstance(rates, dict) or set(rates) != CONTAINER_SIZES:
        return jsonify({'status': 'error', 'message': 'Provide rates for both 20ft and 40ft containers.'}), 400

    parsed_rates = {}
    for size, value in rates.items():
        try:
            rate_kes = parse_amount(value)
        except (TypeError, ValueError):
            return jsonify({'status': 'error', 'message': f'Enter a valid {size} container rate.'}), 400
        if not 0 < rate_kes <= 10_000_000:
            return jsonify({
                'status': 'error',
                'message': f'The {size} rate must be greater than zero and at most KES 10,000,000.',
            }), 400
        parsed_rates[size] = rate_kes

    now = datetime.now(timezone.utc)
    for size, rate_kes in parsed_rates.items():
        rate = db.session.get(ContainerQuoteRate, size)
        if rate is None:
            rate = ContainerQuoteRate()
            rate.container_size = size
            rate.rate_kes = rate_kes
            rate.updated_by_id = user.id
            db.session.add(rate)
        else:
            rate.rate_kes = rate_kes
            rate.updated_by_id = user.id
            rate.updated_at = now
    db.session.commit()
    saved = ContainerQuoteRate.query.order_by(ContainerQuoteRate.container_size).all()
    return jsonify({'status': 'success', 'rates': [rate.to_dict() for rate in saved]}), 200


@portal_bp.put('/container-rates/<container_size>')
@jwt_required()
def set_container_rate(container_size):
    user = current_user()
    if not user or user.role not in RATE_MANAGER_ROLES:
        return jsonify({'status': 'error', 'message': 'Admin access is required.'}), 403
    container_size = container_size.strip().lower()
    if container_size not in CONTAINER_SIZES:
        return jsonify({'status': 'error', 'message': 'Choose a supported container size.'}), 400
    data = request_data()
    try:
        rate_kes = parse_amount(data.get('rate_kes'))
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Enter a valid KES rate.'}), 400
    if not 0 < rate_kes <= 10_000_000:
        return jsonify({'status': 'error', 'message': 'The rate must be greater than zero and at most KES 10,000,000.'}), 400

    rate = db.session.get(ContainerQuoteRate, container_size)
    if rate is None:
        rate = ContainerQuoteRate()
        rate.container_size = container_size
        rate.rate_kes = rate_kes
        rate.updated_by_id = user.id
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
    data = request_data()
    size = data.get('size')
    try:
        quantity = parse_integer(data.get('quantity'))
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Enter a valid container quantity.'}), 400
    if not isinstance(size, str) or size not in CONTAINER_SIZES or not 1 <= quantity <= 100:
        return jsonify({'status': 'error', 'message': 'Choose a supported container size and quantity between 1 and 100.'}), 400
    rate = db.session.get(ContainerQuoteRate, size)
    if rate is None:
        return jsonify({
            'status': 'error',
            'message': f'No rate is configured for {size} containers yet. Please contact Difan Logistics.',
        }), 409
    total_excluding_vat = round(rate.rate_kes * quantity, 2)
    vat_amount = round(total_excluding_vat * VAT_RATE, 2)
    return jsonify({
        'status': 'success',
        'quote': {
            'size': size,
            'quantity': quantity,
            'rate_per_container_kes': rate.rate_kes,
            'total_kes': total_excluding_vat,
            'vat_rate': VAT_RATE,
            'vat_amount_kes': vat_amount,
            'total_including_vat_kes': round(total_excluding_vat + vat_amount, 2),
        },
    }), 200


@portal_bp.get('/payroll')
@jwt_required()
def list_payroll():
    user = current_user()
    if not user or user.role not in EMPLOYEE_ROLES:
        return jsonify({'status': 'error', 'message': 'Employee payroll access is required.'}), 403
    status = employee_payroll_status(user)
    query = PayrollSlip.query
    if user.role not in ADMIN_ROLES or status['must_sign']:
        query = query.filter_by(employee_id=user.id)
    slips = query.order_by(PayrollSlip.pay_period.desc(), PayrollSlip.id.desc()).all()
    requested_year = request.args.get('year')
    if requested_year is not None:
        try:
            year = int(requested_year)
            if not 2000 <= year <= datetime.now(timezone.utc).year:
                raise ValueError
        except ValueError:
            return jsonify({'status': 'error', 'message': 'Choose a valid payroll year up to the current year.'}), 400
        today = datetime.now(timezone.utc)
        slips = [
            slip for slip in slips
            if (
                (period := parse_payroll_month(slip.pay_period, year=year)) is not None
                and (period.year < today.year or period.month <= today.month)
            )
        ]
    return jsonify({
        'status': 'success',
        'slips': [slip.to_dict() for slip in slips],
        'must_sign': status['must_sign'],
        'pending_slips': [slip.to_dict() for slip in status['pending']],
        'pending_notices': [notice.to_dict() for notice in status['pending_notices']],
    }), 200


def parse_payroll_month(pay_period, year=None):
    if not isinstance(pay_period, str):
        return None
    for date_format in ('%Y-%m', '%Y/%m', '%B %Y', '%b %Y'):
        try:
            parsed = datetime.strptime(pay_period.strip(), date_format)
            return parsed if year is None or parsed.year == year else None
        except ValueError:
            continue
    return None


def payroll_dispute_deadline(pay_period):
    period = parse_payroll_month(pay_period)
    if not period:
        return None
    next_month = datetime(
        period.year + (period.month == 12),
        1 if period.month == 12 else period.month + 1,
        1,
        tzinfo=ZoneInfo('Africa/Nairobi'),
    )
    release_at = next_month - timedelta(microseconds=1)
    return release_at - timedelta(hours=48)


@portal_bp.post('/payroll/<int:slip_id>/dispute')
@jwt_required()
def dispute_payroll_slip(slip_id):
    user = current_user()
    slip = db.session.get(PayrollSlip, slip_id)
    if not user or not slip or slip.employee_id != user.id:
        return jsonify({'status': 'error', 'message': 'Payslip was not found for this account.'}), 404
    if slip.status != 'APPROVED':
        return jsonify({'status': 'error', 'message': 'Only a published paystub can be contested.'}), 409
    deadline = payroll_dispute_deadline(slip.pay_period)
    now = datetime.now(ZoneInfo('Africa/Nairobi'))
    if deadline is None:
        return jsonify({'status': 'error', 'message': 'This pay period has no valid month-end dispute deadline.'}), 409
    if now > deadline:
        return jsonify({
            'status': 'error',
            'message': f'The contest window closed at {deadline.isoformat()}.',
            'dispute_deadline_at': deadline.isoformat(),
        }), 409
    data = request_data()
    message = data.get('message')
    if not isinstance(message, str) or not message.strip() or len(message.strip()) > 2000:
        return jsonify({'status': 'error', 'message': 'Enter the dispute details (up to 2,000 characters).'}), 400
    slip.dispute_message = message.strip()
    slip.dispute_submitted_at = datetime.now(timezone.utc)
    slip.dispute_status = 'SUBMITTED'
    db.session.commit()
    return jsonify({
        'status': 'success',
        'message': 'Your paystub contest was sent to HR.',
        'slip': slip.to_dict(),
    }), 201


def format_payroll_amount(value):
    return f'KES {value:,.2f}' if value is not None else 'Not entered'


def payroll_pdf_response(contents, filename):
    response = send_file(
        io.BytesIO(contents),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename,
        max_age=0,
    )
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


def _create_p9_pdf(employee, year):
    current = datetime.now(timezone.utc)
    if year > current.year:
        return None, 'A P9 cannot be generated for a future year.', 400
    final_month = current.month if year == current.year else 12
    slips = PayrollSlip.query.filter_by(employee_id=employee.id, status='APPROVED').all()
    by_month = {}
    for slip in slips:
        parsed = parse_payroll_month(slip.pay_period, year)
        if parsed:
            by_month.setdefault(parsed.month, []).append(slip)

    missing_months = [month for month in range(1, final_month + 1) if not by_month.get(month)]
    if missing_months:
        month_names = ', '.join(datetime(year, month, 1).strftime('%B') for month in missing_months)
        return None, f'Approved payroll records are missing for: {month_names}. No zero values were assumed.', 409
    duplicate_months = [month for month in range(1, final_month + 1) if len(by_month[month]) > 1]
    if duplicate_months:
        return None, 'More than one approved pay period maps to a month. Correct the payroll periods before generating P9.', 409

    required_fields = (
        'nssf_deduction', 'shif_deduction', 'housing_levy_deduction',
        'taxable_pay', 'tax_charged', 'personal_relief', 'other_reliefs', 'paye_tax',
    )
    for month in range(1, final_month + 1):
        slip = by_month[month][0]
        missing_fields = [field.replace('_', ' ') for field in required_fields if getattr(slip, field) is None]
        if missing_fields:
            month_name = datetime(year, month, 1).strftime('%B')
            return None, f'{month_name} payroll is missing explicitly entered statutory values: {", ".join(missing_fields)}.', 409

    employee_name = employee.display_name or employee.driver_name or employee.email
    employer_name = current_app.config.get('PAYROLL_EMPLOYER_NAME', 'Difan Logistics')
    employer_pin = current_app.config.get('PAYROLL_EMPLOYER_KRA_PIN') or 'Not configured'
    employee_pin = employee.kra_pin or current_app.config.get(f'PAYROLL_EMPLOYEE_{employee.id}_KRA_PIN') or 'Not provided'
    monthly_fields = (
        ('Gross pay', 'gross_pay'),
        ('NSSF', 'nssf_deduction'),
        ('SHIF', 'shif_deduction'),
        ('Housing levy', 'housing_levy_deduction'),
        ('Taxable pay', 'taxable_pay'),
        ('Tax charged', 'tax_charged'),
        ('Personal relief', 'personal_relief'),
        ('Other reliefs', 'other_reliefs'),
        ('PAYE', 'paye_tax'),
    )
    annual_totals = {field: 0.0 for _, field in monthly_fields}
    lines = [
        'DIFAN LOGISTICS - P9 ANNUAL TAX SUMMARY',
        f'Tax year: {year}',
        f'Employer: {employer_name}',
        f'Employer KRA PIN: {employer_pin}',
        f'Employee: {employee_name}',
        f'Employee KRA PIN: {employee_pin}',
        '',
        'Month | ' + ' | '.join(label for label, _ in monthly_fields),
    ]
    for month in range(1, final_month + 1):
        slip = by_month[month][0]
        values = []
        for label, field in monthly_fields:
            value = getattr(slip, field)
            annual_totals[field] += value
            values.append(f'{value:,.2f}')
        lines.append(datetime(year, month, 1).strftime('%b') + ' | ' + ' | '.join(values))
    lines.append('TOTAL | ' + ' | '.join(f'{annual_totals[field]:,.2f}' for _, field in monthly_fields))
    lines.extend([
        '',
        'Salary Advance / Early Cashout is disclosed separately on each paystub and is not treated as a statutory deduction in this summary.',
        'All statutory and tax values above are transcribed from explicitly entered, approved payroll records; no tax values were estimated.',
    ])

    document = fitz.open()
    page = document.new_page(width=842, height=595)
    page.insert_text((36, 34), lines[0], fontsize=16, fontname='helv')
    content = '\n'.join(lines[1:]).encode('latin-1', 'replace').decode('latin-1')
    page.insert_textbox(fitz.Rect(36, 52, 806, 560), content, fontsize=8, fontname='cour', lineheight=1.3)
    return document.tobytes(garbage=4, deflate=True), None, 200


@portal_bp.get('/payroll/<int:slip_id>/pdf')
@jwt_required()
def download_payroll_slip_pdf(slip_id):
    user = current_user()
    slip = db.session.get(PayrollSlip, slip_id)
    if not user or not slip or (
        slip.employee_id != user.id and user.role not in ADMIN_ROLES
    ):
        return jsonify({'status': 'error', 'message': 'Payslip was not found for this account.'}), 404
    lines = [
        'DIFAN LOGISTICS - PAYSLIP',
        f'Employee: {slip.employee.display_name or slip.employee.driver_name or slip.employee.email}',
        f'Pay period: {slip.pay_period}',
        f'Basic pay: {format_payroll_amount(slip.basic_pay)}',
        f'Housing allowance: {format_payroll_amount(slip.housing_allowance)}',
        f'Off-duty pay ({slip.off_duty_days:g} day(s)): {format_payroll_amount(slip.off_duty_pay)}',
        f'Allowances: {format_payroll_amount(slip.allowances)}',
        f'Bonus: {format_payroll_amount(slip.bonus)}',
        f'Gross pay: {format_payroll_amount(slip.gross_pay)}',
        f'Standard payroll deductions: {format_payroll_amount(slip.deductions)}',
        f'NSSF: {format_payroll_amount(slip.nssf_deduction)}',
        f'SHIF: {format_payroll_amount(slip.shif_deduction)}',
        f'Housing levy: {format_payroll_amount(slip.housing_levy_deduction)}',
        f'Taxable pay: {format_payroll_amount(slip.taxable_pay)}',
        f'Tax charged: {format_payroll_amount(slip.tax_charged)}',
        f'Personal relief: {format_payroll_amount(slip.personal_relief)}',
        f'Other reliefs: {format_payroll_amount(slip.other_reliefs)}',
        f'PAYE: {format_payroll_amount(slip.paye_tax)}',
        f'Salary Advance / Early Cashout: {format_payroll_amount(slip.salary_advance)}',
        f'Net pay: {format_payroll_amount(slip.net_pay)}',
        f'Status: {slip.status}',
    ]
    document = fitz.open()
    page = document.new_page()
    page.insert_text((48, 58), lines[0], fontsize=16, fontname='helv')
    content = '\n'.join(lines[1:]).encode('latin-1', 'replace').decode('latin-1')
    page.insert_textbox(fitz.Rect(48, 86, 547, 780), content, fontsize=11, fontname='helv', lineheight=1.5)
    safe_period = re.sub(r'[^A-Za-z0-9_-]+', '-', slip.pay_period).strip('-') or 'pay-period'
    return payroll_pdf_response(document.tobytes(garbage=4, deflate=True), f'{safe_period}-payslip.pdf')


@portal_bp.get('/payroll/p9/<int:year>')
@jwt_required()
def download_own_p9(year):
    user = current_user()
    if not user or user.role not in EMPLOYEE_ROLES:
        return jsonify({'status': 'error', 'message': 'Employee payroll access is required.'}), 403
    pdf, error, status_code = _create_p9_pdf(user, year)
    if error:
        return jsonify({'status': 'error', 'message': error}), status_code
    return payroll_pdf_response(pdf, f'{year}-P9-annual-summary.pdf')


@portal_bp.get('/payroll/employees/<int:employee_id>/p9/<int:year>')
@jwt_required()
def download_employee_p9(employee_id, year):
    user = current_user()
    if not user or user.role not in ADMIN_ROLES:
        return jsonify({'status': 'error', 'message': 'HR or management access is required.'}), 403
    employee = db.session.get(UserAccount, employee_id)
    if not employee or employee.role not in EMPLOYEE_ROLES:
        return jsonify({'status': 'error', 'message': 'Employee was not found.'}), 404
    pdf, error, status_code = _create_p9_pdf(employee, year)
    if error:
        return jsonify({'status': 'error', 'message': error}), status_code
    safe_name = re.sub(r'[^A-Za-z0-9_-]+', '-', employee.display_name or employee.driver_name or 'employee')
    return payroll_pdf_response(pdf, f'{safe_name}-{year}-P9.pdf')


@portal_bp.post('/payroll')
@jwt_required()
def create_payroll_slip():
    admin = current_user()
    if not admin or admin.role not in ADMIN_ROLES:
        return jsonify({'status': 'error', 'message': 'Admin access is required.'}), 403
    data = request_data()
    try:
        employee_id = parse_integer(data.get('employee_id'))
        basic_pay = parse_amount(data.get('basic_pay', 0))
        allowances = parse_amount(data.get('allowances', 0))
        bonus = parse_amount(data.get('bonus', 0))
        deductions = parse_amount(data.get('deductions', 0))
        salary_advance = parse_amount(data.get('salary_advance', 0))
        auto_calculate = data.get('auto_calculate') is True
        housing_allowance = (
            parse_amount(data['housing_allowance'])
            if data.get('housing_allowance') not in (None, '')
            else (round(basic_pay * 0.15, 2) if auto_calculate else 0.0)
        )
        off_duty_days = parse_amount(data.get('off_duty_days', 0) or 0)
        off_duty_pay = (
            parse_amount(data['off_duty_pay'])
            if data.get('off_duty_pay') not in (None, '')
            else round(basic_pay / 26 * off_duty_days, 2)
        )
        statutory_fields = (
            'nssf_deduction', 'shif_deduction', 'housing_levy_deduction',
            'taxable_pay', 'tax_charged', 'personal_relief', 'other_reliefs', 'paye_tax',
        )
        statutory_amounts = {
            field: parse_amount(data[field]) if data.get(field) not in (None, '') else None
            for field in statutory_fields
        }
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Enter valid employee and payroll amounts.'}), 400
    period = data.get('pay_period', '')
    if not isinstance(period, str):
        return jsonify({'status': 'error', 'message': 'Enter a valid payroll period.'}), 400
    period = period.strip()
    employee = db.session.get(UserAccount, employee_id)
    if not employee or employee.role not in EMPLOYEE_ROLES:
        return jsonify({'status': 'error', 'message': 'Choose an existing employee account.'}), 400
    if not period or len(period) > 20:
        return jsonify({'status': 'error', 'message': 'Enter a payroll period of 20 characters or fewer.'}), 400
    all_amounts = [basic_pay, allowances, bonus, deductions, salary_advance, housing_allowance, off_duty_days, off_duty_pay, *(
        amount for amount in statutory_amounts.values() if amount is not None
    )]
    if min(all_amounts) < 0 or max(all_amounts) > 100_000_000:
        return jsonify({'status': 'error', 'message': 'Payroll amounts must be non-negative and within the supported limit.'}), 400
    if PayrollSlip.query.filter_by(employee_id=employee.id, pay_period=period).first():
        return jsonify({'status': 'error', 'message': 'A payslip already exists for this employee and period.'}), 409

    gross_pay = round(basic_pay + housing_allowance + off_duty_pay + allowances + bonus, 2)
    statutory_total = 0.0
    if auto_calculate:
        from backend.routes.hr import calculate_statutory_deductions
        computed = calculate_statutory_deductions(gross_pay)
        statutory_amounts.update({
            'nssf_deduction': computed['nssf'],
            'shif_deduction': computed['shif'],
            'housing_levy_deduction': computed['housing_levy'],
            'taxable_pay': computed['taxable_pay'],
            'tax_charged': computed['tax_charged'],
            'personal_relief': computed['personal_relief'],
            'other_reliefs': 0.0,
            'paye_tax': computed['paye'],
        })
        statutory_total = computed['total_deductions']
    if statutory_total + deductions + salary_advance > gross_pay:
        return jsonify({'status': 'error', 'message': 'Deductions cannot exceed gross pay.'}), 400
    slip = PayrollSlip()
    slip.employee_id = employee.id
    slip.pay_period = period
    slip.basic_pay = basic_pay
    slip.allowances = allowances
    slip.bonus = bonus
    slip.deductions = deductions
    slip.salary_advance = salary_advance
    slip.housing_allowance = housing_allowance
    slip.off_duty_days = off_duty_days
    slip.off_duty_pay = off_duty_pay
    for field, amount in statutory_amounts.items():
        setattr(slip, field, amount)
    slip.gross_pay = gross_pay
    slip.net_pay = round(gross_pay - statutory_total - deductions - salary_advance, 2)
    slip.status = 'PENDING_APPROVAL'
    slip.created_by_id = admin.id
    db.session.add(slip)
    db.session.commit()
    return jsonify({'status': 'success', 'slip': slip.to_dict()}), 201


@portal_bp.patch('/payroll/<int:slip_id>/approve')
@jwt_required()
def approve_payroll_slip(slip_id):
    admin = current_user()
    if not admin or admin.role not in ADMIN_ROLES:
        return jsonify({'status': 'error', 'message': 'Admin access is required.'}), 403
    slip = db.session.get(PayrollSlip, slip_id)
    if not slip:
        return jsonify({'status': 'error', 'message': 'Payslip not found.'}), 404
    if slip.status != 'PENDING_APPROVAL':
        return jsonify({'status': 'error', 'message': 'Only pending payslips can be approved.'}), 409
    from backend.routes.workforce import verify_immutable_storage_ready
    try:
        verify_immutable_storage_ready()
    except RuntimeError as error:
        return jsonify({'status': 'error', 'message': str(error)}), 503
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
    if slip.signed_pdf_sha256:
        return jsonify({'status': 'error', 'message': 'This paystub already has an immutable signed document.'}), 409
    data = request_data()
    if (
        data.get('receipt_confirmed') is not True
        or data.get('paystub_confirmed') is not True
        or slip.salary_advance > 0 and data.get('advance_confirmed') is not True
    ):
        return jsonify({
            'status': 'error',
            'message': 'Confirm receipt, paystub review, and the separate salary advance notice where applicable.',
        }), 400
    from backend.routes.workforce import (
        build_signed_pdf,
        parse_signature,
        parse_signature_metadata,
        upload_immutable_pdf,
    )
    try:
        signature = parse_signature(data)
        device_id, latitude, longitude = parse_signature_metadata(data)
    except ValueError as error:
        return jsonify({'status': 'error', 'message': str(error)}), 400

    signed_at = datetime.now(timezone.utc)
    employee_name = user.display_name or user.driver_name or user.email
    acknowledgement_body = (
        f"Employee: {employee_name}\nPay period: {slip.pay_period}\n"
        f"Gross salary: KES {slip.gross_pay:,.2f}\n"
        f"Standard payroll deductions: KES {slip.deductions:,.2f}\n"
        f"NSSF: {format_payroll_amount(slip.nssf_deduction)}\n"
        f"SHIF: {format_payroll_amount(slip.shif_deduction)}\n"
        f"Housing levy: {format_payroll_amount(slip.housing_levy_deduction)}\n"
        f"Taxable pay: {format_payroll_amount(slip.taxable_pay)}\n"
        f"Tax charged: {format_payroll_amount(slip.tax_charged)}\n"
        f"Personal relief: {format_payroll_amount(slip.personal_relief)}\n"
        f"Other reliefs: {format_payroll_amount(slip.other_reliefs)}\n"
        f"PAYE: {format_payroll_amount(slip.paye_tax)}\n"
        f"Salary Advance / Early Cashout: KES {slip.salary_advance:,.2f}\n"
        f"Net pay: KES {slip.net_pay:,.2f}\n\n"
        "I confirm receipt of this paystub and acknowledge the listed earnings, "
        "standard payroll deductions, and net pay. "
    )
    if slip.salary_advance > 0:
        acknowledgement_body += (
            f"I separately acknowledge and consent that KES {slip.salary_advance:,.2f} "
            "is a Salary Advance / Early Cashout and is to be offset against final trip "
            "settlements as permitted by applicable law and the applicable written agreement. "
            "This records receipt and consent and does not waive rights under applicable law."
        )
    else:
        acknowledgement_body += "No salary advance or early cashout is listed on this paystub."
    ip_address = request.remote_addr
    pdf = build_signed_pdf(
        f'Paystub acknowledgement · {slip.pay_period}',
        acknowledgement_body,
        signature,
        signed_at,
        device_id,
        ip_address,
        latitude,
        longitude,
    )
    try:
        object_key, version_id, digest = upload_immutable_pdf(pdf)
    except RuntimeError as error:
        return jsonify({'status': 'error', 'message': str(error)}), 503
    slip.receipt_signed_at = signed_at
    slip.paystub_signed_at = signed_at
    if slip.salary_advance > 0:
        slip.advance_signed_at = signed_at
    slip.signed_pdf_object_key = object_key
    slip.signed_pdf_version_id = version_id
    slip.signed_pdf_sha256 = digest
    slip.signature_device_id = device_id
    slip.signature_ip_address = ip_address
    slip.signature_latitude = latitude
    slip.signature_longitude = longitude
    db.session.commit()
    return jsonify({
        'status': 'success',
        'slip': slip.to_dict(),
        'signed_at': signed_at.isoformat(),
        'sha256': digest,
    }), 200


@portal_bp.get('/payroll/<int:slip_id>/signed-document')
@jwt_required()
def download_signed_payroll_document(slip_id):
    user = current_user()
    slip = db.session.get(PayrollSlip, slip_id)
    if not user or not slip or (
        slip.employee_id != user.id and user.role not in ADMIN_ROLES
    ):
        return jsonify({'status': 'error', 'message': 'Signed paystub was not found for this account.'}), 404
    if not slip.signed_pdf_object_key or not slip.signed_pdf_version_id or not slip.signed_pdf_sha256:
        return jsonify({'status': 'error', 'message': 'This paystub does not have a verified signed PDF.'}), 404
    from backend.routes.workforce import download_verified_pdf
    try:
        contents = download_verified_pdf(
            slip.signed_pdf_object_key,
            slip.signed_pdf_version_id,
            slip.signed_pdf_sha256,
        )
    except RuntimeError as error:
        return jsonify({'status': 'error', 'message': str(error)}), 500
    return send_file(
        io.BytesIO(contents),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'{slip.pay_period}-signed-paystub.pdf',
    )


@portal_bp.get('/mechanic-reports')
@jwt_required()
def list_mechanic_reports():
    user = current_user()
    if not user or user.role not in ({'mechanic'} | ADMIN_ROLES):
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
    data = request_data()
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
    report = MechanicIncidentReport()
    report.reference = reference
    report.mechanic_id = user.id
    report.parts_used = parts_used.strip() or None
    report.vehicle_registration = values['vehicle_registration']
    report.incident_date = values['incident_date']
    report.location = values['location']
    report.severity = values['severity']
    report.symptoms = values['symptoms']
    report.findings = values['findings']
    report.action_taken = values['action_taken']
    db.session.add(report)
    db.session.commit()
    return jsonify({'status': 'success', 'report': report.to_dict()}), 201
