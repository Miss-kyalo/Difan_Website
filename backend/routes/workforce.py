import base64
import binascii
import hashlib
import hmac
import io
import re
import uuid
from datetime import datetime, timedelta, timezone

import pymupdf as fitz
from flask import Blueprint, current_app, jsonify, request, send_file
from flask_jwt_extended import get_jwt_identity, jwt_required
from PIL import Image, UnidentifiedImageError
from sqlalchemy import and_
from werkzeug.utils import secure_filename

from backend.models.payroll import db
from backend.routes.auth import EMPLOYEE_ROLES, HR_ROLES, UserAccount
from backend.routes.shipments import Shipment, ShipmentProofOfDelivery, shipment_visible_to

workforce_bp = Blueprint('workforce', __name__, url_prefix='/api/portal/workforce')
DRIVER_STATUSES = {'ACTIVE', 'ON_LEAVE', 'SUSPENDED', 'OFF_DUTY'}
LEAVE_TYPES = {'SICK', 'VACATION'}
CASE_TYPES = {'WRITTEN_REPRIMAND', 'MINOR_INFRACTION', 'VERBAL_WARNING'}
CASE_SEVERITIES = {'MINOR_LATE_ARRIVAL', 'CARGO_MISMANAGEMENT', 'UNEXCUSED_ABSENCE', 'SAFETY_COMPLIANCE'}
SEVERITY_POINTS = {
    'MINOR_LATE_ARRIVAL': 2,
    'CARGO_MISMANAGEMENT': 5,
    'UNEXCUSED_ABSENCE': 10,
    'SAFETY_COMPLIANCE': 20,
}
EVIDENCE_MAX_BYTES = 5 * 1024 * 1024
EVIDENCE_MIME_TYPES = {'application/pdf', 'image/jpeg', 'image/png', 'image/webp'}
SIGNATURE_MAX_BYTES = 512 * 1024
NOTICE_TYPES = {'TERMS_UPDATE', 'CONSENT_AGREEMENT'}
DISPUTE_HOURS = 72
SCORE_WINDOW_DAYS = 90


class WorkforceNotice(db.Model):
    __tablename__ = 'workforce_notices'

    id = db.Column(db.Integer, primary_key=True)
    notice_type = db.Column(db.String(32), nullable=False)
    title = db.Column(db.String(160), nullable=False)
    body = db.Column(db.String(5000), nullable=False)
    version = db.Column(db.String(40), nullable=False)
    published = db.Column(db.Boolean, nullable=False, default=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    created_by = db.relationship('UserAccount', foreign_keys=[created_by_id])
    acknowledgements = db.relationship(
        'WorkforceNoticeAcknowledgement', backref='notice', lazy=True, cascade='all, delete-orphan',
    )

    def to_dict(self):
        return {
            'id': self.id,
            'notice_type': self.notice_type,
            'title': self.title,
            'body': self.body,
            'version': self.version,
            'published': self.published,
            'created_at': self.created_at.isoformat(),
        }


class WorkforceNoticeAcknowledgement(db.Model):
    __tablename__ = 'workforce_notice_acknowledgements'
    __table_args__ = (
        db.UniqueConstraint('notice_id', 'employee_id', name='uq_workforce_notice_employee'),
    )

    id = db.Column(db.Integer, primary_key=True)
    notice_id = db.Column(db.Integer, db.ForeignKey('workforce_notices.id'), nullable=False, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False, index=True)
    signed_at = db.Column(db.DateTime(timezone=True), nullable=False)
    device_id = db.Column(db.String(120), nullable=False)
    ip_address = db.Column(db.String(64), nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    pdf_object_key = db.Column(db.String(512), nullable=False)
    pdf_version_id = db.Column(db.String(256), nullable=False)
    pdf_sha256 = db.Column(db.String(64), nullable=False)
    employee = db.relationship('UserAccount', foreign_keys=[employee_id])


class WorkforceCase(db.Model):
    __tablename__ = 'workforce_cases'

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False)
    case_type = db.Column(db.String(32), nullable=False)
    severity = db.Column(db.String(32), nullable=False)
    details = db.Column(db.String(3000), nullable=False)
    status = db.Column(db.String(24), nullable=False, default='DISPUTE_OPEN')
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    dispute_deadline_at = db.Column(db.DateTime(timezone=True), nullable=False)
    resolved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    resolved_by_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=True)
    resolution_note = db.Column(db.String(2000), nullable=True)
    employee = db.relationship('UserAccount', foreign_keys=[employee_id])
    created_by = db.relationship('UserAccount', foreign_keys=[created_by_id])
    evidence = db.relationship(
        'WorkforceCaseEvidence', backref='case', lazy=True, cascade='all, delete-orphan',
    )
    rebuttals = db.relationship(
        'WorkforceCaseRebuttal', backref='case', lazy=True, cascade='all, delete-orphan',
    )

    def to_dict(self):
        return {
            'id': self.id,
            'employee_id': self.employee_id,
            'employee_name': self.employee.display_name or self.employee.driver_name or self.employee.email,
            'case_type': self.case_type,
            'severity': self.severity,
            'severity_points': SEVERITY_POINTS[self.severity],
            'details': self.details,
            'status': effective_case_status(self),
            'created_at': self.created_at.isoformat(),
            'dispute_deadline_at': self.dispute_deadline_at.isoformat(),
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'resolution_note': self.resolution_note,
            'evidence': [
                evidence.to_dict()
                for evidence in self.evidence
                if evidence.uploaded_by_id == self.created_by_id
            ],
            'rebuttals': [rebuttal.to_dict() for rebuttal in self.rebuttals],
        }


class WorkforceCaseEvidence(db.Model):
    __tablename__ = 'workforce_case_evidence'

    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey('workforce_cases.id'), nullable=False, index=True)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False)
    filename = db.Column(db.String(180), nullable=False)
    mime_type = db.Column(db.String(80), nullable=False)
    contents = db.Column(db.LargeBinary, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    uploaded_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'filename': self.filename,
            'mime_type': self.mime_type,
            'size_bytes': len(self.contents),
            'sha256': self.sha256,
            'uploaded_at': self.uploaded_at.isoformat(),
            'download_url': f'{workforce_bp.url_prefix}/cases/{self.case_id}/evidence/{self.id}',
        }


class WorkforceCaseRebuttal(db.Model):
    __tablename__ = 'workforce_case_rebuttals'

    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey('workforce_cases.id'), nullable=False, unique=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False)
    details = db.Column(db.String(3000), nullable=False)
    submitted_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    employee = db.relationship('UserAccount', foreign_keys=[employee_id])
    def to_dict(self):
        return {
            'id': self.id,
            'details': self.details,
            'submitted_at': self.submitted_at.isoformat(),
            'evidence': [
                evidence.to_dict()
                for evidence in WorkforceCaseEvidence.query.filter_by(case_id=self.case_id).all()
                if evidence.uploaded_by_id == self.employee_id
            ],
        }


