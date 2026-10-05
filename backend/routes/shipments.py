import io
import os
import re
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from threading import Lock

import numpy as np
import pymupdf as fitz
from flask import Blueprint, current_app, jsonify, request, send_file
from flask_jwt_extended import get_jwt_identity, jwt_required
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError
from rapidocr_onnxruntime import RapidOCR
from werkzeug.utils import secure_filename

from backend.models.payroll import db
from backend.routes.auth import ADMIN_ROLES, UserAccount

shipments_bp = Blueprint('shipments', __name__, url_prefix='/api/shipments')
MAX_DOCUMENT_BYTES = 12 * 1024 * 1024
MAX_DOCUMENTS_PER_UPLOAD = 10
MAX_PDF_PAGES = 8
MAX_OCR_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = MAX_OCR_PIXELS
OCR_ENGINE = RapidOCR()
OCR_ENGINE_LOCK = Lock()


class Shipment(db.Model):
    __tablename__ = 'shipments'

    tracking_number = db.Column(db.String(40), primary_key=True)
    status = db.Column(db.String(30), nullable=False)
    origin = db.Column(db.String(160), nullable=False)
    destination = db.Column(db.String(160), nullable=False)
    cargo_type = db.Column(db.String(160), nullable=False)
    tonnage = db.Column(db.Float, nullable=False)
    imei = db.Column(db.String(32), nullable=True)
    breakdown_alert = db.Column(db.Boolean, nullable=False, default=False)
    company_name = db.Column(db.String(120), nullable=True, index=True)
    assigned_driver_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    departed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    arrived_at = db.Column(db.DateTime(timezone=True), nullable=True)
    assigned_driver = db.relationship('UserAccount', foreign_keys=[assigned_driver_id])
    documents = db.relationship('ShipmentDocument', backref='shipment', lazy=True, cascade='all, delete-orphan')
    deliveries = db.relationship('ShipmentDelivery', backref='shipment', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        documents = ShipmentDocument.query.filter_by(
            shipment_tracking_number=self.tracking_number,
        ).all()
        deliveries = ShipmentDelivery.query.filter_by(
            shipment_tracking_number=self.tracking_number,
        ).order_by(ShipmentDelivery.delivery_number).all()
        return {
            'tracking_number': self.tracking_number,
            'status': self.status,
            'origin': self.origin,
            'destination': self.destination,
            'cargo_type': self.cargo_type,
            'tonnage': self.tonnage,
            'imei': self.imei,
            'breakdown_alert': self.breakdown_alert,
            'company_name': self.company_name,
            'assigned_driver_name': self.assigned_driver.driver_name if self.assigned_driver else None,
            'destination_verified': any(document.destination_validated for document in documents),
            'departed_at': self.departed_at.isoformat() if self.departed_at else None,
            'arrived_at': self.arrived_at.isoformat() if self.arrived_at else None,
            'deliveries': [
                {
                    'delivery_number': delivery.delivery_number,
                    'goods_description': delivery.goods_description,
                    'customer_name': delivery.customer_name,
                    'destination': delivery.destination,
                }
                for delivery in deliveries
            ],
        }


class ShipmentDocument(db.Model):
    __tablename__ = 'shipment_documents'

    id = db.Column(db.String(36), primary_key=True)
    shipment_tracking_number = db.Column(
        db.String(40), db.ForeignKey('shipments.tracking_number'), nullable=False, index=True
    )
    document_type = db.Column(db.String(32), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    storage_filename = db.Column(db.String(80), nullable=False, unique=True)
    mime_type = db.Column(db.String(80), nullable=False)
    destination_validated = db.Column(db.Boolean, nullable=False, default=False)
    ocr_destination = db.Column(db.String(160), nullable=True)
    security_stamped_at = db.Column(db.DateTime(timezone=True), nullable=True)
    client_received_stamped_at = db.Column(db.DateTime(timezone=True), nullable=True)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False)
    uploaded_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    uploaded_by = db.relationship('UserAccount', foreign_keys=[uploaded_by_id])
    deliveries = db.relationship('ShipmentDelivery', backref='source_document', lazy=True, cascade='all, delete-orphan')


class ShipmentDelivery(db.Model):
    __tablename__ = 'shipment_deliveries'

    id = db.Column(db.Integer, primary_key=True)
    shipment_tracking_number = db.Column(
        db.String(40), db.ForeignKey('shipments.tracking_number'), nullable=False, index=True
    )
    document_id = db.Column(db.String(36), db.ForeignKey('shipment_documents.id'), nullable=False, index=True)
    delivery_number = db.Column(db.String(100), nullable=False, index=True)
    goods_description = db.Column(db.String(500), nullable=True)
    customer_name = db.Column(db.String(200), nullable=True)
    destination = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


def seed_demo_shipment():
    if db.session.get(Shipment, 'DL-8801') is None:
        shipment = Shipment()
        shipment.tracking_number = 'DL-8801'
        shipment.status = 'IN_TRANSIT'
        shipment.origin = 'Athi River Industrial Zone'
        shipment.destination = 'Kisumu Central Warehouse'
        shipment.cargo_type = 'General Goods / FMCG'
        shipment.tonnage = 15
        shipment.imei = '490154203237518'
        shipment.breakdown_alert = False
        shipment.company_name = None
        shipment.assigned_driver_id = None
        shipment.departed_at = datetime.now(timezone.utc)
        db.session.add(shipment)
        db.session.commit()


def get_request_user():
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        return None
    return db.session.get(UserAccount, user_id)


def shipment_visible_to(shipment, user):
    if user.role in ADMIN_ROLES:
        return True
    if user.role == 'client':
        return bool(user.company_name and shipment.company_name and
                    user.company_name.strip().casefold() == shipment.company_name.strip().casefold())
    if user.role == 'driver':
        return shipment.assigned_driver_id == user.id
    return False


def normalize_text(value):
    return re.sub(r'[^a-z0-9]', '', value.casefold())


def destination_found(ocr_text, destination):
    expected = normalize_text(destination)
    actual = normalize_text(ocr_text)
    if expected and expected in actual:
        return True

    expected_tokens = re.findall(r'[a-z0-9]+', destination.casefold())
    actual_tokens = re.findall(r'[a-z0-9]+', ocr_text.casefold())
    if not expected_tokens or not actual_tokens:
        return False

    matches = sum(
        any(SequenceMatcher(None, expected_token, token).ratio() >= 0.82 for token in actual_tokens)
        for expected_token in expected_tokens
    )
    return matches / len(expected_tokens) >= 0.8


def ocr_label_value(ocr_text, labels):
    label_pattern = '|'.join(labels)
    match = re.search(
        rf'^\s*(?:{label_pattern})\s*(?:[:#\-]\s*)?(.+?)\s*$',
        ocr_text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if match and match.group(1).strip():
        value = re.sub(r'\s+', ' ', match.group(1)).strip(' :#-\t')
        if value and normalize_text(value) not in {normalize_text(label) for label in labels}:
            return value[:300]

    lines = [line.strip(' :#-\t') for line in ocr_text.splitlines() if line.strip(' :#-\t')]
    for index, line in enumerate(lines[:-1]):
        if re.fullmatch(rf'(?:{label_pattern})\s*[:#\-]?', line, flags=re.IGNORECASE):
            return lines[index + 1][:300]
    return None


def extract_delivery_rows(ocr_text, expected_destination):
    pattern = re.compile(
        r'\b(?:del(?:i)?very\s*(?:note\s*)?(?:no\.?|number|#|ref(?:erence)?)|'
        r'd\.?\s*n\.?|waybill\s*(?:no\.?|number|#))\s*[:#\-]?\s*'
        r'([A-Z0-9][A-Z0-9/-]{2,})',
        flags=re.IGNORECASE,
    )
    delivery_numbers = list(dict.fromkeys(match.group(1).strip('/-') for match in pattern.finditer(ocr_text)))
    goods = ocr_label_value(ocr_text, [
        r'description\s+of\s+goods', r'goods\s+description', r'goods', r'commodity', r'product(?:s)?', r'items?',
    ])
    customer = ocr_label_value(ocr_text, [
        r'customer(?:\s+name)?', r'consignee', r'recipient', r'bill\s+to', r'deliver\s+to',
    ])
    destination = ocr_label_value(ocr_text, [
        r'delivery\s+destination', r'destination', r'delivery\s+address', r'ship\s+to', r'deliver\s+to',
    ])
    if not destination and destination_found(ocr_text, expected_destination):
        destination = expected_destination

    return [{
        'delivery_number': number[:100],
        'goods_description': goods[:500] if goods else None,
        'customer_name': customer[:200] if customer else None,
        'destination': destination[:300] if destination else None,
    } for number in delivery_numbers]


def inspect_and_ocr_file(contents):
    if not contents or len(contents) > MAX_DOCUMENT_BYTES:
        raise ValueError('Each upload must be between 1 byte and 12 MB.')

    if contents.startswith(b'%PDF-'):
        try:
            document = fitz.open(stream=contents, filetype='pdf')
        except (fitz.FileDataError, RuntimeError) as exc:
            raise ValueError('The PDF file is invalid or damaged.') from exc
        if document.is_encrypted or not 1 <= document.page_count <= MAX_PDF_PAGES:
            document.close()
            raise ValueError(f'PDF files must contain between 1 and {MAX_PDF_PAGES} pages and must not be encrypted.')
        page_images = []
        total_pixels = 0
        for page in document:
            if page.rect.width * page.rect.height * 2.25 > MAX_OCR_PIXELS:
                document.close()
                raise ValueError('The PDF page dimensions are too large for safe OCR processing.')
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            total_pixels += pixmap.width * pixmap.height
            if total_pixels > MAX_OCR_PIXELS:
                document.close()
                raise ValueError('The PDF page dimensions are too large for safe OCR processing.')
            page_images.append(Image.frombytes('RGB', (pixmap.width, pixmap.height), pixmap.samples))
        document.close()
        return 'application/pdf', 'pdf', page_images

    try:
        image = Image.open(io.BytesIO(contents))
        if image.format not in {'JPEG', 'PNG', 'WEBP', 'TIFF'}:
            raise ValueError('Upload a PDF, JPEG, PNG, WEBP, or TIFF document.')
        if image.format == 'TIFF' and getattr(image, 'n_frames', 1) != 1:
            raise ValueError('Upload each TIFF page as a separate document.')
        image_format = image.format
        image.verify()
        image = Image.open(io.BytesIO(contents)).convert('RGB')
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError('The uploaded document is not a valid supported image or PDF.') from exc

    mime_type = Image.MIME.get(image_format, 'image/jpeg')
    extension = image_format.lower()
    return mime_type, extension, [image]


def extract_ocr_text(image):
    with OCR_ENGINE_LOCK:
        result, _ = OCR_ENGINE(np.asarray(image.convert('RGB')))
    if not result:
        return ''
    return '\n'.join(
        str(item[1]).strip()
        for item in result
        if len(item) > 2 and float(item[2]) >= 0.55 and str(item[1]).strip()
    )


def stamp_image(image, stamp_lines):
    stamped = image.convert('RGB')
    draw = ImageDraw.Draw(stamped)
    font = ImageFont.load_default()
    line_height = 22
    band_height = 14 + line_height * len(stamp_lines)
    top = max(0, stamped.height - band_height)
    draw.rectangle((0, top, stamped.width, stamped.height), fill=(27, 59, 43))
    for index, line in enumerate(stamp_lines):
        draw.text((12, top + 7 + index * line_height), line, fill=(255, 253, 248), font=font)
    return stamped


def stamped_document_bytes(page_images, file_format, security_timestamp, received_timestamp):
    lines = []
    if security_timestamp:
        lines.append(f'DIFAN SECURITY CLEARED | {security_timestamp:%Y-%m-%d %H:%M UTC}')
    if received_timestamp:
        lines.append(f'CLIENT RECEIVED | {received_timestamp:%Y-%m-%d %H:%M UTC}')

    output = io.BytesIO()
    if file_format == 'pdf':
        document = fitz.open()
        for page_image in page_images:
            pixmap_bytes = io.BytesIO()
            page_image.save(pixmap_bytes, format='PNG')
            page = document.new_page(width=page_image.width, height=page_image.height)
            page.insert_image(page.rect, stream=pixmap_bytes.getvalue())
            page.draw_rect(
                fitz.Rect(0, page.rect.height - 46, page.rect.width, page.rect.height),
                color=(0.106, 0.231, 0.169),
                fill=(0.106, 0.231, 0.169),
                overlay=True,
            )
            page.insert_textbox(
                fitz.Rect(12, page.rect.height - 42, page.rect.width - 12, page.rect.height - 8),
                '\n'.join(lines),
                fontsize=11,
                color=(1, 1, 1),
                overlay=True,
            )
        output.write(document.tobytes(garbage=4, deflate=True))
        document.close()
    else:
        stamped = [stamp_image(image, lines) for image in page_images]
        image_format = 'JPEG' if file_format in {'jpg', 'jpeg'} else file_format.upper()
        options = {'quality': 92} if image_format == 'JPEG' else {}
        stamped[0].save(output, format=image_format, **options)
    return output.getvalue()


def stamp_existing_document(path, mime_type, security_timestamp, received_timestamp):
    lines = []
    if security_timestamp:
        lines.append(f'DIFAN SECURITY CLEARED | {security_timestamp:%Y-%m-%d %H:%M UTC}')
    if received_timestamp:
        lines.append(f'CLIENT RECEIVED | {received_timestamp:%Y-%m-%d %H:%M UTC}')
    output = io.BytesIO()

    if mime_type == 'application/pdf':
        document = fitz.open(path)
        for page in document:
            page.draw_rect(
                fitz.Rect(0, page.rect.height - 46, page.rect.width, page.rect.height),
                color=(0.106, 0.231, 0.169),
                fill=(0.106, 0.231, 0.169),
                overlay=True,
            )
            page.insert_textbox(
                fitz.Rect(12, page.rect.height - 42, page.rect.width - 12, page.rect.height - 8),
                '\n'.join(lines),
                fontsize=11,
                color=(1, 1, 1),
                overlay=True,
            )
        output.write(document.tobytes(garbage=4, deflate=True))
        document.close()
    else:
        image = Image.open(path).convert('RGB')
        stamped = stamp_image(image, lines)
        image_format = next(
            (format_name for format_name, mapped_mime in Image.MIME.items() if mapped_mime == mime_type),
            'JPEG',
        )
        if image_format == 'JPG':
            image_format = 'JPEG'
        options = {'quality': 92} if image_format == 'JPEG' else {}
        stamped.save(output, format=image_format, **options)
    return output.getvalue()


def document_metadata(document):
    deliveries = ShipmentDelivery.query.filter_by(document_id=document.id).all()
    extracted_deliveries = [
        {
            'delivery_number': delivery.delivery_number,
            'goods_description': delivery.goods_description,
            'customer_name': delivery.customer_name,
            'destination': delivery.destination,
        }
        for delivery in deliveries
    ]
    return {
        'id': document.id,
        'tracking_number': document.shipment_tracking_number,
        'document_type': document.document_type,
        'filename': document.original_filename,
        'destination_validated': document.destination_validated,
        'ocr_destination': document.ocr_destination,
        'uploaded_at': document.uploaded_at.isoformat(),
        'security_stamped_at': document.security_stamped_at.isoformat() if document.security_stamped_at else None,
        'client_received_stamped_at': (
            document.client_received_stamped_at.isoformat()
            if document.client_received_stamped_at else None
        ),
        'extracted_deliveries': extracted_deliveries,
        'download_url': f'/api/shipments/{document.shipment_tracking_number}/documents/{document.id}/download',
    }


@shipments_bp.route('', methods=['GET'])
@jwt_required()
def list_shipments():
    user = get_request_user()
    if not user:
        return jsonify({'status': 'error', 'message': 'User not found.'}), 401
    if user.role not in ({'client', 'driver'} | ADMIN_ROLES):
        return jsonify({'status': 'error', 'message': 'This account cannot access shipment tracking.'}), 403

    shipments = Shipment.query.order_by(Shipment.created_at.desc()).all()
    visible = [shipment.to_dict() for shipment in shipments if shipment_visible_to(shipment, user)]
    return jsonify({'status': 'success', 'shipments': visible}), 200


@shipments_bp.route('/track/<tracking_number>', methods=['GET'])
@jwt_required()
def track_shipment(tracking_number):
    user = get_request_user()
    if not user:
        return jsonify({'status': 'error', 'message': 'User not found.'}), 401
    if user.role not in ({'client', 'driver'} | ADMIN_ROLES):
        return jsonify({'status': 'error', 'message': 'This account cannot access shipment tracking.'}), 403

    shipment = db.session.get(Shipment, tracking_number.strip().upper())
    if shipment is None or not shipment_visible_to(shipment, user):
        return jsonify({
            'status': 'error',
            'message': 'Shipment was not found or is not assigned to your account.',
        }), 404

    return jsonify({
        'status': 'success',
        'shipment': shipment.to_dict(),
    }), 200


@shipments_bp.route('/authorize-imei/<imei>', methods=['GET'])
@jwt_required()
def authorize_imei(imei):
    user = get_request_user()
    if not user or user.role not in ({'client', 'driver'} | ADMIN_ROLES):
        return jsonify({'status': 'error', 'message': 'Shipment access is not authorized.'}), 403

    shipment = Shipment.query.filter_by(imei=imei).first()
    if shipment is None or not shipment_visible_to(shipment, user):
        return jsonify({'status': 'error', 'message': 'Shipment access is not authorized.'}), 404
    return jsonify({'status': 'success', 'authorized': True}), 200


@shipments_bp.route('/<tracking_number>/assignment', methods=['PATCH'])
@jwt_required()
def update_shipment_assignment(tracking_number):
    admin = get_request_user()
    if not admin or admin.role not in ADMIN_ROLES:
        return jsonify({'status': 'error', 'message': 'Admin access is required.'}), 403

    shipment = db.session.get(Shipment, tracking_number.strip().upper())
    if shipment is None:
        return jsonify({'status': 'error', 'message': 'Shipment not found.'}), 404

    data = request.get_json(silent=True) or {}
    if 'company_name' not in data or 'driver_user_id' not in data or 'destination' not in data:
        return jsonify({
            'status': 'error',
            'message': "'company_name', 'driver_user_id', and 'destination' are required.",
        }), 400

    company_name = data['company_name']
    if not isinstance(company_name, str) or not company_name.strip():
        return jsonify({'status': 'error', 'message': 'Select a client company.'}), 400
    company_name = company_name.strip()
    company_exists = UserAccount.query.filter(
        db.func.lower(UserAccount.company_name) == company_name.lower(),
        UserAccount.role == 'client',
    ).first()
    if not company_exists:
        return jsonify({'status': 'error', 'message': 'No client account exists for that company.'}), 400
    destination = data['destination']
    if not isinstance(destination, str) or not destination.strip():
        return jsonify({'status': 'error', 'message': 'A shipment destination is required.'}), 400
    destination = destination.strip()
    if len(destination) > 160:
        return jsonify({'status': 'error', 'message': 'Shipment destination cannot exceed 160 characters.'}), 400

    driver_user_id = data['driver_user_id']
    if isinstance(driver_user_id, bool) or not isinstance(driver_user_id, int):
        return jsonify({'status': 'error', 'message': 'Select an assigned driver.'}), 400
    driver = db.session.get(UserAccount, driver_user_id)
    if not driver or driver.role != 'driver' or driver.account_status != 'active':
        return jsonify({'status': 'error', 'message': 'The selected account is not an active driver account.'}), 400

    shipment.company_name = company_name
    shipment.assigned_driver_id = driver.id
    shipment.destination = destination
    db.session.commit()
    return jsonify({'status': 'success', 'shipment': shipment.to_dict()}), 200


@shipments_bp.route('/<tracking_number>/status', methods=['PATCH'])
@jwt_required()
def update_shipment_status(tracking_number):
    user = get_request_user()
    if not user or user.role not in (ADMIN_ROLES | {'driver'}):
        return jsonify({'status': 'error', 'message': 'Only the assigned driver or an Admin can update shipment status.'}), 403

    shipment = db.session.get(Shipment, tracking_number.strip().upper())
    if not shipment or (user.role == 'driver' and shipment.assigned_driver_id != user.id):
        return jsonify({'status': 'error', 'message': 'Shipment was not found or is not assigned to this driver.'}), 404

    data = request.get_json(silent=True) or {}
    new_status = data.get('status')
    allowed_transitions = {
        'AWAITING_DISPATCH': {'IN_TRANSIT', 'BREAKDOWN'},
        'IN_TRANSIT': {'DELIVERED', 'BREAKDOWN'},
        'BREAKDOWN': {'IN_TRANSIT'},
        'DELIVERED': set(),
    }
    if new_status not in allowed_transitions:
        return jsonify({'status': 'error', 'message': 'Unsupported shipment status.'}), 400
    if new_status == shipment.status:
        return jsonify({'status': 'success', 'shipment': shipment.to_dict()}), 200
    if new_status not in allowed_transitions.get(shipment.status, set()):
        return jsonify({'status': 'error', 'message': f"Cannot change shipment status from {shipment.status} to {new_status}."}), 409

    documents = ShipmentDocument.query.filter_by(shipment_tracking_number=shipment.tracking_number).all()
    if new_status == 'IN_TRANSIT':
        document_types = {document.document_type for document in documents if document.destination_validated}
        required = {'proof_of_delivery', 'delivery_documents'}
        if not required.issubset(document_types):
            return jsonify({
                'status': 'error',
                'message': 'Upload and pass OCR destination validation for proof of delivery and delivery documents before dispatch.',
            }), 400
        shipment.departed_at = datetime.now(timezone.utc)
        for document in documents:
            if document.destination_validated:
                document.security_stamped_at = shipment.departed_at
    elif new_status == 'DELIVERED':
        if not any(document.document_type == 'proof_of_delivery' and document.destination_validated for document in documents):
            return jsonify({
                'status': 'error',
                'message': 'Upload and validate proof of delivery before marking goods as delivered.',
            }), 400
        shipment.arrived_at = datetime.now(timezone.utc)
        for document in documents:
            if document.destination_validated:
                document.security_stamped_at = document.security_stamped_at or shipment.departed_at or shipment.arrived_at
                document.client_received_stamped_at = shipment.arrived_at

    stamp_updates = []
    if new_status in {'IN_TRANSIT', 'DELIVERED'}:
        for document in documents:
            if not document.destination_validated:
                continue
            document.security_stamped_at = document.security_stamped_at or shipment.departed_at
            if new_status == 'DELIVERED':
                document.client_received_stamped_at = shipment.arrived_at
            path = os.path.join(current_app.config['SHIPMENT_DOCUMENTS_DIR'], document.storage_filename)
            if os.path.isfile(path):
                stamp_updates.append((
                    path,
                    stamp_existing_document(
                        path,
                        document.mime_type,
                        document.security_stamped_at,
                        document.client_received_stamped_at,
                    ),
                ))

    shipment.status = new_status
    db.session.commit()
    for path, stamped_bytes in stamp_updates:
        temporary_path = f'{path}.{uuid.uuid4().hex}.tmp'
        try:
            descriptor = os.open(temporary_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'wb') as stamped_file:
                stamped_file.write(stamped_bytes)
            os.replace(temporary_path, path)
        except OSError:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)
            current_app.logger.exception('Unable to apply shipment status stamp to a document.')
            return jsonify({
                'status': 'error',
                'message': 'Shipment status was updated, but a document stamp could not be applied. Contact an administrator.',
            }), 500
    return jsonify({'status': 'success', 'shipment': shipment.to_dict()}), 200


@shipments_bp.route('/<tracking_number>/documents', methods=['POST'])
@jwt_required()
def upload_shipment_documents(tracking_number):
    user = get_request_user()
    if not user or user.role not in ({'driver'} | ADMIN_ROLES):
        return jsonify({'status': 'error', 'message': 'Only the assigned driver or an Admin may upload shipment documents.'}), 403

    shipment = db.session.get(Shipment, tracking_number.strip().upper())
    if not shipment or (user.role == 'driver' and shipment.assigned_driver_id != user.id):
        return jsonify({'status': 'error', 'message': 'Shipment was not found or is not assigned to this driver.'}), 404

    proof_files = request.files.getlist('proof_of_delivery')
    delivery_files = request.files.getlist('delivery_documents')
    uploads = [
        ('proof_of_delivery', uploaded)
        for uploaded in proof_files if uploaded and uploaded.filename
    ] + [
        ('delivery_documents', uploaded)
        for uploaded in delivery_files if uploaded and uploaded.filename
    ]
    if not proof_files or not any(uploaded.filename for uploaded in proof_files) or \
            not delivery_files or not any(uploaded.filename for uploaded in delivery_files):
        return jsonify({
            'status': 'error',
            'message': 'Upload at least one proof-of-delivery file and one delivery document.',
        }), 400
    if len(uploads) > MAX_DOCUMENTS_PER_UPLOAD:
        return jsonify({'status': 'error', 'message': f'Upload no more than {MAX_DOCUMENTS_PER_UPLOAD} files at a time.'}), 400

    prepared = []
    try:
        for document_type, uploaded in uploads:
            contents = uploaded.read(MAX_DOCUMENT_BYTES + 1)
            mime_type, extension, pages = inspect_and_ocr_file(contents)
            try:
                ocr_text = '\n'.join(extract_ocr_text(page) for page in pages)
            except Exception as exc:
                current_app.logger.exception('OCR processing failed for a shipment document.')
                raise RuntimeError('OCR could not process this document. Check server OCR configuration and try a clearer scan.') from exc

            if not ocr_text.strip():
                raise ValueError(f'OCR could not read {secure_filename(uploaded.filename or "document")}. Upload a clearer scan.')
            extracted_deliveries = (
                extract_delivery_rows(ocr_text, shipment.destination)
                if document_type == 'delivery_documents' else []
            )
            destination_verified = destination_found(ocr_text, shipment.destination)
            if document_type == 'delivery_documents' and extracted_deliveries:
                recognized_destinations = [
                    delivery['destination'] for delivery in extracted_deliveries if delivery['destination']
                ]
                if recognized_destinations:
                    destination_verified = all(
                        destination_found(destination, shipment.destination)
                        for destination in recognized_destinations
                    )
            if not destination_verified:
                raise ValueError(
                    f"Destination validation failed for {secure_filename(uploaded.filename or 'document')}. "
                    "OCR could not read a delivery destination."
                )
            if document_type == 'delivery_documents' and not extracted_deliveries:
                raise ValueError(
                    f"OCR could not identify a delivery number in {secure_filename(uploaded.filename or 'document')}. "
                    "Include a clear delivery number on the scanned document."
                )

            now = datetime.now(timezone.utc)
            if shipment.status in {'IN_TRANSIT', 'DELIVERED'} and not shipment.departed_at:
                shipment.departed_at = now
            if shipment.status == 'DELIVERED' and not shipment.arrived_at:
                shipment.arrived_at = now
            security_stamped_at = shipment.departed_at or (now if shipment.status in {'IN_TRANSIT', 'DELIVERED'} else None)
            received_stamped_at = shipment.arrived_at or (now if shipment.status == 'DELIVERED' else None)
            stamped_bytes = stamped_document_bytes(
                pages,
                extension,
                security_stamped_at,
                received_stamped_at,
            )
            safe_filename = secure_filename(uploaded.filename or 'document')
            prepared.append({
                'id': str(uuid.uuid4()),
                'document_type': document_type,
                'original_filename': safe_filename[:255] or 'document',
                'storage_filename': f'{uuid.uuid4().hex}.{extension}',
                'mime_type': mime_type,
                'destination': (
                    extracted_deliveries[0]['destination']
                    if extracted_deliveries and extracted_deliveries[0]['destination']
                    else shipment.destination
                ),
                'security_stamped_at': security_stamped_at,
                'client_received_stamped_at': received_stamped_at,
                'uploaded_at': now,
                'contents': stamped_bytes,
                'extracted_deliveries': extracted_deliveries,
            })
    except ValueError as exc:
        return jsonify({'status': 'error', 'message': str(exc)}), 422
    except RuntimeError as exc:
        return jsonify({'status': 'error', 'message': str(exc)}), 503

    document_directory = current_app.config['SHIPMENT_DOCUMENTS_DIR']
    os.makedirs(document_directory, mode=0o700, exist_ok=True)
    os.chmod(document_directory, 0o700)
    written_paths = []
    documents = []
    try:
        for item in prepared:
            path = os.path.join(document_directory, item['storage_filename'])
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'wb') as document_file:
                document_file.write(item['contents'])
            written_paths.append(path)
            record = ShipmentDocument()
            record.id = item['id']
            record.shipment_tracking_number = shipment.tracking_number
            record.document_type = item['document_type']
            record.original_filename = item['original_filename']
            record.storage_filename = item['storage_filename']
            record.mime_type = item['mime_type']
            record.destination_validated = True
            record.ocr_destination = item['destination']
            record.security_stamped_at = item['security_stamped_at']
            record.client_received_stamped_at = item['client_received_stamped_at']
            record.uploaded_by_id = user.id
            record.uploaded_at = item['uploaded_at']
            db.session.add(record)
            documents.append(record)
            for delivery in item['extracted_deliveries']:
                delivery_record = ShipmentDelivery()
                delivery_record.shipment_tracking_number = shipment.tracking_number
                delivery_record.document_id = record.id
                delivery_record.delivery_number = delivery['delivery_number']
                delivery_record.goods_description = delivery['goods_description']
                delivery_record.customer_name = delivery['customer_name']
                delivery_record.destination = delivery['destination']
                delivery_record.created_at = item['uploaded_at']
                db.session.add(delivery_record)
        db.session.commit()
    except OSError:
        db.session.rollback()
        for path in written_paths:
            if os.path.exists(path):
                os.remove(path)
        current_app.logger.exception('Failed to store shipment documents.')
        return jsonify({'status': 'error', 'message': 'The server could not securely store the uploaded files.'}), 500
    except Exception:
        db.session.rollback()
        for path in written_paths:
            if os.path.exists(path):
                os.remove(path)
        current_app.logger.exception('Failed to save shipment document records.')
        return jsonify({'status': 'error', 'message': 'The server could not save the uploaded document records.'}), 500

    return jsonify({
        'status': 'success',
        'message': 'Documents passed destination OCR validation and were securely stamped.',
        'documents': [document_metadata(document) for document in documents],
        'shipment': shipment.to_dict(),
    }), 201


