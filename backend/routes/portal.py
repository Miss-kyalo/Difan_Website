import calendar
import io
import math
import os
import uuid
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request, send_file
from flask_jwt_extended import get_jwt_identity, jwt_required
from PIL import Image, UnidentifiedImageError
from sqlalchemy.exc import SQLAlchemyError

from backend.models.payroll import db
from backend.routes.auth import ADMIN_ROLES, HR_ROLES, UserAccount
from backend.routes.shipments import Shipment

portal_bp = Blueprint('portal', __name__, url_prefix='/api/portal')
CONTAINER_SIZES = {'20ft', '40ft'}
EMPLOYEE_ROLES = ADMIN_ROLES | {'hr', 'driver', 'mechanic', 'accountant'}
FINANCE_VIEW_ROLES = ADMIN_ROLES | {'accountant', 'client'}
FINANCE_UPDATE_ROLES = ADMIN_ROLES | {'accountant'}
CLIENT_COMMUNICATION_ROLES = ADMIN_ROLES | HR_ROLES | {'accountant'}
MESSAGE_CONTACT_ROLES = {'admin', 'hr', 'accountant'}
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


class AnonymousReport(db.Model):
    __tablename__ = 'anonymous_reports'

    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(32), unique=True, nullable=False, index=True)
    description = db.Column(db.String(5000), nullable=False, default='')
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    attachments = db.relationship('AnonymousReportAttachment', backref='report', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'reference': self.reference,
            'description': self.description,
            'created_at': self.created_at.isoformat(),
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
    }), 201


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
        contact_rows = []

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
    if not user or user.account_status != 'active' or user.role != 'client':
        return jsonify({'status': 'error', 'message': 'Only client accounts can start a staff conversation.'}), 403

    data = request_data()
    try:
        staff_user_id = parse_integer(data.get('staff_user_id'))
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Choose an Admin, HR, or Accounts contact.'}), 400
    staff = db.session.get(UserAccount, staff_user_id)
    if not staff or staff.account_status != 'active' or staff.role not in MESSAGE_CONTACT_ROLES:
        return jsonify({'status': 'error', 'message': 'Messages may only be sent to active Admin, HR, or Accounts contacts.'}), 400

    conversation = ClientConversation.query.filter_by(
        client_user_id=user.id,
        staff_user_id=staff.id,
    ).first()
    if conversation is None:
        conversation = ClientConversation()
        conversation.client_user_id = user.id
        conversation.staff_user_id = staff.id
        conversation.updated_at = datetime.now(timezone.utc)
        db.session.add(conversation)
        db.session.commit()

    return jsonify({
        'status': 'success',
        'conversation': {
            'id': conversation.id,
            'peer_name': staff.display_name or staff.email,
            'peer_role': staff.role,
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
    query = PayrollSlip.query
    if user.role not in ADMIN_ROLES:
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
    if not admin or admin.role not in ADMIN_ROLES:
        return jsonify({'status': 'error', 'message': 'Admin access is required.'}), 403
    data = request_data()
    try:
        employee_id = parse_integer(data.get('employee_id'))
        basic_pay = parse_amount(data.get('basic_pay', 0))
        allowances = parse_amount(data.get('allowances', 0))
        bonus = parse_amount(data.get('bonus', 0))
        deductions = parse_amount(data.get('deductions', 0))
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
    if min(basic_pay, allowances, bonus, deductions) < 0 or max(basic_pay, allowances, bonus, deductions) > 100_000_000:
        return jsonify({'status': 'error', 'message': 'Payroll amounts must be non-negative and within the supported limit.'}), 400
    if PayrollSlip.query.filter_by(employee_id=employee.id, pay_period=period).first():
        return jsonify({'status': 'error', 'message': 'A payslip already exists for this employee and period.'}), 409

    gross_pay = round(basic_pay + allowances + bonus, 2)
    if deductions > gross_pay:
        return jsonify({'status': 'error', 'message': 'Deductions cannot exceed gross pay.'}), 400
    slip = PayrollSlip()
    slip.employee_id = employee.id
    slip.pay_period = period
    slip.basic_pay = basic_pay
    slip.allowances = allowances
    slip.bonus = bonus
    slip.deductions = deductions
    slip.gross_pay = gross_pay
    slip.net_pay = round(gross_pay - deductions, 2)
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
    data = request_data()
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