class DriverRating(db.Model):
    __tablename__ = 'driver_ratings'

    id = db.Column(db.Integer, primary_key=True)
    shipment_tracking_number = db.Column(
        db.String(40), db.ForeignKey('shipments.tracking_number'), nullable=False, unique=True, index=True,
    )
    driver_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False)
    stars = db.Column(db.Integer, nullable=False)
    feedback = db.Column(db.String(1000), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    driver = db.relationship('UserAccount', foreign_keys=[driver_id])
    client = db.relationship('UserAccount', foreign_keys=[client_id])
    shipment = db.relationship('Shipment')


class ClientRating(db.Model):
    __tablename__ = 'client_ratings'

    id = db.Column(db.Integer, primary_key=True)
    shipment_tracking_number = db.Column(
        db.String(40), db.ForeignKey('shipments.tracking_number'), nullable=False, unique=True, index=True,
    )
    driver_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False, index=True)
    loading_speed_stars = db.Column(db.Integer, nullable=False)
    facility_friendliness_stars = db.Column(db.Integer, nullable=False)
    feedback = db.Column(db.String(1000), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    driver = db.relationship('UserAccount', foreign_keys=[driver_id])
    client = db.relationship('UserAccount', foreign_keys=[client_id])
    shipment = db.relationship('Shipment')

    @property
    def score(self):
        return (self.loading_speed_stars + self.facility_friendliness_stars) / 2


class SafetyEmergencyReport(db.Model):
    __tablename__ = 'safety_emergency_reports'

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False, index=True)
    report_type = db.Column(db.String(24), nullable=False)
    vehicle_registration = db.Column(db.String(20), nullable=True)
    location = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(2000), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    employee = db.relationship('UserAccount', foreign_keys=[employee_id])


def parse_signature(data):
    value = data.get('signature_png')
    if not isinstance(value, str) or not value.startswith('data:image/png;base64,'):
        raise ValueError('Draw your signature before submitting the acknowledgement.')
    try:
        content = base64.b64decode(value.split(',', 1)[1], validate=True)
        if not content or len(content) > SIGNATURE_MAX_BYTES:
            raise ValueError
        with Image.open(io.BytesIO(content)) as image:
            if image.format != 'PNG' or image.width > 1200 or image.height > 600:
                raise ValueError
            image.load()
            grayscale = image.convert('L')
            if grayscale.getextrema()[0] > 245:
                raise ValueError
            normalized = io.BytesIO()
            image.convert('RGB').save(normalized, format='PNG', optimize=True)
            return normalized.getvalue()
    except (binascii.Error, OSError, UnidentifiedImageError, ValueError) as error:
        raise ValueError('The signature is blank or not a supported PNG image.') from error


def parse_signature_metadata(data):
    device_id = data.get('device_id')
    if not isinstance(device_id, str) or not device_id.strip() or len(device_id.strip()) > 120:
        raise ValueError('A browser device ID is required to sign this acknowledgement.')
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    if (latitude is None) != (longitude is None):
        raise ValueError('Both GPS coordinates must be provided together.')
    if latitude is not None:
        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except (TypeError, ValueError) as error:
            raise ValueError('GPS coordinates must be valid numbers.') from error
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError('GPS coordinates are outside the supported range.')
    return device_id.strip(), latitude, longitude


def build_signed_pdf(title, body, signature_png, signed_at, device_id, ip_address, latitude, longitude):
    document = fitz.open()
    font_size = 11
    max_width = 499
    def wrap_text(value, size):
        wrapped = []
        for paragraph in value.splitlines() or ['']:
            words = paragraph.split()
            if not words:
                wrapped.append('')
                continue
            line = ''
            for word in words:
                candidate = f'{line} {word}'.strip()
                if fitz.get_text_length(candidate, fontname='helv', fontsize=size) <= max_width:
                    line = candidate
                    continue
                if line:
                    wrapped.append(line)
                line = ''
                for character in word:
                    candidate = f'{line}{character}'
                    if fitz.get_text_length(candidate, fontname='helv', fontsize=size) > max_width and line:
                        wrapped.append(line)
                        line = character
                    else:
                        line = candidate
            if line:
                wrapped.append(line)
        return wrapped

    title_lines = wrap_text(title, 18)
    body_lines = wrap_text(body, font_size)
    chunks = [body_lines[index:index + 39] for index in range(0, len(body_lines), 39)]
    if not chunks:
        chunks = [[]]
    last_page = None
    next_y = 120
    for page_index, lines in enumerate(chunks):
        last_page = document.new_page(width=595, height=842)
        if page_index == 0:
            title_y = 58
            for line in title_lines:
                last_page.insert_text((48, title_y), line, fontsize=18, fontname='helv')
                title_y += 22
            next_y = max(120, title_y + 16)
        else:
            last_page.insert_text((48, 58), 'Acknowledgement (continued)', fontsize=13, fontname='helv')
            next_y = 88
        for line in lines:
            last_page.insert_text((48, next_y), line, fontsize=font_size, fontname='helv')
            next_y += 15

    if next_y + 190 > 790:
        last_page = document.new_page(width=595, height=842)
        next_y = 80
        last_page.insert_text((48, 58), 'Signature and audit record', fontsize=15, fontname='helv')
    last_page.insert_text((48, next_y + 16), 'Electronic signature', fontsize=10, fontname='helv')
    last_page.insert_image(
        fitz.Rect(48, next_y + 28, 330, next_y + 108),
        stream=signature_png,
        keep_proportion=True,
    )
    metadata = (
        f'Signed at (UTC): {signed_at.isoformat()}\n'
        f'Browser device ID: {device_id}\n'
        f'IP address: {ip_address or "Unavailable"}\n'
        f'GPS: {latitude}, {longitude}' if latitude is not None
        else f'Signed at (UTC): {signed_at.isoformat()}\n'
        f'Browser device ID: {device_id}\n'
        f'IP address: {ip_address or "Unavailable"}\nGPS: unavailable'
    )
    last_page.insert_textbox(
        fitz.Rect(48, next_y + 118, 547, min(next_y + 220, 810)),
        metadata,
        fontsize=9,
        fontname='helv',
    )
    return document.tobytes(garbage=4, deflate=True)


def get_immutable_storage():
    bucket = current_app.config.get('PAYROLL_DOCUMENTS_BUCKET')
    kms_key = current_app.config.get('PAYROLL_DOCUMENT_KMS_KEY_ID')
    region = current_app.config.get('AWS_REGION')
    retention_days = current_app.config.get('PAYROLL_DOCUMENT_RETENTION_DAYS')
    if not bucket or not kms_key or not region:
        raise RuntimeError(
            'Signed-document storage is not configured. Set the AWS bucket, region, and KMS key.'
        )
    try:
        retention_days = int(retention_days)
    except (TypeError, ValueError) as error:
        raise RuntimeError('Set PAYROLL_DOCUMENT_RETENTION_DAYS to the legally approved retention period.') from error
    if not 1 <= retention_days <= 36500:
        raise RuntimeError('PAYROLL_DOCUMENT_RETENTION_DAYS must be between 1 and 36,500.')

    import boto3
    from botocore.exceptions import BotoCoreError

    try:
        client = boto3.client('s3', region_name=region)
        lock_configuration = client.get_object_lock_configuration(Bucket=bucket)
        versioning = client.get_bucket_versioning(Bucket=bucket)
    except BotoCoreError as error:
        current_app.logger.error('Unable to verify immutable S3 payroll storage: %s', error)
        raise RuntimeError('The signed-document bucket could not be verified for Object Lock.') from error
    if lock_configuration.get('ObjectLockConfiguration', {}).get('ObjectLockEnabled') != 'Enabled':
        raise RuntimeError('The configured S3 bucket must have Object Lock enabled.')
    if versioning.get('Status') != 'Enabled':
        raise RuntimeError('The configured S3 bucket must have versioning enabled.')
    return client, bucket, kms_key, retention_days