@shipments_bp.route('/<tracking_number>/documents', methods=['GET'])
@jwt_required()
def list_shipment_documents(tracking_number):
    user = get_request_user()
    if not user or user.role == 'driver':
        return jsonify({'status': 'error', 'message': 'Drivers cannot view shipment document files.'}), 403
    if user.role not in ({'client'} | ADMIN_ROLES):
        return jsonify({'status': 'error', 'message': 'Document access is not authorized.'}), 403

    shipment = db.session.get(Shipment, tracking_number.strip().upper())
    if not shipment or not shipment_visible_to(shipment, user):
        return jsonify({'status': 'error', 'message': 'Shipment was not found or is not assigned to your company.'}), 404
    documents = ShipmentDocument.query.filter_by(
        shipment_tracking_number=shipment.tracking_number
    ).order_by(ShipmentDocument.uploaded_at.desc()).all()
    return jsonify({'status': 'success', 'documents': [document_metadata(document) for document in documents]}), 200


@shipments_bp.route('/<tracking_number>/documents/<document_id>/download', methods=['GET'])
@jwt_required()
def download_shipment_document(tracking_number, document_id):
    user = get_request_user()
    if not user or user.role == 'driver':
        return jsonify({'status': 'error', 'message': 'Drivers cannot download shipment documents.'}), 403
    if user.role not in ({'client'} | ADMIN_ROLES):
        return jsonify({'status': 'error', 'message': 'Document download is not authorized.'}), 403

    shipment = db.session.get(Shipment, tracking_number.strip().upper())
    if not shipment or not shipment_visible_to(shipment, user):
        return jsonify({'status': 'error', 'message': 'Shipment was not found or is not assigned to your company.'}), 404
    document = db.session.get(ShipmentDocument, document_id)
    if not document or document.shipment_tracking_number != shipment.tracking_number:
        return jsonify({'status': 'error', 'message': 'Document was not found.'}), 404

    path = os.path.join(current_app.config['SHIPMENT_DOCUMENTS_DIR'], document.storage_filename)
    if not os.path.isfile(path):
        current_app.logger.error('Shipment document file is missing: %s', document.id)
        return jsonify({'status': 'error', 'message': 'The stored document is unavailable.'}), 404

    response = send_file(
        path,
        mimetype=document.mime_type,
        as_attachment=True,
        download_name=document.original_filename,
        conditional=False,
        max_age=0,
    )
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Content-Security-Policy'] = "sandbox; default-src 'none'"
    return response