def verify_immutable_storage_ready():
    if current_app.config.get('TESTING'):
        return
    get_immutable_storage()


def upload_immutable_pdf(pdf_bytes):
    client, bucket, kms_key, retention_days = get_immutable_storage()
    from botocore.exceptions import BotoCoreError

    digest = hashlib.sha256(pdf_bytes).hexdigest()
    object_key = f'payroll-signed/{uuid.uuid4()}.pdf'
    retain_until = datetime.now(timezone.utc) + timedelta(days=retention_days)
    try:
        response = client.put_object(
            Bucket=bucket,
            Key=object_key,
            Body=pdf_bytes,
            ContentType='application/pdf',
            Metadata={'sha256': digest},
            ServerSideEncryption='aws:kms',
            SSEKMSKeyId=kms_key,
            ObjectLockMode='COMPLIANCE',
            ObjectLockRetainUntilDate=retain_until,
        )
    except BotoCoreError as error:
        current_app.logger.error('Unable to store immutable signed payroll PDF: %s', error)
        raise RuntimeError('The signed PDF could not be saved to immutable encrypted storage.') from error
    version_id = response.get('VersionId')
    if not version_id:
        raise RuntimeError('S3 did not return an immutable object version for the signed PDF.')
    return object_key, version_id, digest


def download_verified_pdf(object_key, version_id, expected_digest):
    import boto3
    from botocore.exceptions import BotoCoreError

    bucket = current_app.config.get('PAYROLL_DOCUMENTS_BUCKET')
    region = current_app.config.get('AWS_REGION')
    if not bucket or not region:
        raise RuntimeError('Signed-document storage is not configured.')
    try:
        response = boto3.client('s3', region_name=region).get_object(
            Bucket=bucket, Key=object_key, VersionId=version_id,
        )
        contents = response['Body'].read()
    except BotoCoreError as error:
        current_app.logger.error('Unable to retrieve signed payroll PDF: %s', error)
        raise RuntimeError('The signed PDF could not be retrieved from immutable storage.') from error
    actual_digest = hashlib.sha256(contents).hexdigest()
    if not hmac.compare_digest(actual_digest, expected_digest):
        current_app.logger.error('SHA-256 validation failed for signed PDF object %s', object_key)
        raise RuntimeError('The signed PDF failed SHA-256 integrity verification.')
    return contents


def current_user():
    try:
        return db.session.get(UserAccount, int(get_jwt_identity()))
    except (TypeError, ValueError):
        return None


def effective_case_status(case):
    if case.status == 'UNDER_REVIEW' and case.rebuttals:
        return 'DISPUTED'
    if case.status != 'DISPUTE_OPEN':
        return case.status
    now = datetime.now(timezone.utc)
    deadline = case.dispute_deadline_at
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    if case.rebuttals or now < deadline:
        return 'DISPUTED' if case.rebuttals else 'DISPUTE_OPEN'
    return 'FINALIZED'


def case_penalty(case, now):
    status = effective_case_status(case)
    if status not in {'FINALIZED', 'UPHELD'}:
        return 0.0
    created = case.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - created).total_seconds() / 86400)
    return SEVERITY_POINTS[case.severity] * max(0.0, 1 - age_days / SCORE_WINDOW_DAYS)


def driver_score(driver, performance_since=None):
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=SCORE_WINDOW_DAYS)).replace(tzinfo=None)
    metric_since = performance_since or since
    if metric_since.tzinfo is not None:
        metric_since = metric_since.astimezone(timezone.utc).replace(tzinfo=None)
    cases = WorkforceCase.query.filter(
        WorkforceCase.employee_id == driver.id,
        WorkforceCase.created_at >= since,
    ).all()
    rating_rows = DriverRating.query.filter(
        DriverRating.driver_id == driver.id,
        DriverRating.created_at >= metric_since,
    ).all()
    shipments = Shipment.query.filter(
        Shipment.assigned_driver_id == driver.id,
        Shipment.status == 'DELIVERED',
        Shipment.arrived_at.is_not(None),
        Shipment.arrived_at >= metric_since,
    ).all()
    signed_shipment_ids = {
        tracking_number for (tracking_number,) in db.session.query(
            ShipmentProofOfDelivery.shipment_tracking_number,
        ).filter(
            ShipmentProofOfDelivery.shipment_tracking_number.in_(
                [shipment.tracking_number for shipment in shipments],
            ),
        ).all()
    }
    shipments = [shipment for shipment in shipments if shipment.tracking_number in signed_shipment_ids]

    penalties = [case_penalty(case, now) for case in cases]
    infraction_penalty = min(100.0, sum(penalties))
    safety_penalty = sum(
        case_penalty(case, now)
        for case in cases if case.severity == 'SAFETY_COMPLIANCE'
    )
    safety_score = max(0.0, 100.0 - safety_penalty)
    customer_rating = (
        sum(rating.stars for rating in rating_rows) / len(rating_rows) * 20
        if rating_rows else 100.0
    )
    dated_shipments = [shipment for shipment in shipments if shipment.delivery_due_at is not None]
    on_time_score = (
        sum(shipment.arrived_at <= shipment.delivery_due_at for shipment in dated_shipments)
        / len(dated_shipments) * 100
        if dated_shipments else 100.0
    )
    score = max(
        0.0,
        0.35 * safety_score
        + 0.30 * customer_rating
        + 0.25 * on_time_score
        - 0.10 * infraction_penalty,
    )
    return {
        'score': round(score, 2),
        'safety_score': round(safety_score, 2),
        'customer_rating_score': round(customer_rating, 2),
        'customer_rating_average': round(customer_rating / 20, 2),
        'customer_rating_count': len(rating_rows),
        'customer_feedback': [
            {
                'tracking_number': rating.shipment_tracking_number,
                'stars': rating.stars,
                'feedback': rating.feedback,
                'created_at': rating.created_at.isoformat(),
            }
            for rating in sorted(rating_rows, key=lambda item: item.created_at, reverse=True)[:25]
        ],
        'on_time_score': round(on_time_score, 2),
        'on_time_deliveries': sum(shipment.arrived_at <= shipment.delivery_due_at for shipment in dated_shipments),
        'scored_deliveries': len(dated_shipments),
        'hr_infraction_penalty': round(infraction_penalty, 2),
        'window_days': SCORE_WINDOW_DAYS,
    }


def employee_acknowledgement_status(user):
    from backend.routes.portal import PayrollSlip

    if not user or user.role not in EMPLOYEE_ROLES:
        return {'must_acknowledge': False, 'pending_slips': [], 'pending_notices': []}
    pending_slips = PayrollSlip.query.filter(
        PayrollSlip.employee_id == user.id,
        PayrollSlip.status == 'APPROVED',
        db.or_(
            PayrollSlip.receipt_signed_at.is_(None),
            PayrollSlip.paystub_signed_at.is_(None),
            PayrollSlip.signed_pdf_sha256.is_(None),
            and_(
                PayrollSlip.salary_advance > 0,
                PayrollSlip.advance_signed_at.is_(None),
            ),
        ),
    ).order_by(PayrollSlip.pay_period).all()
    acknowledged_ids = db.select(
        WorkforceNoticeAcknowledgement.notice_id,
    ).filter_by(employee_id=user.id)
    pending_notices = WorkforceNotice.query.filter(
        WorkforceNotice.published.is_(True),
        ~WorkforceNotice.id.in_(acknowledged_ids),
    ).order_by(WorkforceNotice.created_at).all()
    return {
        'must_acknowledge': bool(pending_slips or pending_notices),
        'pending_slips': pending_slips,
        'pending_notices': pending_notices,
    }


def _manager():
    user = current_user()
    return user if user and user.account_status == 'active' and user.role in HR_ROLES else None


def _accept_evidence(case_id, uploader_id, uploads):
    saved = []
    for upload in uploads:
        if not upload or not upload.filename:
            continue
        contents = upload.read(EVIDENCE_MAX_BYTES + 1)
        if not contents or len(contents) > EVIDENCE_MAX_BYTES:
            raise ValueError('Each evidence file must be between 1 byte and 5 MB.')
        mime_type = upload.mimetype or 'application/octet-stream'
        if mime_type not in EVIDENCE_MIME_TYPES:
            raise ValueError('Evidence files must be PDF, JPEG, PNG, or WEBP.')
        if mime_type == 'application/pdf' and not contents.startswith(b'%PDF-'):
            raise ValueError('A PDF evidence file has invalid contents.')
        if mime_type == 'image/png' and not contents.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('A PNG evidence file has invalid contents.')
        if mime_type == 'image/jpeg' and not contents.startswith(b'\xff\xd8\xff'):
            raise ValueError('A JPEG evidence file has invalid contents.')
        if mime_type == 'image/webp' and (len(contents) < 12 or contents[8:12] != b'WEBP'):
            raise ValueError('A WEBP evidence file has invalid contents.')
        if mime_type.startswith('image/'):
            expected_format = {
                'image/jpeg': 'JPEG',
                'image/png': 'PNG',
                'image/webp': 'WEBP',
            }[mime_type]
            try:
                with Image.open(io.BytesIO(contents)) as image:
                    if image.format != expected_format or image.width * image.height > 40_000_000:
                        raise ValueError('An image evidence file has invalid dimensions or format.')
                    image.verify()
            except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as error:
                raise ValueError('An image evidence file is invalid or exceeds the dimension limit.') from error
        filename = secure_filename(upload.filename)[:180] or 'evidence'
        saved.append(WorkforceCaseEvidence(
            case_id=case_id,
            uploaded_by_id=uploader_id,
            filename=filename or 'evidence',
            mime_type=mime_type,
            contents=contents,
            sha256=hashlib.sha256(contents).hexdigest(),
        ))
    if len(saved) > 5:
        raise ValueError('Attach no more than five evidence files.')
    return saved


def install_workforce_lockout(app):
    @app.before_request
    def enforce_workforce_acknowledgement_lockout():
        if request.method == 'OPTIONS':
            return None
        from flask_jwt_extended import verify_jwt_in_request

        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        if identity is None:
            return None
        try:
            user = db.session.get(UserAccount, int(identity))
        except (TypeError, ValueError):
            return None
        if not user or user.role not in EMPLOYEE_ROLES:
            return None
        if not employee_acknowledgement_status(user)['must_acknowledge']:
            return None

        path = request.path
        allowed = (
            path == '/api/auth/me'
            or path == '/api/auth/change-password'
            or path == f'{workforce_bp.url_prefix}/pending'
            or path == f'{workforce_bp.url_prefix}/cases'
            and request.method == 'GET'
            or bool(re.fullmatch(rf'{re.escape(workforce_bp.url_prefix)}/cases/\d+/dispute', path))
            and request.method == 'POST'
            or bool(re.fullmatch(rf'{re.escape(workforce_bp.url_prefix)}/cases/\d+/evidence/\d+', path))
            and request.method == 'GET'
            or path.startswith('/api/portal/payroll')
            and (request.method == 'GET' or path.endswith('/sign') and request.method == 'POST')
            or path.startswith(f'{workforce_bp.url_prefix}/notices/')
            and path.endswith('/acknowledge')
            and request.method == 'POST'
            or path.startswith(f'{workforce_bp.url_prefix}/emergency')
            and request.method == 'POST'
            or bool(re.fullmatch(r'/api/fleet/vehicles/[^/]+/breakdowns', path))
            and request.method == 'POST'
            or bool(re.fullmatch(r'/api/shipments/[^/]+/status', path))
            and request.method == 'PATCH'
            and (request.get_json(silent=True) or {}).get('status') == 'BREAKDOWN'
        )
        if allowed:
            return None
        return jsonify({
            'status': 'locked',
            'code': 'WORKFORCE_ACKNOWLEDGEMENT_REQUIRED',
            'message': 'Review and sign your pending paystub, terms update, or consent agreement to continue.',
            'pending_url': f'{workforce_bp.url_prefix}/pending',
            'safety_actions_allowed': True,
        }), 423


@workforce_bp.get('/pending')
@jwt_required()
def get_pending_acknowledgements():
    user = current_user()
    if not user or user.role not in EMPLOYEE_ROLES:
        return jsonify({'status': 'error', 'message': 'Employee access is required.'}), 403
    pending = employee_acknowledgement_status(user)
    return jsonify({
        'status': 'success',
        'must_acknowledge': pending['must_acknowledge'],
        'pending_slips': [slip.to_dict() for slip in pending['pending_slips']],
        'pending_notices': [notice.to_dict() for notice in pending['pending_notices']],
    }), 200


@workforce_bp.get('/drivers')
@jwt_required()
def list_driver_statuses():
    manager = _manager()
    if not manager:
        return jsonify({'status': 'error', 'message': 'HR access is required.'}), 403
    drivers = UserAccount.query.filter_by(role='driver').order_by(UserAccount.display_name, UserAccount.id).all()
    return jsonify({
        'status': 'success',
        'drivers': [
            {
                'id': driver.id,
                'name': driver.display_name or driver.driver_name or driver.email,
                'driver_id': driver.driver_code or str(driver.id),
                'status': driver.employment_status,
                'leave_type': driver.leave_type,
                'status_note': driver.employment_status_note,
                'score': driver_score(driver),
                'leaderboard_opt_in': driver.leaderboard_opt_in,
                'leaderboard_handle': driver.leaderboard_handle,
            }
            for driver in drivers
        ],
    }), 200


@workforce_bp.patch('/drivers/<int:driver_id>/status')
@jwt_required()
def update_driver_status(driver_id):
    manager = _manager()
    if not manager:
        return jsonify({'status': 'error', 'message': 'HR access is required.'}), 403
    driver = db.session.get(UserAccount, driver_id)
    if not driver or driver.role != 'driver':
        return jsonify({'status': 'error', 'message': 'Driver was not found.'}), 404
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'status': 'error', 'message': 'A JSON status update is required.'}), 400
    status = data.get('status')
    leave_type = data.get('leave_type')
    note = data.get('note', '')
    if status not in DRIVER_STATUSES:
        return jsonify({'status': 'error', 'message': 'Choose Active, On Leave, Suspended, or Off-Duty.'}), 400
    if status == 'ON_LEAVE' and leave_type not in LEAVE_TYPES:
        return jsonify({'status': 'error', 'message': 'Choose Sick or Vacation for leave status.'}), 400
    if status != 'ON_LEAVE':
        leave_type = None
    if not isinstance(note, str) or len(note) > 500:
        return jsonify({'status': 'error', 'message': 'Status notes must be at most 500 characters.'}), 400
    driver.employment_status = status
    driver.leave_type = leave_type
    driver.employment_status_note = note.strip() or None
    driver.employment_status_updated_at = datetime.now(timezone.utc)
    driver.employment_status_updated_by_id = manager.id
    db.session.commit()
    return jsonify({'status': 'success', 'driver': {
        'id': driver.id,
        'name': driver.display_name or driver.driver_name or driver.email,
        'status': driver.employment_status,
        'leave_type': driver.leave_type,
    }}), 200


@workforce_bp.get('/cases')
@jwt_required()
def list_workforce_cases():
    user = current_user()
    if not user:
        return jsonify({'status': 'error', 'message': 'Sign in to review workforce records.'}), 401
    query = WorkforceCase.query
    locked = employee_acknowledgement_status(user)['must_acknowledge']
    if user.role not in HR_ROLES or locked:
        query = query.filter_by(employee_id=user.id)
    cases = query.order_by(WorkforceCase.created_at.desc()).limit(200).all()
    return jsonify({'status': 'success', 'cases': [case.to_dict() for case in cases]}), 200


@workforce_bp.post('/cases')
@jwt_required()
def create_workforce_case():
    manager = _manager()
    if not manager:
        return jsonify({'status': 'error', 'message': 'HR access is required to create a formal employee record.'}), 403
    employee_id = request.form.get('employee_id', type=int)
    employee = db.session.get(UserAccount, employee_id) if employee_id else None
    if not employee or employee.role != 'driver':
        return jsonify({'status': 'error', 'message': 'Choose an existing driver.'}), 400
    case_type = request.form.get('case_type')
    severity = request.form.get('severity')
    details = request.form.get('details', '').strip()
    if case_type not in CASE_TYPES or severity not in CASE_SEVERITIES:
        return jsonify({'status': 'error', 'message': 'Choose a valid HR record type and infraction severity.'}), 400
    if not details or len(details) > 3000:
        return jsonify({'status': 'error', 'message': 'Record details are required and limited to 3,000 characters.'}), 400
    uploads = request.files.getlist('evidence')
    if len(uploads) > 5:
        return jsonify({'status': 'error', 'message': 'Attach no more than five evidence files.'}), 400
    now = datetime.now(timezone.utc)
    case = WorkforceCase(
        employee_id=employee.id,
        created_by_id=manager.id,
        case_type=case_type,
        severity=severity,
        details=details,
        status='DISPUTE_OPEN',
        created_at=now,
        dispute_deadline_at=now + timedelta(hours=DISPUTE_HOURS),
    )
    db.session.add(case)
    db.session.flush()
    try:
        for evidence in _accept_evidence(case.id, manager.id, uploads):
            db.session.add(evidence)
    except ValueError as error:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(error)}), 400
    db.session.commit()
    return jsonify({
        'status': 'success',
        'message': f'The driver has {DISPUTE_HOURS} hours to submit a rebuttal before an undisputed infraction can affect their score.',
        'case': case.to_dict(),
    }), 201


@workforce_bp.post('/cases/<int:case_id>/dispute')
@jwt_required()
def submit_case_rebuttal(case_id):
    user = current_user()
    case = db.session.get(WorkforceCase, case_id)
    if not user or not case or case.employee_id != user.id:
        return jsonify({'status': 'error', 'message': 'The HR record was not found for this account.'}), 404
    deadline = case.dispute_deadline_at
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > deadline or case.status != 'DISPUTE_OPEN':
        return jsonify({'status': 'error', 'message': 'The 72-hour dispute window has closed.'}), 409
    if WorkforceCaseRebuttal.query.filter_by(case_id=case.id).first():
        return jsonify({'status': 'error', 'message': 'A rebuttal has already been submitted for this record.'}), 409
    details = request.form.get('details', '').strip()
    if not details or len(details) > 3000:
        return jsonify({'status': 'error', 'message': 'A rebuttal is required and limited to 3,000 characters.'}), 400
    uploads = request.files.getlist('evidence')
    if len(uploads) > 5:
        return jsonify({'status': 'error', 'message': 'Attach no more than five evidence files.'}), 400
    rebuttal = WorkforceCaseRebuttal(case_id=case.id, employee_id=user.id, details=details)
    case.status = 'UNDER_REVIEW'
    db.session.add(rebuttal)
    db.session.flush()
    try:
        for evidence in _accept_evidence(case.id, user.id, uploads):
            db.session.add(evidence)
    except ValueError as error:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(error)}), 400
    db.session.commit()
    return jsonify({'status': 'success', 'case': case.to_dict()}), 201


@workforce_bp.patch('/cases/<int:case_id>/resolve')
@jwt_required()
def resolve_workforce_case(case_id):
    manager = _manager()
    if not manager:
        return jsonify({'status': 'error', 'message': 'HR access is required.'}), 403
    case = db.session.get(WorkforceCase, case_id)
    if not case:
        return jsonify({'status': 'error', 'message': 'HR record was not found.'}), 404
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get('upheld'), bool):
        return jsonify({'status': 'error', 'message': 'Choose whether the infraction is upheld after review.'}), 400
    if case.status not in {'UNDER_REVIEW', 'DISPUTE_OPEN'}:
        return jsonify({'status': 'error', 'message': 'This HR record has already been resolved.'}), 409
    resolution_note = data.get('resolution_note', '')
    if not isinstance(resolution_note, str) or len(resolution_note) > 2000:
        return jsonify({'status': 'error', 'message': 'The resolution note must be at most 2,000 characters.'}), 400
    case.status = 'UPHELD' if data['upheld'] else 'DISMISSED'
    case.resolved_at = datetime.now(timezone.utc)
    case.resolved_by_id = manager.id
    case.resolution_note = resolution_note.strip() or None
    db.session.commit()
    return jsonify({'status': 'success', 'case': case.to_dict()}), 200


@workforce_bp.get('/cases/<int:case_id>/evidence/<int:evidence_id>')
@jwt_required()
def download_case_evidence(case_id, evidence_id):
    user = current_user()
    evidence = db.session.get(WorkforceCaseEvidence, evidence_id)
    if not user or not evidence or evidence.case_id != case_id:
        return jsonify({'status': 'error', 'message': 'Evidence was not found.'}), 404
    if user.role not in HR_ROLES and evidence.case.employee_id != user.id:
        return jsonify({'status': 'error', 'message': 'Evidence access is not authorized.'}), 403
    if hashlib.sha256(evidence.contents).hexdigest() != evidence.sha256:
        current_app.logger.error('SHA-256 validation failed for HR case evidence %s', evidence.id)
        return jsonify({'status': 'error', 'message': 'Evidence failed integrity verification.'}), 500
    return send_file(
        io.BytesIO(evidence.contents),
        mimetype=evidence.mime_type,
        as_attachment=True,
        download_name=evidence.filename,
    )


@workforce_bp.post('/notices')
@jwt_required()
def create_workforce_notice():
    manager = _manager()
    if not manager:
        return jsonify({'status': 'error', 'message': 'HR access is required to publish employee notices.'}), 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'status': 'error', 'message': 'A JSON notice is required.'}), 400
    notice_type = data.get('notice_type')
    title = data.get('title')
    body = data.get('body')
    version = data.get('version')
    if (
        notice_type not in NOTICE_TYPES
        or not isinstance(title, str) or not title.strip() or len(title) > 160
        or not isinstance(body, str) or not body.strip() or len(body) > 5000
        or not isinstance(version, str) or not version.strip() or len(version) > 40
    ):
        return jsonify({'status': 'error', 'message': 'Provide a valid notice type, title, body, and version.'}), 400
    try:
        verify_immutable_storage_ready()
    except RuntimeError as error:
        return jsonify({'status': 'error', 'message': str(error)}), 503
    notice = WorkforceNotice(
        notice_type=notice_type,
        title=title.strip(),
        body=body.strip(),
        version=version.strip(),
        created_by_id=manager.id,
    )
    WorkforceNotice.query.filter_by(notice_type=notice_type, published=True).update(
        {'published': False},
        synchronize_session=False,
    )
    db.session.add(notice)
    db.session.commit()
    return jsonify({'status': 'success', 'notice': notice.to_dict()}), 201


@workforce_bp.post('/notices/<int:notice_id>/acknowledge')
@jwt_required()
def acknowledge_workforce_notice(notice_id):
    user = current_user()
    notice = db.session.get(WorkforceNotice, notice_id)
    if not user or user.role not in EMPLOYEE_ROLES or not notice or not notice.published:
        return jsonify({'status': 'error', 'message': 'The notice was not found for this account.'}), 404
    if WorkforceNoticeAcknowledgement.query.filter_by(
        notice_id=notice.id, employee_id=user.id,
    ).first():
        return jsonify({'status': 'error', 'message': 'This notice has already been acknowledged.'}), 409
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or data.get('acknowledged') is not True:
        return jsonify({'status': 'error', 'message': 'Confirm that you have read this notice before signing.'}), 400
    try:
        signature = parse_signature(data)
        device_id, latitude, longitude = parse_signature_metadata(data)
    except ValueError as error:
        return jsonify({'status': 'error', 'message': str(error)}), 400
    signed_at = datetime.now(timezone.utc)
    ip_address = request.remote_addr
    pdf = build_signed_pdf(
        notice.title, f'{notice.body}\n\nNotice version: {notice.version}',
        signature, signed_at, device_id, ip_address, latitude, longitude,
    )
    try:
        object_key, version_id, digest = upload_immutable_pdf(pdf)
    except RuntimeError as error:
        return jsonify({'status': 'error', 'message': str(error)}), 503
    acknowledgement = WorkforceNoticeAcknowledgement(
        notice_id=notice.id,
        employee_id=user.id,
        signed_at=signed_at,
        device_id=device_id,
        ip_address=ip_address,
        latitude=latitude,
        longitude=longitude,
        pdf_object_key=object_key,
        pdf_version_id=version_id,
        pdf_sha256=digest,
    )
    db.session.add(acknowledgement)
    db.session.commit()
    return jsonify({'status': 'success', 'acknowledged_at': signed_at.isoformat(), 'sha256': digest}), 201


@workforce_bp.get('/notices')
@jwt_required()
def list_workforce_notices():
    user = current_user()
    if not user or user.role not in EMPLOYEE_ROLES:
        return jsonify({'status': 'error', 'message': 'Employee access is required.'}), 403
    notices = WorkforceNotice.query.filter_by(published=True).order_by(
        WorkforceNotice.created_at.desc(),
    ).all()
    records = []
    for notice in notices:
        acknowledgement = WorkforceNoticeAcknowledgement.query.filter_by(
            notice_id=notice.id,
            employee_id=user.id,
        ).first()
        records.append({
            **notice.to_dict(),
            'acknowledged_at': acknowledgement.signed_at.isoformat() if acknowledgement else None,
            'signed_document_url': (
                f'{workforce_bp.url_prefix}/notices/{notice.id}/signed-document'
                if acknowledgement else None
            ),
        })
    return jsonify({'status': 'success', 'notices': records}), 200


@workforce_bp.get('/notices/<int:notice_id>/signed-document')
@jwt_required()
def download_signed_notice(notice_id):
    user = current_user()
    acknowledgement = WorkforceNoticeAcknowledgement.query.filter_by(
        notice_id=notice_id,
        employee_id=user.id if user else None,
    ).first()
    if not acknowledgement and user and user.role in HR_ROLES:
        acknowledgement = WorkforceNoticeAcknowledgement.query.filter_by(
            notice_id=notice_id,
        ).first()
    if not acknowledgement:
        return jsonify({'status': 'error', 'message': 'Signed notice was not found for this account.'}), 404
    try:
        contents = download_verified_pdf(
            acknowledgement.pdf_object_key,
            acknowledgement.pdf_version_id,
            acknowledgement.pdf_sha256,
        )
    except RuntimeError as error:
        return jsonify({'status': 'error', 'message': str(error)}), 500
    return send_file(
        io.BytesIO(contents),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'notice-{notice_id}-acknowledgement.pdf',
    )


@workforce_bp.get('/score')
@jwt_required()
def get_own_driver_score():
    user = current_user()
    if not user or user.role != 'driver':
        return jsonify({'status': 'error', 'message': 'Driver access is required.'}), 403
    return jsonify({'status': 'success', 'score': driver_score(user)}), 200


@workforce_bp.get('/drivers/<int:driver_id>/score')
@jwt_required()
def get_driver_score(driver_id):
    manager = _manager()
    driver = db.session.get(UserAccount, driver_id)
    if not manager:
        return jsonify({'status': 'error', 'message': 'HR access is required.'}), 403
    if not driver or driver.role != 'driver':
        return jsonify({'status': 'error', 'message': 'Driver was not found.'}), 404
    return jsonify({'status': 'success', 'score': driver_score(driver)}), 200


@workforce_bp.get('/leaderboard')
def public_driver_leaderboard():
    drivers = UserAccount.query.filter_by(
        role='driver', leaderboard_opt_in=True, employment_status='ACTIVE', account_status='active',
    ).all()
    now = datetime.now(timezone.utc)
    period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    scores = []
    for driver in drivers:
        performance = driver_score(driver, performance_since=period_start)
        if performance['customer_rating_count'] + performance['scored_deliveries'] == 0:
            continue
        scores.append({
            'driver_id': driver.driver_code or str(driver.id),
            'handle': driver.leaderboard_handle or f'Driver {driver.driver_code or driver.id}',
            'score': performance['score'],
        })
    scores.sort(key=lambda item: (-item['score'], item['handle'].casefold(), item['driver_id']))
    return jsonify({
        'status': 'success',
        'period': period_start.strftime('%Y-%m'),
        'hr_penalty_decay_days': SCORE_WINDOW_DAYS,
        'drivers': [{'rank': index + 1, **record} for index, record in enumerate(scores[:100])],
    }), 200


@workforce_bp.patch('/leaderboard-opt-in')
@jwt_required()
def set_leaderboard_opt_in():
    user = current_user()
    if not user or user.role != 'driver':
        return jsonify({'status': 'error', 'message': 'Driver access is required.'}), 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get('opt_in'), bool):
        return jsonify({'status': 'error', 'message': 'Choose whether your score may appear on the public leaderboard.'}), 400
    handle = data.get('handle', '')
    if not isinstance(handle, str) or len(handle.strip()) > 40:
        return jsonify({'status': 'error', 'message': 'The leaderboard handle must be at most 40 characters.'}), 400
    if data['opt_in'] and not handle.strip():
        return jsonify({'status': 'error', 'message': 'Enter a public handle or driver ID before opting in.'}), 400
    user.leaderboard_opt_in = data['opt_in']
    user.leaderboard_handle = handle.strip() or None
    db.session.commit()
    return jsonify({'status': 'success', 'opt_in': user.leaderboard_opt_in}), 200


@workforce_bp.post('/shipments/<tracking_number>/rating')
@jwt_required()
def rate_completed_shipment(tracking_number):
    user = current_user()
    if not user or user.role != 'client':
        return jsonify({'status': 'error', 'message': 'Only the shipment client may submit a rating.'}), 403
    shipment = db.session.get(Shipment, tracking_number.strip().upper())
    if not shipment or not shipment_visible_to(shipment, user):
        return jsonify({'status': 'error', 'message': 'Shipment was not found for this client.'}), 404
    signed_pod = ShipmentProofOfDelivery.query.filter_by(
        shipment_tracking_number=shipment.tracking_number,
    ).first()
    if shipment.status != 'DELIVERED' or not shipment.assigned_driver_id or not signed_pod:
        return jsonify({'status': 'error', 'message': 'A rating is available after signed proof of delivery.'}), 409
    data = request.get_json(silent=True)
    stars = data.get('stars') if isinstance(data, dict) else None
    feedback = data.get('feedback', '') if isinstance(data, dict) else ''
    if isinstance(stars, bool) or not isinstance(stars, int) or not 1 <= stars <= 5:
        return jsonify({'status': 'error', 'message': 'Choose a rating from one to five stars.'}), 400
    if not isinstance(feedback, str) or len(feedback) > 1000:
        return jsonify({'status': 'error', 'message': 'Rating feedback must be at most 1,000 characters.'}), 400
    rating = DriverRating.query.filter_by(shipment_tracking_number=shipment.tracking_number).first()
    if rating:
        return jsonify({'status': 'error', 'message': 'This shipment has already been rated.'}), 409
    rating = DriverRating(
        shipment_tracking_number=shipment.tracking_number,
        driver_id=shipment.assigned_driver_id,
        client_id=user.id,
        stars=stars,
        feedback=feedback.strip() or None,
    )
    db.session.add(rating)
    db.session.commit()
    return jsonify({'status': 'success', 'score': driver_score(rating.driver)}), 201


@workforce_bp.get('/shipments/<tracking_number>/rating')
@jwt_required()
def get_shipment_rating(tracking_number):
    user = current_user()
    shipment = db.session.get(Shipment, tracking_number.strip().upper())
    if not user or user.role != 'client' or not shipment or not shipment_visible_to(shipment, user):
        return jsonify({'status': 'error', 'message': 'Shipment was not found for this client.'}), 404
    rating = DriverRating.query.filter_by(shipment_tracking_number=shipment.tracking_number).first()
    return jsonify({
        'status': 'success',
        'can_rate': (
            not rating
            and shipment.status == 'DELIVERED'
            and ShipmentProofOfDelivery.query.filter_by(
            shipment_tracking_number=shipment.tracking_number,
            ).first() is not None
        ),
        'already_rated': rating is not None,
        'rating': {
            'stars': rating.stars,
            'feedback': rating.feedback,
            'created_at': rating.created_at.isoformat(),
        } if rating and rating.client_id == user.id else None,
    }), 200


@workforce_bp.get('/driver/rateable-shipments')
@jwt_required()
def list_shipments_for_client_rating():
    user = current_user()
    if not user or user.role != 'driver':
        return jsonify({'status': 'error', 'message': 'Driver access is required.'}), 403
    shipments = Shipment.query.filter_by(
        assigned_driver_id=user.id,
        status='DELIVERED',
    ).order_by(Shipment.arrived_at.desc(), Shipment.created_at.desc()).all()
    rated = {
        rating.shipment_tracking_number
        for rating in ClientRating.query.filter_by(driver_id=user.id).all()
    }
    records = []
    for shipment in shipments:
        if shipment.tracking_number in rated or not shipment.company_name:
            continue
        if not ShipmentProofOfDelivery.query.filter_by(
            shipment_tracking_number=shipment.tracking_number,
        ).first():
            continue
        records.append({
            'tracking_number': shipment.tracking_number,
            'company_name': shipment.company_name,
            'destination': shipment.destination,
        })
    return jsonify({'status': 'success', 'shipments': records}), 200


@workforce_bp.post('/shipments/<tracking_number>/client-rating')
@jwt_required()
def rate_shipment_client(tracking_number):
    user = current_user()
    if not user or user.role != 'driver':
        return jsonify({'status': 'error', 'message': 'Only the assigned driver may rate a client.'}), 403
    shipment = db.session.get(Shipment, tracking_number.strip().upper())
    if not shipment or shipment.assigned_driver_id != user.id or not shipment.company_name:
        return jsonify({'status': 'error', 'message': 'Shipment was not found for this driver.'}), 404
    if shipment.status != 'DELIVERED' or not ShipmentProofOfDelivery.query.filter_by(
        shipment_tracking_number=shipment.tracking_number,
    ).first():
        return jsonify({'status': 'error', 'message': 'Client ratings are available after signed proof of delivery.'}), 409
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'status': 'error', 'message': 'Provide a client rating.'}), 400
    loading_speed = data.get('loading_speed_stars')
    friendliness = data.get('facility_friendliness_stars')
    if any(
        isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5
        for value in (loading_speed, friendliness)
    ):
        return jsonify({'status': 'error', 'message': 'Choose one-to-five stars for loading speed and facility friendliness.'}), 400
    feedback = data.get('feedback', '')
    if not isinstance(feedback, str) or len(feedback) > 1000:
        return jsonify({'status': 'error', 'message': 'Feedback must be at most 1,000 characters.'}), 400
    if ClientRating.query.filter_by(shipment_tracking_number=shipment.tracking_number).first():
        return jsonify({'status': 'error', 'message': 'This shipment has already been rated for client service.'}), 409

    client = db.session.get(UserAccount, shipment.client_user_id) if shipment.client_user_id else UserAccount.query.filter(
        UserAccount.role == 'client',
        db.func.lower(UserAccount.company_name) == shipment.company_name.strip().lower(),
        UserAccount.account_status == 'active',
    ).order_by(UserAccount.id).first()
    if not client or client.role != 'client' or client.account_status != 'active':
        return jsonify({'status': 'error', 'message': 'The shipment is not linked to an active client account.'}), 409
    rating = ClientRating(
        shipment_tracking_number=shipment.tracking_number,
        driver_id=user.id,
        client_id=client.id,
        loading_speed_stars=loading_speed,
        facility_friendliness_stars=friendliness,
        feedback=feedback.strip() or None,
    )
    db.session.add(rating)
    db.session.commit()
    return jsonify({'status': 'success', 'rating': {
        'shipment_tracking_number': shipment.tracking_number,
        'score': round(rating.score, 2),
    }}), 201


@workforce_bp.get('/client-leaderboard')
@jwt_required()
def client_ratings_leaderboard():
    manager = _manager()
    if not manager:
        return jsonify({'status': 'error', 'message': 'HR access is required to view client ratings.'}), 403
    ratings = ClientRating.query.all()
    groups = {}
    for rating in ratings:
        group = groups.setdefault(rating.client_id, {
            'client_id': rating.client_id,
            'company_name': rating.client.company_name,
            'rating_count': 0,
            'loading_speed_total': 0,
            'facility_friendliness_total': 0,
            'feedback': [],
        })
        group['rating_count'] += 1
        group['loading_speed_total'] += rating.loading_speed_stars
        group['facility_friendliness_total'] += rating.facility_friendliness_stars
        if rating.feedback and len(group['feedback']) < 10:
            group['feedback'].append({
                'tracking_number': rating.shipment_tracking_number,
                'feedback': rating.feedback,
                'created_at': rating.created_at.isoformat(),
            })
    clients = []
    for group in groups.values():
        count = group['rating_count']
        loading_speed_average = group['loading_speed_total'] / count
        friendliness_average = group['facility_friendliness_total'] / count
        clients.append({
            'client_id': group['client_id'],
            'company_name': group['company_name'],
            'rating_count': count,
            'loading_speed_average': round(loading_speed_average, 2),
            'facility_friendliness_average': round(friendliness_average, 2),
            'average_rating': round((loading_speed_average + friendliness_average) / 2, 2),
            'feedback': group['feedback'],
        })
    clients.sort(key=lambda row: (-row['average_rating'], -row['rating_count'], row['company_name'].casefold()))
    return jsonify({
        'status': 'success',
        'clients': [{'rank': index + 1, **row} for index, row in enumerate(clients[:100])],
    }), 200


@workforce_bp.get('/hr-dashboard')
@jwt_required()
def hr_dashboard():
    manager = _manager()
    if not manager:
        return jsonify({'status': 'error', 'message': 'HR access is required.'}), 403
    drivers = UserAccount.query.filter_by(role='driver').all()
    cases = WorkforceCase.query.order_by(WorkforceCase.created_at.desc()).limit(200).all()
    emergencies = SafetyEmergencyReport.query.order_by(SafetyEmergencyReport.created_at.desc()).limit(100).all()
    return jsonify({
        'status': 'success',
        'drivers': [
            {
                'id': driver.id,
                'name': driver.display_name or driver.driver_name or driver.email,
                'driver_id': driver.driver_code or str(driver.id),
                'employment_status': driver.employment_status,
                'leave_type': driver.leave_type,
                'status_note': driver.employment_status_note,
                'score': driver_score(driver),
            }
            for driver in drivers
        ],
        'cases': [case.to_dict() for case in cases],
        'emergencies': [
            {
                'id': report.id,
                'reference': f'SAFE-{report.id:06d}',
                'employee_name': report.employee.display_name or report.employee.email,
                'report_type': report.report_type,
                'vehicle_registration': report.vehicle_registration,
                'location': report.location,
                'description': report.description,
                'created_at': report.created_at.isoformat(),
            }
            for report in emergencies
        ],
    }), 200


@workforce_bp.post('/emergency')
@jwt_required()
def report_emergency():
    user = current_user()
    if not user or user.role not in EMPLOYEE_ROLES:
        return jsonify({'status': 'error', 'message': 'Employee access is required to submit this safety report.'}), 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'status': 'error', 'message': 'An emergency report is required.'}), 400
    report_type = data.get('report_type')
    vehicle_registration = data.get('vehicle_registration', '')
    location = data.get('location')
    description = data.get('description')
    if report_type not in {'ACTIVE_ACCIDENT', 'ROADSIDE_BREAKDOWN'}:
        return jsonify({'status': 'error', 'message': 'Choose an active accident or roadside breakdown.'}), 400
    if (
        not isinstance(location, str) or not location.strip() or len(location) > 200
        or not isinstance(description, str) or not description.strip() or len(description) > 2000
        or not isinstance(vehicle_registration, str) or len(vehicle_registration) > 20
    ):
        return jsonify({'status': 'error', 'message': 'Enter the emergency location and details.'}), 400
    vehicle = None
    if report_type == 'ROADSIDE_BREAKDOWN':
        if not vehicle_registration.strip():
            return jsonify({'status': 'error', 'message': 'Choose the vehicle involved in the roadside breakdown.'}), 400
        from backend.routes.fleet import FleetVehicle, VehicleBreakdown

        vehicle = FleetVehicle.query.filter_by(
            registration=vehicle_registration.strip().upper(),
        ).first()
        if not vehicle or (
            user.role not in HR_ROLES and vehicle.assigned_driver_id != user.id
        ):
            return jsonify({'status': 'error', 'message': 'The vehicle was not found or is not assigned to this driver.'}), 404
        vehicle.status = 'BREAKDOWN'
        db.session.add(VehicleBreakdown(
            vehicle_id=vehicle.id,
            reported_by_id=user.id,
            severity='HIGH',
            location=location.strip(),
            description=description.strip(),
            incident_date=datetime.now(timezone.utc).date().isoformat(),
            symptoms=description.strip(),
            odometer_km=vehicle.current_odometer_km,
        ))
    report = SafetyEmergencyReport(
        employee_id=user.id,
        report_type=report_type,
        vehicle_registration=vehicle.registration if vehicle else None,
        location=location.strip(),
        description=description.strip(),
    )
    db.session.add(report)
    db.session.commit()
    return jsonify({
        'status': 'success',
        'message': 'Emergency report recorded for HR review.',
        'reference': f'SAFE-{report.id:06d}',
        'created_at': report.created_at.isoformat(),
    }), 201
