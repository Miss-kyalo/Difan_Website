import base64
import binascii
import hashlib
import hmac
import io
import json
import math
import os
import posixpath
import re
import secrets
import uuid
import zipfile
import xml.etree.ElementTree as ElementTree
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from threading import Lock
from urllib.parse import quote, urlsplit

import httpx
import numpy as np
import pymupdf as fitz
import qrcode
from cryptography.fernet import Fernet, InvalidToken
from flask import Blueprint, current_app, jsonify, request, send_file
from flask_jwt_extended import get_jwt_identity, jwt_required
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError
from rapidocr_onnxruntime import RapidOCR
from sqlalchemy.exc import IntegrityError
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
TRUCK_TYPES = {
    '3_TON': {'name': '3-Ton Light Canter', 'capacity': 3, 'base_fee': 4500, 'rate_per_ton_km': 18},
    '10_TON': {'name': '10-Ton Medium Rigid', 'capacity': 10, 'base_fee': 8500, 'rate_per_ton_km': 14},
    '15_TON': {'name': '15-Ton Heavy Tipper / Flatbed', 'capacity': 15, 'base_fee': 12000, 'rate_per_ton_km': 12},
    '30_TON': {'name': '30-Ton Multi-Axle Trailer', 'capacity': 30, 'base_fee': 22000, 'rate_per_ton_km': 9.5},
}
FREIGHT_HUBS = {
    'Athi River Industrial Zone': (-1.4583, 36.9806),
    'Nairobi Inland Container Depot (ICD)': (-1.3211, 36.8783),
    'Mombasa Port Terminal': (-4.0435, 39.6682),
    'Nakuru Freight Bypass': (-0.2833, 36.0667),
    'Eldoret Logistics Hub': (0.5143, 35.2698),
    'Kisumu Central Warehouse': (-0.0917, 34.7680),
}


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
    client_user_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=True, index=True)
    assigned_driver_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    departed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    arrived_at = db.Column(db.DateTime(timezone=True), nullable=True)
    delivery_due_at = db.Column(db.DateTime(timezone=True), nullable=True)
    truck_type = db.Column(db.String(20), nullable=True)
    pickup_address = db.Column(db.String(300), nullable=True)
    pickup_at = db.Column(db.DateTime(timezone=True), nullable=True)
    end_customer_name = db.Column(db.String(200), nullable=True)
    end_customer_address = db.Column(db.String(300), nullable=True)
    end_customer_phone = db.Column(db.String(40), nullable=True)
    end_customer_email = db.Column(db.String(254), nullable=True)
    public_tracking_token_hash = db.Column(db.String(64), nullable=True, unique=True, index=True)
    public_tracking_token_ciphertext = db.Column(db.String(255), nullable=True)
    public_tracking_expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    quoted_amount_kes = db.Column(db.Float, nullable=True)
    detention_rate_kes_per_hour = db.Column(db.Float, nullable=False, default=0)
    destination_change_request = db.Column(db.Text, nullable=True)
    assigned_driver = db.relationship('UserAccount', foreign_keys=[assigned_driver_id])
    client_account = db.relationship('UserAccount', foreign_keys=[client_user_id])
    documents = db.relationship('ShipmentDocument', backref='shipment', lazy=True, cascade='all, delete-orphan')
    deliveries = db.relationship('ShipmentDelivery', backref='shipment', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        documents = ShipmentDocument.query.filter_by(
            shipment_tracking_number=self.tracking_number,
        ).all()
        deliveries = ShipmentDelivery.query.filter_by(
            shipment_tracking_number=self.tracking_number,
        ).order_by(ShipmentDelivery.delivery_number).all()
        destination_change = (
            json.loads(self.destination_change_request)
            if self.destination_change_request else None
        )
        proof_of_delivery = ShipmentProofOfDelivery.query.filter_by(
            shipment_tracking_number=self.tracking_number,
        ).first()
        detention_charges = round(detention_total(self), 2)
        detention_vat = round(detention_charges * 0.16, 2)
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
            'client_user_id': self.client_user_id,
            'assigned_driver_name': (
                self.assigned_driver.display_name or self.assigned_driver.driver_name or self.assigned_driver.email
                if self.assigned_driver else None
            ),
            'destination_verified': any(document.destination_validated for document in documents),
            'departed_at': self.departed_at.isoformat() if self.departed_at else None,
            'arrived_at': self.arrived_at.isoformat() if self.arrived_at else None,
            'delivery_due_at': self.delivery_due_at.isoformat() if self.delivery_due_at else None,
            'truck_type': self.truck_type,
            'pickup_address': self.pickup_address,
            'pickup_at': self.pickup_at.isoformat() if self.pickup_at else None,
            'end_customer_name': self.end_customer_name,
            'end_customer_address': self.end_customer_address,
            'end_customer_phone': self.end_customer_phone,
            'end_customer_email': self.end_customer_email,
            'quoted_amount_kes': self.quoted_amount_kes,
            'detention_rate_kes_per_hour': self.detention_rate_kes_per_hour,
            'detention_charges_kes': detention_charges,
            'detention_vat_kes': detention_vat,
            'invoice_total_kes': round((self.quoted_amount_kes or 0) + detention_charges + detention_vat, 2),
            'geofence_events': [
                {
                    'site_type': event.site_type,
                    'event_type': event.event_type,
                    'facility_name': event.facility_name,
                    'recorded_at': event.recorded_at.isoformat(),
                    'accuracy_m': event.accuracy_m,
                }
                for event in ShipmentGeofenceEvent.query.filter_by(
                    shipment_tracking_number=self.tracking_number,
                ).order_by(ShipmentGeofenceEvent.recorded_at, ShipmentGeofenceEvent.id).all()
            ],
            'destination_change_pending': bool(self.destination_change_request),
            'destination_change': destination_change,
            'pod_signed_at': proof_of_delivery.signed_at.isoformat() if proof_of_delivery else None,
            'pod_signed_by': proof_of_delivery.signer_name if proof_of_delivery else None,
            'proof_of_delivery_download_url': (
                f'/api/shipments/{self.tracking_number}/proof-of-delivery'
                if proof_of_delivery else None
            ),
            'deliveries': [
                {
                    'id': delivery.id,
                    'delivery_number': delivery.delivery_number,
                    'goods_description': delivery.goods_description,
                    'customer_name': delivery.customer_name,
                    'destination': delivery.destination,
                }
                for delivery in deliveries
            ],
        }


class DriverLocation(db.Model):
    __tablename__ = 'driver_locations'

    driver_id = db.Column(
        db.Integer, db.ForeignKey('user_accounts.id'), primary_key=True,
    )
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    accuracy_m = db.Column(db.Float, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False)


class ClientDestinationRate(db.Model):
    __tablename__ = 'client_destination_rates'
    __table_args__ = (
        db.UniqueConstraint('client_user_id', 'origin', 'destination', 'truck_type', name='uq_client_destination_rate'),
    )

    id = db.Column(db.Integer, primary_key=True)
    client_user_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False, index=True)
    origin = db.Column(db.String(160), nullable=False)
    destination = db.Column(db.String(160), nullable=False)
    truck_type = db.Column(db.String(20), nullable=False)
    flat_rate_kes = db.Column(db.Float, nullable=False)
    source_filename = db.Column(db.String(255), nullable=False)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False)
    imported_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'client_user_id': self.client_user_id,
            'origin': self.origin,
            'destination': self.destination,
            'truck_type': self.truck_type,
            'truck_name': TRUCK_TYPES[self.truck_type]['name'],
            'flat_rate_kes': self.flat_rate_kes,
            'source_filename': self.source_filename,
            'imported_at': self.imported_at.isoformat(),
        }


class DestinationRate(db.Model):
    __tablename__ = 'shipment_destination_rates'
    __table_args__ = (
        db.UniqueConstraint('origin', 'destination', 'truck_type', name='uq_destination_rate_route_truck'),
    )

    id = db.Column(db.Integer, primary_key=True)
    origin = db.Column(db.String(160), nullable=False)
    destination = db.Column(db.String(160), nullable=False)
    truck_type = db.Column(db.String(20), nullable=False)
    flat_rate_kes = db.Column(db.Float, nullable=False)
    source_filename = db.Column(db.String(255), nullable=False)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False)
    imported_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    uploaded_by = db.relationship('UserAccount', foreign_keys=[uploaded_by_id])

    def to_dict(self):
        return {
            'id': self.id,
            'origin': self.origin,
            'destination': self.destination,
            'truck_type': self.truck_type,
            'truck_name': TRUCK_TYPES[self.truck_type]['name'],
            'flat_rate_kes': self.flat_rate_kes,
            'source_filename': self.source_filename,
            'imported_at': self.imported_at.isoformat(),
        }


class ShipmentProofOfDelivery(db.Model):
    __tablename__ = 'shipment_proof_of_delivery'

    id = db.Column(db.Integer, primary_key=True)
    shipment_tracking_number = db.Column(
        db.String(40), db.ForeignKey('shipments.tracking_number'), nullable=False, unique=True,
    )
    signer_user_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False)
    signer_name = db.Column(db.String(120), nullable=False)
    signature_png = db.Column(db.LargeBinary, nullable=False)
    signed_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


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


class ShipmentOperationalEvidence(db.Model):
    __tablename__ = 'shipment_operational_evidence'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    shipment_tracking_number = db.Column(
        db.String(40), db.ForeignKey('shipments.tracking_number'), nullable=False, index=True,
    )
    evidence_type = db.Column(db.String(24), nullable=False, index=True)
    filename = db.Column(db.String(255), nullable=False)
    contents = db.Column(db.LargeBinary, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    note = db.Column(db.String(1000), nullable=True)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False)
    uploaded_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    uploaded_by = db.relationship('UserAccount', foreign_keys=[uploaded_by_id])

    def to_dict(self):
        return {
            'id': self.id,
            'evidence_type': self.evidence_type,
            'filename': self.filename,
            'sha256': self.sha256,
            'note': self.note,
            'uploaded_at': self.uploaded_at.isoformat(),
            'download_url': (
                f'/api/shipments/{self.shipment_tracking_number}/operational-evidence/{self.id}'
            ),
        }


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


class ShipmentGeofenceEvent(db.Model):
    __tablename__ = 'shipment_geofence_events'

    id = db.Column(db.Integer, primary_key=True)
    shipment_tracking_number = db.Column(
        db.String(40), db.ForeignKey('shipments.tracking_number'), nullable=False, index=True,
    )
    site_type = db.Column(db.String(16), nullable=False)
    event_type = db.Column(db.String(16), nullable=False)
    facility_name = db.Column(db.String(160), nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    accuracy_m = db.Column(db.Float, nullable=True)
    recorded_by_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False)
    recorded_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    recorded_by = db.relationship('UserAccount', foreign_keys=[recorded_by_id])


class ShipmentDamageClaim(db.Model):
    __tablename__ = 'shipment_damage_claims'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    shipment_tracking_number = db.Column(
        db.String(40), db.ForeignKey('shipments.tracking_number'), nullable=False, index=True,
    )
    line_item_id = db.Column(db.Integer, db.ForeignKey('shipment_deliveries.id'), nullable=True)
    line_item_description = db.Column(db.String(300), nullable=False)
    details = db.Column(db.String(2000), nullable=False)
    filed_by_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False)
    filed_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    filed_by = db.relationship('UserAccount', foreign_keys=[filed_by_id])
    line_item = db.relationship('ShipmentDelivery', foreign_keys=[line_item_id])
    evidence = db.relationship(
        'ShipmentDamageEvidence', backref='claim', lazy=True, cascade='all, delete-orphan',
        order_by='ShipmentDamageEvidence.uploaded_at',
    )

    def to_dict(self):
        return {
            'id': self.id,
            'tracking_number': self.shipment_tracking_number,
            'line_item_id': self.line_item_id,
            'line_item_description': self.line_item_description,
            'details': self.details,
            'filed_by': self.filed_by.display_name or self.filed_by.driver_name or self.filed_by.email,
            'filed_by_role': self.filed_by.role,
            'filed_at': self.filed_at.isoformat(),
            'evidence': [item.to_dict() for item in self.evidence],
        }


class ShipmentDamageEvidence(db.Model):
    __tablename__ = 'shipment_damage_evidence'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    claim_id = db.Column(db.String(36), db.ForeignKey('shipment_damage_claims.id'), nullable=False, index=True)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=False)
    filename = db.Column(db.String(180), nullable=False)
    mime_type = db.Column(db.String(40), nullable=False)
    contents = db.Column(db.LargeBinary, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    uploaded_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    uploaded_by = db.relationship('UserAccount', foreign_keys=[uploaded_by_id])

    def to_dict(self):
        return {
            'id': self.id,
            'filename': self.filename,
            'mime_type': self.mime_type,
            'sha256': self.sha256,
            'uploaded_at': self.uploaded_at.isoformat(),
            'download_url': f'/api/shipments/claims/evidence/{self.id}',
        }


def detention_total(shipment, now=None):
    events = ShipmentGeofenceEvent.query.filter_by(
        shipment_tracking_number=shipment.tracking_number,
    ).order_by(ShipmentGeofenceEvent.recorded_at, ShipmentGeofenceEvent.id).all()
    open_arrivals = {}
    total_hours = 0.0
    current_time = now or datetime.now(timezone.utc)
    for event in events:
        recorded_at = event.recorded_at
        if recorded_at.tzinfo is None:
            recorded_at = recorded_at.replace(tzinfo=timezone.utc)
        key = event.site_type
        if event.event_type == 'ARRIVE':
            open_arrivals[key] = recorded_at
        elif event.event_type == 'DEPART' and key in open_arrivals:
            total_hours += max(0.0, (recorded_at - open_arrivals.pop(key)).total_seconds() / 3600)
    total_hours += sum(
        max(0.0, (current_time - arrived_at).total_seconds() / 3600)
        for arrived_at in open_arrivals.values()
    )
    return total_hours * (shipment.detention_rate_kes_per_hour or 0)


def detention_invoice_amount(shipment):
    detention = round(detention_total(shipment), 2)
    detention_vat = round(detention * 0.16, 2)
    base = shipment.quoted_amount_kes or 0
    return round(base + detention + detention_vat, 2), detention, detention_vat


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
        if shipment.client_user_id is not None:
            return shipment.client_user_id == user.id
        return bool(user.company_name and shipment.company_name and
                    user.company_name.strip().casefold() == shipment.company_name.strip().casefold())
    if user.role == 'driver':
        return shipment.assigned_driver_id == user.id
    return False


def create_public_tracking_link(shipment):
    now = datetime.now(timezone.utc)
    secret = current_app.config.get('SECRET_KEY')
    if not isinstance(secret, str) or not secret:
        raise RuntimeError('A stable application secret is required for customer tracking links.')
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode('utf-8')).digest())
    cipher = Fernet(key)
    expiry = shipment.public_tracking_expires_at
    if expiry and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if (
        shipment.public_tracking_token_hash
        and shipment.public_tracking_token_ciphertext
        and expiry
        and expiry > now
    ):
        try:
            token = cipher.decrypt(
                shipment.public_tracking_token_ciphertext.encode('ascii'),
            ).decode('ascii')
            if hmac.compare_digest(
                hashlib.sha256(token.encode('utf-8')).hexdigest(),
                shipment.public_tracking_token_hash,
            ):
                base_url = public_application_base_url()
                return f'{base_url}/tracking.html?token={quote(token)}'
        except (InvalidToken, UnicodeDecodeError):
            pass

    token = secrets.token_urlsafe(32)
    delivery_window = shipment.delivery_due_at
    if delivery_window and delivery_window.tzinfo is None:
        delivery_window = delivery_window.replace(tzinfo=timezone.utc)
    minimum_expiry = now + timedelta(days=30)
    schedule_expiry = (delivery_window + timedelta(days=7)) if delivery_window else minimum_expiry
    expiry = max(minimum_expiry, schedule_expiry)
    shipment.public_tracking_token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    shipment.public_tracking_token_ciphertext = cipher.encrypt(token.encode('ascii')).decode('ascii')
    shipment.public_tracking_expires_at = expiry
    base_url = public_application_base_url()
    return f'{base_url}/tracking.html?token={quote(token)}'


def public_application_base_url():
    base_url = (
        current_app.config.get('PUBLIC_APP_URL')
        or request.headers.get('Origin')
        or request.host_url
    ).strip().rstrip('/')
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {'http', 'https'}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError('PUBLIC_APP_URL must be an HTTP(S) origin without a path.')
    return base_url


def send_shipment_email(recipients, subject, message, attachment=None, attachment_name=None):
    api_key = current_app.config.get('SENDGRID_API_KEY')
    sender = current_app.config.get('MAIL_FROM_EMAIL')
    if not api_key or not sender:
        return {
            'status': 'not_sent',
            'message': 'Email delivery is not configured. Set SENDGRID_API_KEY and MAIL_FROM_EMAIL.',
        }
    recipients = list(dict.fromkeys(email for email in recipients if email))
    if not recipients:
        return {'status': 'not_sent', 'message': 'No recipient email address is on file.'}

    payload = {
        'personalizations': [{'to': [{'email': email}]} for email in recipients],
        'from': {'email': sender},
        'subject': subject,
        'content': [{'type': 'text/plain', 'value': message}],
    }
    if attachment is not None:
        payload['attachments'] = [{
            'content': base64.b64encode(attachment).decode('ascii'),
            'type': 'application/pdf',
            'filename': attachment_name,
            'disposition': 'attachment',
        }]
    try:
        response = httpx.post(
            'https://api.sendgrid.com/v3/mail/send',
            headers={'Authorization': f'Bearer {api_key}'},
            json=payload,
            timeout=10,
        )
    except httpx.HTTPError:
        current_app.logger.exception('Shipment email delivery failed for a shipment notification.')
        return {
            'status': 'failed',
            'message': 'Email delivery failed. Retry the notification from the shipment portal.',
        }
    if response.status_code != 202:
        current_app.logger.error(
            'Shipment email provider rejected a notification with HTTP %s.',
            response.status_code,
        )
        return {
            'status': 'failed',
            'message': 'The email provider rejected delivery. Check email configuration.',
        }
    return {'status': 'sent', 'message': 'Email delivered successfully.'}


def send_customer_tracking_email(shipment, tracking_url):
    if not shipment.end_customer_email:
        return {'status': 'not_sent', 'message': 'No end-customer email address is on file.'}
    message = (
        f'Hello {shipment.end_customer_name or "Customer"},\n\n'
        f'Your delivery from {shipment.company_name or "Difan Logistics"} is being handled by Difan Logistics.\n'
        f'Reference: {shipment.tracking_number}\n'
        f'Route: {shipment.origin} to {shipment.destination}\n\n'
        f'View shipment updates securely: {tracking_url}\n'
    )
    notification = send_shipment_email(
        [shipment.end_customer_email],
        f'Difan delivery tracking — {shipment.tracking_number}',
        message,
    )
    if notification['status'] == 'sent':
        notification['message'] = 'Secure tracking link emailed to the end customer.'
    elif notification['status'] == 'failed':
        notification['message'] = f"Tracking link was created, but {notification['message'].lower()}"
    else:
        notification['message'] = f"Tracking link was not emailed: {notification['message']}"
    return notification


def send_driver_assignment_email(shipment):
    driver = shipment.assigned_driver
    if not driver or not driver.email:
        return {'status': 'not_sent', 'message': 'The assigned driver has no email address on file.'}
    portal_url = public_application_base_url()
    message = (
        f'Hello {driver.display_name or driver.driver_name or "Driver"},\n\n'
        f'A shipment has been assigned to you.\n'
        f'Reference: {shipment.tracking_number}\n'
        f'Pickup: {shipment.pickup_address or shipment.origin}\n'
        f'Pickup time: {shipment.pickup_at.isoformat() if shipment.pickup_at else "Contact dispatch"}\n'
        f'Delivery: {shipment.end_customer_address or shipment.destination}\n'
        f'Cargo: {shipment.cargo_type} ({shipment.tonnage:g} tonnes)\n'
        f'Delivery deadline: {shipment.delivery_due_at.isoformat() if shipment.delivery_due_at else "Not specified"}\n\n'
        f'Sign in to the Difan driver portal for trip documents and updates: {portal_url}/index.html\n'
    )
    notification = send_shipment_email(
        [driver.email],
        f'Difan shipment assigned — {shipment.tracking_number}',
        message,
    )
    if notification['status'] == 'sent':
        notification['message'] = 'Shipment assignment emailed to the driver.'
    return notification


def build_signed_pod_pdf(shipment, proof):
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((48, 58), 'DIFAN LOGISTICS - PROOF OF DELIVERY', fontsize=16, fontname='helv')
    detail_lines = [
        f'Tracking reference: {shipment.tracking_number}',
        f'Client: {shipment.company_name or "Not specified"}',
        f'Cargo: {shipment.cargo_type} ({shipment.tonnage:g} tonnes)',
        f'Pickup: {shipment.origin}',
        f'Delivery: {shipment.destination}',
        f'End customer: {shipment.end_customer_name or "Not specified"}',
        f'Delivered at: {shipment.arrived_at.isoformat() if shipment.arrived_at else "Not recorded"}',
        f'Received and signed by: {proof.signer_name}',
        f'Signed at: {proof.signed_at.isoformat()}',
    ]
    detail_lines.append(
        f'Agreed delivery amount (including VAT): KES {shipment.quoted_amount_kes:,.2f}'
        if shipment.quoted_amount_kes is not None
        else 'Agreed delivery amount: Not recorded'
    )
    detention_amount = round(detention_total(shipment), 2)
    detail_lines.append(
        f'Detention: {round(detention_amount, 2):,.2f} KES before VAT; VAT at 16%: '
        f'{round(detention_amount * 0.16, 2):,.2f} KES; applied rate: '
        f'{(shipment.detention_rate_kes_per_hour or 0):,.2f} KES/hour'
    )
    detail_lines.append(
        f'Total invoice amount including detention and VAT: KES {detention_invoice_amount(shipment)[0]:,.2f}'
    )
    details = '\n'.join(' '.join(line.split()) for line in detail_lines)
    details = details.encode('latin-1', 'replace').decode('latin-1')
    page.insert_textbox(fitz.Rect(48, 85, 547, 320), details, fontsize=11, fontname='helv', lineheight=1.5)
    page.insert_text((48, 365), 'Customer signature', fontsize=11, fontname='helv')
    page.insert_image(fitz.Rect(48, 380, 330, 500), stream=proof.signature_png, keep_proportion=True)
    page.insert_textbox(
        fitz.Rect(48, 535, 547, 590),
        "This electronic proof of delivery records the receiving customer's confirmation of the cargo listed above.",
        fontsize=9,
        fontname='helv',
    )
    return pdf.tobytes()


def route_quote(origin, destination, truck_type, tonnage, client_user_id=None):
    if origin not in FREIGHT_HUBS or destination not in FREIGHT_HUBS:
        raise ValueError('Select a supported pickup and destination hub.')
    if origin == destination:
        raise ValueError('Pickup and destination hubs must be different.')
    truck = TRUCK_TYPES.get(truck_type)
    if truck is None:
        raise ValueError('Select a supported truck type.')
    if tonnage > truck['capacity']:
        raise ValueError(
            f"{truck['name']} supports up to {truck['capacity']} tonnes."
        )

    lat1, lon1 = FREIGHT_HUBS[origin]
    lat2, lon2 = FREIGHT_HUBS[destination]
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    haversine = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    distance_km = max(1, round(6371 * 2 * math.atan2(
        math.sqrt(haversine), math.sqrt(1 - haversine),
    ) * 1.22))
    destination_rate = None
    agreed_rate = None
    if client_user_id:
        agreed_rate = ClientDestinationRate.query.filter_by(
            client_user_id=client_user_id, origin=origin, destination=destination, truck_type=truck_type,
        ).first()
    if not agreed_rate:
        destination_rate = DestinationRate.query.filter_by(
            origin=origin,
            destination=destination,
            truck_type=truck_type,
        ).first()
    destination_rate = agreed_rate or destination_rate
    freight = (
        destination_rate.flat_rate_kes
        if destination_rate
        else truck['base_fee'] + tonnage * truck['rate_per_ton_km'] * distance_km
    )
    subtotal_kes = round(freight, 2)
    vat_kes = round(subtotal_kes * 0.16, 2)
    return {
        'truck_type': truck_type,
        'truck_name': truck['name'],
        'distance_km': distance_km,
        'tonnage': tonnage,
        'subtotal_kes': subtotal_kes,
        'vat_kes': vat_kes,
        'total_kes': round(subtotal_kes + vat_kes, 2),
        'pricing_source': (
            'agreed_client_rate' if agreed_rate
            else 'uploaded_destination_rate' if destination_rate else 'standard_estimate'
        ),
    }


def distance_between_coordinates_km(latitude_a, longitude_a, latitude_b, longitude_b):
    phi_a = math.radians(latitude_a)
    phi_b = math.radians(latitude_b)
    delta_phi = math.radians(latitude_b - latitude_a)
    delta_lambda = math.radians(longitude_b - longitude_a)
    haversine = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi_a) * math.cos(phi_b) * math.sin(delta_lambda / 2) ** 2
    )
    return 6371 * 2 * math.atan2(
        math.sqrt(haversine),
        math.sqrt(max(0.0, 1 - haversine)),
    )


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


def read_xlsx_rows(contents):
    try:
        with zipfile.ZipFile(io.BytesIO(contents)) as workbook:
            members = workbook.infolist()
            if len(members) > 2000 or sum(member.file_size for member in members) > 50 * 1024 * 1024:
                raise ValueError('The Excel workbook expands beyond the safe import limit.')

            shared_strings = []
            if 'xl/sharedStrings.xml' in workbook.namelist():
                shared_root = ElementTree.fromstring(workbook.read('xl/sharedStrings.xml'))
                for item in shared_root:
                    shared_strings.append(''.join(
                        text_node.text or ''
                        for text_node in item.iter()
                        if text_node.tag.endswith('}t')
                    ))

            workbook_root = ElementTree.fromstring(workbook.read('xl/workbook.xml'))
            first_sheet = next(
                node for node in workbook_root.iter()
                if node.tag.endswith('}sheet')
            )
            relationship_id = next(
                value for key, value in first_sheet.attrib.items()
                if key.endswith('}id')
            )
            relationships = ElementTree.fromstring(workbook.read('xl/_rels/workbook.xml.rels'))
            target = next(
                relation.attrib['Target']
                for relation in relationships
                if relation.attrib.get('Id') == relationship_id
            )
            sheet_path = posixpath.normpath(posixpath.join('xl', target))
            if not sheet_path.startswith('xl/worksheets/') or sheet_path not in workbook.namelist():
                raise ValueError('The first Excel sheet could not be read.')
            sheet_root = ElementTree.fromstring(workbook.read(sheet_path))
            rows = []
            for row in (node for node in sheet_root.iter() if node.tag.endswith('}row')):
                values = []
                for cell in (node for node in row if node.tag.endswith('}c')):
                    reference = cell.attrib.get('r', '')
                    letters = re.match(r'[A-Z]+', reference)
                    if not letters:
                        continue
                    column_index = 0
                    for letter in letters.group(0):
                        column_index = column_index * 26 + ord(letter) - ord('A') + 1
                    while len(values) < column_index:
                        values.append('')
                    value_node = next((node for node in cell if node.tag.endswith('}v')), None)
                    value = value_node.text if value_node is not None else ''
                    if cell.attrib.get('t') == 's' and value:
                        value = shared_strings[int(value)]
                    elif cell.attrib.get('t') == 'inlineStr':
                        value = ''.join(
                            node.text or ''
                            for node in cell.iter()
                            if node.tag.endswith('}t')
                        )
                    values[column_index - 1] = value or ''
                if any(str(value).strip() for value in values):
                    rows.append(values)
            return rows
    except (zipfile.BadZipFile, KeyError, IndexError, StopIteration, ElementTree.ParseError, ValueError) as error:
        if isinstance(error, ValueError) and str(error):
            raise
        raise ValueError('The Excel workbook is invalid or could not be read.') from error


def validate_destination_rate(candidate, row_number):
    origin = candidate.get('origin')
    destination = candidate.get('destination')
    truck_type = candidate.get('truck_type')
    raw_rate = candidate.get('flat_rate_kes')
    errors = []
    if not isinstance(origin, str) or origin.strip() not in FREIGHT_HUBS:
        errors.append('Origin must match a supported freight hub.')
    if not isinstance(destination, str) or destination.strip() not in FREIGHT_HUBS:
        errors.append('Destination must match a supported freight hub.')
    if isinstance(truck_type, str):
        truck_type = truck_type.strip().upper().replace('-', '_').replace(' ', '_')
    if truck_type not in TRUCK_TYPES:
        errors.append('Truck type must be one of the supported truck types.')
    try:
        if isinstance(raw_rate, bool):
            raise ValueError
        rate = float(str(raw_rate).replace(',', '').replace('KES', '').strip())
        if not math.isfinite(rate) or rate <= 0 or rate > 1_000_000_000:
            raise ValueError
    except (TypeError, ValueError):
        rate = None
        errors.append('Rate must be a positive amount in KES.')
    if isinstance(origin, str) and isinstance(destination, str) and origin.strip() == destination.strip():
        errors.append('Origin and destination must be different.')
    return {
        'row_number': row_number,
        'origin': origin.strip() if isinstance(origin, str) else '',
        'destination': destination.strip() if isinstance(destination, str) else '',
        'truck_type': truck_type if isinstance(truck_type, str) else '',
        'flat_rate_kes': rate,
        'valid': not errors,
        'errors': errors,
    }


def parse_rate_rows(rows):
    if not rows:
        raise ValueError('No rate rows were found in the uploaded file.')
    headers = [normalize_text(str(value)) for value in rows[0]]
    aliases = {
        'origin': {'origin', 'pickup', 'from', 'pickuphub'},
        'destination': {'destination', 'dropoff', 'to', 'destinationhub'},
        'truck_type': {'trucktype', 'truck', 'equipmenttype'},
        'flat_rate_kes': {'flatratekes', 'ratekes', 'rate', 'pricekes', 'amountkes'},
    }
    indexes = {
        name: next((index for index, header in enumerate(headers) if header in choices), None)
        for name, choices in aliases.items()
    }
    if any(index is None for index in indexes.values()):
        raise ValueError('Include columns for origin, destination, truck_type, and flat_rate_kes.')
    candidates = []
    for row_number, row in enumerate(rows[1:], start=2):
        if not any(str(value).strip() for value in row):
            continue
        candidates.append(validate_destination_rate({
            name: row[index] if index < len(row) else ''
            for name, index in indexes.items()
        }, row_number))
    if not candidates:
        raise ValueError('No destination rate rows were found below the header.')
    return candidates


def parse_pdf_rate_rows(ocr_text):
    rows = []
    for line in ocr_text.splitlines():
        line = line.strip()
        if not line:
            continue
        delimiter = next((value for value in ('|', ';', '\t') if value in line), None)
        if delimiter:
            rows.append([value.strip() for value in line.split(delimiter)])
    return parse_rate_rows(rows)


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
        'mime_type': document.mime_type,
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


def persist_generated_pdf(shipment, user, document_type, filename, contents):
    directory = current_app.config['SHIPMENT_DOCUMENTS_DIR']
    os.makedirs(directory, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)

    storage_filename = f'{uuid.uuid4().hex}.pdf'
    path = os.path.join(directory, storage_filename)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, 'wb') as document_file:
            document_file.write(contents)
    except OSError:
        if os.path.exists(path):
            os.remove(path)
        raise

    existing = ShipmentDocument.query.filter_by(
        shipment_tracking_number=shipment.tracking_number,
        document_type=document_type,
    ).first()
    previous_path = (
        os.path.join(directory, existing.storage_filename)
        if existing else None
    )
    document = existing or ShipmentDocument()
    document.id = document.id or str(uuid.uuid4())
    document.shipment_tracking_number = shipment.tracking_number
    document.document_type = document_type
    document.original_filename = filename
    document.storage_filename = storage_filename
    document.mime_type = 'application/pdf'
    document.destination_validated = False
    document.ocr_destination = None
    document.security_stamped_at = None
    document.client_received_stamped_at = None
    document.uploaded_by_id = user.id
    document.uploaded_at = datetime.now(timezone.utc)
    db.session.add(document)
    return document, path, previous_path


def cleanup_generated_pdf(path, previous_path=None):
    if os.path.exists(path):
        os.remove(path)
    if previous_path and previous_path != path and os.path.exists(previous_path):
        os.remove(previous_path)


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


def accessible_claim_user(shipment, user):
    return bool(
        user and (
            user.role in ADMIN_ROLES
            or (
                user.role == 'client'
                and shipment_visible_to(shipment, user)
            )
            or (
                user.role == 'driver'
                and shipment.assigned_driver_id == user.id
            )
        )
    )


def read_damage_photo(uploaded):
    if not uploaded or not uploaded.filename:
        raise ValueError('Attach a photo of the reported damage.')
    original_name = secure_filename(uploaded.filename)[:180] or 'damage-evidence'
    contents = uploaded.read(5 * 1024 * 1024 + 1)
    if not contents or len(contents) > 5 * 1024 * 1024:
        raise ValueError('Damage photos must be between 1 byte and 5 MB.')
    try:
        with Image.open(io.BytesIO(contents)) as image:
            if image.format not in {'JPEG', 'PNG', 'WEBP'}:
                raise ValueError('Use a JPEG, PNG, or WEBP damage photo.')
            image.load()
            if image.width > 5000 or image.height > 5000:
                raise ValueError('The damage photo dimensions are too large.')
            output = io.BytesIO()
            image.convert('RGB').save(output, format='JPEG', quality=88, optimize=True)
            return original_name, 'image/jpeg', output.getvalue()
    except (Image.DecompressionBombError, OSError, UnidentifiedImageError) as error:
        raise ValueError('The damage photo is invalid or unreadable.') from error


@shipments_bp.route('/<tracking_number>/claims', methods=['GET', 'POST'])
@jwt_required()
def shipment_damage_claims(tracking_number):
    user = get_request_user()
    shipment = db.session.get(Shipment, tracking_number.strip().upper())
    if not shipment or not accessible_claim_user(shipment, user):
        return jsonify({'status': 'error', 'message': 'Shipment was not found for this account.'}), 404

    if request.method == 'GET':
        claims = ShipmentDamageClaim.query.filter_by(
            shipment_tracking_number=shipment.tracking_number,
        ).order_by(ShipmentDamageClaim.filed_at.desc()).all()
        return jsonify({'status': 'success', 'claims': [claim.to_dict() for claim in claims]}), 200

    if user.role not in {'client', 'driver'}:
        return jsonify({'status': 'error', 'message': 'Only the shipper or assigned driver can file a damage claim.'}), 403
    if shipment.status not in {'IN_TRANSIT', 'BREAKDOWN', 'DELIVERED'}:
        return jsonify({'status': 'error', 'message': 'Damage claims can be filed after dispatch starts.'}), 409

    item_id_value = request.form.get('line_item_id', '').strip()
    item_description = request.form.get('line_item_description', '').strip()
    details = request.form.get('details', '').strip()
    if len(details) < 5 or len(details) > 2000:
        return jsonify({'status': 'error', 'message': 'Describe the damage in 5 to 2,000 characters.'}), 400
    if len(item_description) > 300:
        return jsonify({'status': 'error', 'message': 'Line item description cannot exceed 300 characters.'}), 400
    line_item = None
    if item_id_value:
        try:
            line_item = db.session.get(ShipmentDelivery, int(item_id_value))
        except ValueError:
            line_item = None
        if not line_item or line_item.shipment_tracking_number != shipment.tracking_number:
            return jsonify({'status': 'error', 'message': 'Select a line item belonging to this shipment.'}), 400
    if line_item:
        item_description = (
            f'{line_item.delivery_number} — {line_item.goods_description or line_item.destination or "Delivery item"}'
        )[:300]
    if not item_description:
        return jsonify({'status': 'error', 'message': 'Select a delivery line item or enter its description.'}), 400

    try:
        filename, mime_type, photo = read_damage_photo(request.files.get('photo'))
    except ValueError as error:
        return jsonify({'status': 'error', 'message': str(error)}), 400
    claim = ShipmentDamageClaim(
        shipment_tracking_number=shipment.tracking_number,
        line_item_id=line_item.id if line_item else None,
        line_item_description=item_description,
        details=details,
        filed_by_id=user.id,
    )
    claim.evidence.append(ShipmentDamageEvidence(
        uploaded_by_id=user.id,
        filename=filename,
        mime_type=mime_type,
        contents=photo,
        sha256=hashlib.sha256(photo).hexdigest(),
    ))
    db.session.add(claim)
    db.session.commit()
    return jsonify({'status': 'success', 'claim': claim.to_dict()}), 201


@shipments_bp.post('/claims/<claim_id>/evidence')
@jwt_required()
def add_damage_claim_evidence(claim_id):
    user = get_request_user()
    claim = db.session.get(ShipmentDamageClaim, claim_id)
    shipment = db.session.get(Shipment, claim.shipment_tracking_number) if claim else None
    if not claim or not shipment or not accessible_claim_user(shipment, user):
        return jsonify({'status': 'error', 'message': 'Damage claim was not found for this account.'}), 404
    if user.role not in {'client', 'driver'}:
        return jsonify({'status': 'error', 'message': 'Only the shipper or assigned driver can add claim evidence.'}), 403
    details = request.form.get('details', '').strip()
    if len(details) > 2000:
        return jsonify({'status': 'error', 'message': 'Evidence note cannot exceed 2,000 characters.'}), 400
    try:
        filename, mime_type, photo = read_damage_photo(request.files.get('photo'))
    except ValueError as error:
        return jsonify({'status': 'error', 'message': str(error)}), 400
    evidence = ShipmentDamageEvidence(
        claim_id=claim.id,
        uploaded_by_id=user.id,
        filename=filename,
        mime_type=mime_type,
        contents=photo,
        sha256=hashlib.sha256(photo).hexdigest(),
    )
    db.session.add(evidence)
    db.session.commit()
    return jsonify({'status': 'success', 'evidence': evidence.to_dict()}), 201


@shipments_bp.get('/claims/evidence/<evidence_id>')
@jwt_required()
def download_damage_claim_evidence(evidence_id):
    user = get_request_user()
    evidence = db.session.get(ShipmentDamageEvidence, evidence_id)
    claim = evidence.claim if evidence else None
    shipment = db.session.get(Shipment, claim.shipment_tracking_number) if claim else None
    if not evidence or not claim or not shipment or not accessible_claim_user(shipment, user):
        return jsonify({'status': 'error', 'message': 'Damage evidence was not found for this account.'}), 404
    response = send_file(
        io.BytesIO(evidence.contents),
        mimetype=evidence.mime_type,
        as_attachment=True,
        download_name=evidence.filename,
        max_age=0,
    )
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@shipments_bp.post('/<tracking_number>/geofence-events')
@jwt_required()
def record_shipment_geofence_event(tracking_number):
    user = get_request_user()
    shipment = db.session.get(Shipment, tracking_number.strip().upper())
    if not shipment or not user or not (
        user.role in ADMIN_ROLES
        or (user.role == 'driver' and shipment.assigned_driver_id == user.id)
    ):
        return jsonify({'status': 'error', 'message': 'Shipment was not found for this driver account.'}), 404
    if user.role == 'driver' and user.employment_status != 'ACTIVE':
        return jsonify({'status': 'error', 'message': 'Only active drivers can record shipment geofence events.'}), 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'status': 'error', 'message': 'Provide a geofence event.'}), 400
    site_type = data.get('site_type')
    event_type = data.get('event_type')
    if site_type not in {'PICKUP', 'DESTINATION'} or event_type not in {'ARRIVE', 'DEPART'}:
        return jsonify({'status': 'error', 'message': 'Choose pickup or destination, and arrival or departure.'}), 400
    facility_name = shipment.origin if site_type == 'PICKUP' else shipment.destination
    coordinates = FREIGHT_HUBS.get(facility_name)
    if not coordinates:
        return jsonify({'status': 'error', 'message': 'This shipment hub has no configured geofence coordinates.'}), 409
    try:
        latitude = float(data.get('latitude'))
        longitude = float(data.get('longitude'))
        accuracy_m = float(data.get('accuracy_m'))
        if not math.isfinite(latitude) or not math.isfinite(longitude):
            raise ValueError
        if not math.isfinite(accuracy_m) or not 0 <= accuracy_m <= 750:
            return jsonify({
                'status': 'error',
                'message': 'GPS accuracy must be within 750 m to verify a geofence event.',
            }), 400
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Allow location access and provide valid GPS coordinates.'}), 400

    lat1, lon1 = map(math.radians, coordinates)
    lat2, lon2 = math.radians(latitude), math.radians(longitude)
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    distance_m = 6371000 * 2 * math.asin(math.sqrt(
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    ))
    if distance_m > 750:
        return jsonify({
            'status': 'error',
            'message': f'You are {round(distance_m)} m from the {facility_name} geofence; move within 750 m to record this event.',
        }), 400
    last_event = ShipmentGeofenceEvent.query.filter_by(
        shipment_tracking_number=shipment.tracking_number,
        site_type=site_type,
    ).order_by(ShipmentGeofenceEvent.recorded_at.desc(), ShipmentGeofenceEvent.id.desc()).first()
    if event_type == 'ARRIVE' and last_event and last_event.event_type == 'ARRIVE':
        return jsonify({'status': 'error', 'message': 'An arrival is already open; record departure first.'}), 409
    if event_type == 'DEPART' and (not last_event or last_event.event_type != 'ARRIVE'):
        return jsonify({'status': 'error', 'message': 'Record an arrival before recording departure.'}), 409
    if site_type == 'PICKUP' and shipment.status not in {'ASSIGNED', 'AWAITING_DISPATCH', 'IN_TRANSIT', 'BREAKDOWN'}:
        return jsonify({'status': 'error', 'message': 'Pickup geofence is unavailable for this shipment status.'}), 409
    if site_type == 'DESTINATION' and shipment.status not in {'IN_TRANSIT', 'BREAKDOWN', 'DELIVERED'}:
        return jsonify({'status': 'error', 'message': 'Destination geofence is available after dispatch starts.'}), 409
    event = ShipmentGeofenceEvent(
        shipment_tracking_number=shipment.tracking_number,
        site_type=site_type,
        event_type=event_type,
        facility_name=facility_name,
        latitude=latitude,
        longitude=longitude,
        accuracy_m=accuracy_m,
        recorded_by_id=user.id,
    )
    db.session.add(event)
    db.session.commit()
    invoice_amount = None
    if event_type == 'DEPART':
        from backend.routes.portal import ShipmentFinance

        finance = db.session.get(ShipmentFinance, shipment.tracking_number)
        if finance and shipment.quoted_amount_kes is not None:
            invoice_amount, _, _ = detention_invoice_amount(shipment)
            finance.invoice_amount_kes = invoice_amount
            finance.updated_by_id = user.id
            finance.updated_at = event.recorded_at
            db.session.commit()
    return jsonify({
        'status': 'success',
        'message': f'{event_type.title()} recorded for {facility_name}.',
        'event': {
            'site_type': event.site_type,
            'event_type': event.event_type,
            'facility_name': event.facility_name,
            'recorded_at': event.recorded_at.isoformat(),
            'accuracy_m': event.accuracy_m,
        },
        'detention_charges_kes': round(detention_total(shipment), 2),
        'invoice_amount_kes': invoice_amount,
    }), 201


@shipments_bp.get('/clients')
@jwt_required()
def list_shipment_clients():
    user = get_request_user()
    if not user or user.role not in (ADMIN_ROLES | {'driver'}):
        return jsonify({'status': 'error', 'message': 'Only dispatch staff and assigned drivers can select a client company.'}), 403
    if user.role == 'driver' and user.employment_status != 'ACTIVE':
        return jsonify({'status': 'error', 'message': 'Your driver status does not allow shipment assignment.'}), 403

    clients = UserAccount.query.filter_by(role='client', account_status='active').order_by(
        UserAccount.company_name, UserAccount.email,
    ).all()
    return jsonify({
        'status': 'success',
        'clients': [
            {
                'id': client.id,
                'company_name': client.company_name,
                'email': client.email,
                'display_name': client.display_name,
            }
            for client in clients
            if client.company_name and client.company_name.strip()
        ],
    }), 200


def resolve_rate_client(raw_client_id):
    # No client id means the standard rate sheet used by the quote page.
    if raw_client_id in (None, '', 'standard'):
        return None, None
    try:
        client = db.session.get(UserAccount, int(raw_client_id))
    except (TypeError, ValueError):
        client = None
    if not client or client.role != 'client':
        return None, (jsonify({'status': 'error', 'message': 'Select a valid client account.'}), 400)
    return client, None


@shipments_bp.get('/rates')
@jwt_required()
def list_destination_rates():
    user = get_request_user()
    if not user or user.role not in ADMIN_ROLES:
        return jsonify({'status': 'error', 'message': 'Only HR and management can view imported destination rates.'}), 403
    client, error = resolve_rate_client(request.args.get('client_id'))
    if error:
        return error
    model = ClientDestinationRate if client else DestinationRate
    query = model.query
    if client:
        query = query.filter_by(client_user_id=client.id)
    rates = query.order_by(model.origin, model.destination, model.truck_type).all()
    return jsonify({'status': 'success', 'rates': [rate.to_dict() for rate in rates]}), 200


@shipments_bp.post('/rates/preview')
@jwt_required()
def preview_destination_rates():
    user = get_request_user()
    if not user or user.role not in ADMIN_ROLES:
        return jsonify({'status': 'error', 'message': 'Only HR and management can import destination rates.'}), 403
    uploaded = request.files.get('file')
    if not uploaded or not uploaded.filename:
        return jsonify({'status': 'error', 'message': 'Select an Excel or PDF rate sheet to preview.'}), 400
    filename = secure_filename(uploaded.filename)[:255]
    extension = os.path.splitext(filename)[1].lower()
    contents = uploaded.read(MAX_DOCUMENT_BYTES + 1)
    if not contents or len(contents) > MAX_DOCUMENT_BYTES:
        return jsonify({'status': 'error', 'message': 'Rate sheets must be between 1 byte and 12 MB.'}), 400
    try:
        if extension == '.xlsx':
            rows = parse_rate_rows(read_xlsx_rows(contents))
        elif extension == '.pdf':
            _, _, pages = inspect_and_ocr_file(contents)
            try:
                ocr_text = '\n'.join(extract_ocr_text(page) for page in pages)
            except Exception as error:
                current_app.logger.exception('Rate-sheet OCR processing failed.')
                raise ValueError('OCR could not read this PDF. Upload a clearer scan with the documented rate columns.') from error
            rows = parse_pdf_rate_rows(ocr_text)
        else:
            raise ValueError('Upload an .xlsx Excel workbook or a PDF rate sheet.')
    except ValueError as error:
        return jsonify({'status': 'error', 'message': str(error)}), 400

    return jsonify({
        'status': 'success',
        'source_filename': filename,
        'rows': rows,
        'valid_rows': sum(row['valid'] for row in rows),
        'invalid_rows': sum(not row['valid'] for row in rows),
        'message': 'Review every extracted rate. Nothing is applied until you confirm the import.',
    }), 200


@shipments_bp.post('/rates')
@jwt_required()
def import_destination_rates():
    user = get_request_user()
    if not user or user.role not in ADMIN_ROLES:
        return jsonify({'status': 'error', 'message': 'Only HR and management can import destination rates.'}), 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get('rows'), list):
        return jsonify({'status': 'error', 'message': 'Review and submit the parsed destination rate rows.'}), 400
    source_filename = data.get('source_filename')
    if not isinstance(source_filename, str) or not source_filename.strip() or len(source_filename) > 255:
        return jsonify({'status': 'error', 'message': 'The rate sheet filename is missing or too long.'}), 400
    if not 1 <= len(data['rows']) <= 500:
        return jsonify({'status': 'error', 'message': 'Import between 1 and 500 rate rows at a time.'}), 400

    validated = []
    route_keys = set()
    for row_number, candidate in enumerate(data['rows'], start=1):
        if not isinstance(candidate, dict):
            return jsonify({'status': 'error', 'message': f'Rate row {row_number} is invalid.'}), 400
        row = validate_destination_rate(candidate, row_number)
        if not row['valid']:
            return jsonify({
                'status': 'error',
                'message': f"Rate row {row_number} is invalid: {' '.join(row['errors'])}",
            }), 400
        key = (row['origin'], row['destination'], row['truck_type'])
        if key in route_keys:
            return jsonify({'status': 'error', 'message': f'Rate row {row_number} duplicates a route in this import.'}), 400
        route_keys.add(key)
        validated.append(row)

    client, client_error = resolve_rate_client(data.get('client_id'))
    if client_error:
        return client_error
    model = ClientDestinationRate if client else DestinationRate
    scope = {'client_user_id': client.id} if client else {}
    imported_at = datetime.now(timezone.utc)
    imported_rates = []
    for row in validated:
        rate = model.query.filter_by(
            origin=row['origin'],
            destination=row['destination'],
            truck_type=row['truck_type'],
            **scope,
        ).first()
        if rate is None:
            rate = model(
                origin=row['origin'],
                destination=row['destination'],
                truck_type=row['truck_type'],
                **scope,
            )
            db.session.add(rate)
        rate.flat_rate_kes = row['flat_rate_kes']
        rate.source_filename = secure_filename(source_filename)[:255] or 'imported-rate-sheet'
        rate.uploaded_by_id = user.id
        rate.imported_at = imported_at
        imported_rates.append(rate)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Destination rate import could not be committed.')
        return jsonify({'status': 'error', 'message': 'The destination rate import failed. No rates were applied.'}), 500
    return jsonify({
        'status': 'success',
        'message': f'{len(validated)} destination rate(s) imported.',
        'rates': [rate.to_dict() for rate in imported_rates],
    }), 201


@shipments_bp.post('/quote')
@jwt_required()
def quote_shipment():
    user = get_request_user()
    if not user or user.role != 'client':
        return jsonify({'status': 'error', 'message': 'Only client accounts can request freight quotes.'}), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'status': 'error', 'message': 'A JSON shipment request is required.'}), 400
    try:
        if isinstance(data.get('tonnage'), bool):
            raise ValueError('Cargo weight must be a number of tonnes.')
        tonnage = float(data.get('tonnage'))
        if not math.isfinite(tonnage) or tonnage <= 0 or tonnage > 100:
            raise ValueError('Cargo weight must be between 0 and 100 tonnes.')
        quote = route_quote(
            data.get('origin'),
            data.get('destination'),
            data.get('truck_type'),
            tonnage,
            client_user_id=user.id,
        )
    except (TypeError, ValueError) as error:
        return jsonify({'status': 'error', 'message': str(error)}), 400
    return jsonify({'status': 'success', 'quote': quote}), 200


@shipments_bp.post('/requests')
@jwt_required()
def create_shipment_request():
    user = get_request_user()
    if not user or user.role != 'client':
        return jsonify({'status': 'error', 'message': 'Only client accounts can request a truck.'}), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'status': 'error', 'message': 'A JSON shipment request is required.'}), 400

    text_fields = (
        'origin', 'destination', 'cargo_type', 'truck_type', 'pickup_address',
        'pickup_at', 'end_customer_name', 'end_customer_address', 'end_customer_phone',
    )
    if any(not isinstance(data.get(field), str) or not data[field].strip() for field in text_fields):
        return jsonify({'status': 'error', 'message': 'Complete all shipment, customer, pickup, and schedule details.'}), 400
    if any(len(data[field].strip()) > limit for field, limit in (
        ('origin', 160), ('destination', 160), ('cargo_type', 160),
        ('pickup_address', 300), ('end_customer_name', 200),
        ('end_customer_address', 300), ('end_customer_phone', 40),
    )):
        return jsonify({'status': 'error', 'message': 'One or more shipment details exceed the supported length.'}), 400
    customer_email = data.get('end_customer_email')
    if isinstance(customer_email, str) and not customer_email.strip():
        customer_email = None
    if customer_email is not None:
        if (
            not isinstance(customer_email, str)
            or len(customer_email.strip()) > 254
            or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', customer_email.strip())
        ):
            return jsonify({'status': 'error', 'message': 'Enter a valid end-customer email address.'}), 400
    try:
        if isinstance(data.get('tonnage'), bool):
            raise ValueError('Cargo weight must be a number of tonnes.')
        tonnage = float(data.get('tonnage'))
        if not math.isfinite(tonnage) or tonnage <= 0 or tonnage > 100:
            raise ValueError('Cargo weight must be between 0 and 100 tonnes.')
        quote = route_quote(
            data['origin'].strip(),
            data['destination'].strip(),
            data['truck_type'],
            tonnage,
            client_user_id=user.id,
        )
        pickup_at = datetime.fromisoformat(data['pickup_at'].strip().replace('Z', '+00:00'))
        if pickup_at.tzinfo is None:
            raise ValueError('Pickup date and time must include a time zone.')
        if pickup_at <= datetime.now(timezone.utc):
            raise ValueError('Pickup date and time must be in the future.')
        delivery_due_at = None
        due_value = data.get('delivery_due_at')
        if due_value:
            if not isinstance(due_value, str):
                raise ValueError('Delivery deadline must be a date and time.')
            delivery_due_at = datetime.fromisoformat(due_value.strip().replace('Z', '+00:00'))
            if delivery_due_at.tzinfo is None or delivery_due_at <= pickup_at:
                raise ValueError('Delivery deadline must include a time zone and be after pickup.')
    except (TypeError, ValueError) as error:
        return jsonify({'status': 'error', 'message': str(error) or 'Enter a valid pickup date and time.'}), 400

    shipment = Shipment(
        tracking_number=f"DL-{secrets.token_hex(6).upper()}",
        status='REQUESTED',
        origin=data['origin'].strip(),
        destination=data['destination'].strip(),
        cargo_type=data['cargo_type'].strip(),
        tonnage=tonnage,
        company_name=user.company_name,
        client_user_id=user.id,
        truck_type=data['truck_type'],
        pickup_address=data['pickup_address'].strip(),
        pickup_at=pickup_at,
        delivery_due_at=delivery_due_at,
        end_customer_name=data['end_customer_name'].strip(),
        end_customer_address=data['end_customer_address'].strip(),
        end_customer_phone=data['end_customer_phone'].strip(),
        end_customer_email=customer_email.strip() if customer_email else None,
        quoted_amount_kes=quote['total_kes'],
    )
    db.session.add(shipment)
    db.session.commit()
    return jsonify({
        'status': 'success',
        'message': 'Truck request submitted. Difan Logistics will prepare your shipment.',
        'shipment': shipment.to_dict(),
        'quote': quote,
    }), 201


@shipments_bp.post('/<tracking_number>/destination-change')
@jwt_required()
def request_destination_change(tracking_number):
    user = get_request_user()
    shipment = db.session.get(Shipment, tracking_number.strip().upper())
    if not user or not shipment or not shipment_visible_to(shipment, user):
        return jsonify({'status': 'error', 'message': 'Shipment was not found for this account.'}), 404
    if user.role != 'client':
        return jsonify({'status': 'error', 'message': 'Only the client can request a destination change.'}), 403
    if shipment.status not in {'REQUESTED', 'PLANNED', 'ASSIGNED'}:
        return jsonify({'status': 'error', 'message': 'Destination changes are unavailable after the trip starts.'}), 409
    if shipment.destination_change_request:
        return jsonify({'status': 'error', 'message': 'A destination change is already awaiting your decision.'}), 409

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'status': 'error', 'message': 'A JSON destination change is required.'}), 400
    destination = data.get('destination')
    address = data.get('end_customer_address')
    if not isinstance(destination, str) or not destination.strip() or not isinstance(address, str) or not address.strip():
        return jsonify({'status': 'error', 'message': 'Enter the new destination hub and delivery address.'}), 400
    if len(address.strip()) > 300:
        return jsonify({'status': 'error', 'message': 'The new delivery address cannot exceed 300 characters.'}), 400
    try:
        quote = route_quote(
            shipment.origin, destination.strip(), shipment.truck_type, shipment.tonnage,
            client_user_id=shipment.client_user_id,
        )
    except ValueError as error:
        return jsonify({'status': 'error', 'message': str(error)}), 400

    request_details = {
        'destination': destination.strip(),
        'end_customer_address': address.strip()[:300],
        'quoted_amount_kes': quote['total_kes'],
        'requested_by_id': user.id,
        'requested_at': datetime.now(timezone.utc).isoformat(),
    }
    shipment.destination_change_request = json.dumps(request_details)
    db.session.commit()
    return jsonify({
        'status': 'success',
        'message': 'Review the updated rate and accept or reject this destination change.',
        'change': request_details,
        'previous_quote_kes': shipment.quoted_amount_kes,
        'quote': quote,
        'decision_required': True,
    }), 200


@shipments_bp.post('/<tracking_number>/destination-change/decision')
@jwt_required()
def decide_destination_change(tracking_number):
    user = get_request_user()
    shipment = db.session.get(Shipment, tracking_number.strip().upper())
    if not user or not shipment or not shipment_visible_to(shipment, user):
        return jsonify({'status': 'error', 'message': 'Shipment was not found for this account.'}), 404
    if user.role != 'client':
        return jsonify({'status': 'error', 'message': 'Only the client can decide on a destination change.'}), 403
    if not shipment.destination_change_request:
        return jsonify({'status': 'error', 'message': 'There is no destination change awaiting a decision.'}), 409

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get('accept'), bool):
        return jsonify({'status': 'error', 'message': 'Choose whether to accept the new destination and rate.'}), 400
    change = json.loads(shipment.destination_change_request)
    if data['accept']:
        shipment.destination = change['destination']
        shipment.end_customer_address = change['end_customer_address']
        shipment.quoted_amount_kes = change['quoted_amount_kes']
        message = 'Destination change accepted and the revised rate applied.'
    else:
        message = 'Destination change rejected. The original destination and rate are unchanged.'
    shipment.destination_change_request = None
    db.session.commit()
    return jsonify({'status': 'success', 'message': message, 'shipment': shipment.to_dict()}), 200


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


@shipments_bp.get('/public-tracking/<token>')
def public_track_shipment(token):
    if len(token) < 40 or len(token) > 128:
        return jsonify({'status': 'error', 'message': 'Tracking link is invalid or expired.'}), 404
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    shipment = Shipment.query.filter_by(public_tracking_token_hash=token_hash).first()
    if not shipment or not shipment.public_tracking_expires_at:
        return jsonify({'status': 'error', 'message': 'Tracking link is invalid or expired.'}), 404
    expiry = shipment.public_tracking_expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry <= datetime.now(timezone.utc):
        return jsonify({'status': 'error', 'message': 'Tracking link is invalid or expired.'}), 404

    response = jsonify({
        'status': 'success',
        'tracking': {
            'tracking_number': shipment.tracking_number,
            'company_name': shipment.company_name or 'Difan Logistics',
            'shipment_status': shipment.status,
            'origin': shipment.origin,
            'destination': shipment.destination,
            'delivery_due_at': shipment.delivery_due_at.isoformat() if shipment.delivery_due_at else None,
            'departed_at': shipment.departed_at.isoformat() if shipment.departed_at else None,
            'arrived_at': shipment.arrived_at.isoformat() if shipment.arrived_at else None,
            'last_updated_at': (
                shipment.arrived_at or shipment.departed_at or shipment.created_at
            ).isoformat(),
        },
    })
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response, 200


@shipments_bp.post('/driver-location')
@jwt_required()
def update_driver_location():
    user = get_request_user()
    if not user or user.role != 'driver':
        return jsonify({'status': 'error', 'message': 'Only drivers may update their dispatch location.'}), 403
    if user.account_status != 'active' or user.employment_status != 'ACTIVE':
        return jsonify({'status': 'error', 'message': 'Your driver account must be active to update dispatch location.'}), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'status': 'error', 'message': 'A JSON location update is required.'}), 400
    coordinates = []
    for key in ('latitude', 'longitude', 'accuracy_m'):
        value = data.get(key)
        if isinstance(value, bool):
            return jsonify({'status': 'error', 'message': 'GPS coordinates and accuracy must be numeric.'}), 400
        try:
            number = float(value)
        except (TypeError, ValueError):
            return jsonify({'status': 'error', 'message': 'GPS coordinates and accuracy must be numeric.'}), 400
        if not math.isfinite(number):
            return jsonify({'status': 'error', 'message': 'GPS coordinates and accuracy must be finite.'}), 400
        coordinates.append(number)
    latitude, longitude, accuracy_m = coordinates
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180 or not 0 <= accuracy_m <= 1000:
        return jsonify({'status': 'error', 'message': 'GPS coordinates or accuracy are outside supported limits.'}), 400

    location = db.session.get(DriverLocation, user.id)
    if location is None:
        location = DriverLocation(driver_id=user.id)
        db.session.add(location)
    location.latitude = latitude
    location.longitude = longitude
    location.accuracy_m = accuracy_m
    location.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({
        'status': 'success',
        'updated_at': location.updated_at.isoformat(),
        'message': 'Your current GPS position is available to dispatch for 30 minutes.',
    }), 200


@shipments_bp.get('/driver-load-board')
@jwt_required()
def driver_load_board():
    user = get_request_user()
    if not user or user.role != 'driver':
        return jsonify({'status': 'error', 'message': 'Only drivers may view compatible loads.'}), 403
    if user.account_status != 'active' or user.employment_status != 'ACTIVE':
        return jsonify({
            'status': 'success',
            'eligible': False,
            'message': 'Your driver status does not allow load acceptance.',
            'loads': [],
        }), 200

    from backend.routes.fleet import FleetVehicle, vehicle_dispatch_block_reason

    vehicle = FleetVehicle.query.filter_by(assigned_driver_id=user.id).first()
    if not vehicle:
        return jsonify({
            'status': 'success',
            'eligible': False,
            'message': 'A fleet vehicle must be assigned before you can accept loads.',
            'loads': [],
        }), 200
    block_reason = vehicle_dispatch_block_reason(user)
    if block_reason or vehicle.status in {'MAINTENANCE', 'BREAKDOWN'}:
        return jsonify({
            'status': 'success',
            'eligible': False,
            'message': block_reason or f'{vehicle.registration} is unavailable for dispatch.',
            'loads': [],
        }), 200
    if Shipment.query.filter(
        Shipment.assigned_driver_id == user.id,
        Shipment.status.in_({'IN_TRANSIT', 'BREAKDOWN'}),
    ).first():
        return jsonify({
            'status': 'success',
            'eligible': False,
            'message': 'Finish or resolve your active trip before accepting another load.',
            'loads': [],
        }), 200

    now = datetime.now(timezone.utc)
    location = db.session.get(DriverLocation, user.id)
    location_time = location.updated_at if location else None
    if location_time and location_time.tzinfo is None:
        location_time = location_time.replace(tzinfo=timezone.utc)
    fresh_location = (
        location
        if location_time and now - location_time <= timedelta(minutes=30)
        else None
    )
    previous_destinations = {
        shipment.destination.strip().casefold()
        for shipment in Shipment.query.filter(
            Shipment.assigned_driver_id == user.id,
            Shipment.status.in_({'IN_TRANSIT', 'BREAKDOWN', 'DELIVERED'}),
        ).all()
    }
    candidates = Shipment.query.filter(
        Shipment.assigned_driver_id.is_(None),
        Shipment.status.in_({'REQUESTED', 'PLANNED', 'ASSIGNED', 'AWAITING_DISPATCH'}),
        Shipment.truck_type == vehicle.truck_type,
        Shipment.tonnage <= vehicle.capacity_tonnes,
    ).all()
    loads = []
    for shipment in candidates:
        hub_coordinates = FREIGHT_HUBS.get(shipment.origin)
        distance = (
            distance_between_coordinates_km(
                fresh_location.latitude,
                fresh_location.longitude,
                hub_coordinates[0],
                hub_coordinates[1],
            )
            if fresh_location and hub_coordinates else None
        )
        loads.append({
            'tracking_number': shipment.tracking_number,
            'company_name': shipment.company_name,
            'origin': shipment.origin,
            'pickup_address': shipment.pickup_address,
            'pickup_at': shipment.pickup_at.isoformat() if shipment.pickup_at else None,
            'destination': shipment.destination,
            'cargo_type': shipment.cargo_type,
            'tonnage': shipment.tonnage,
            'truck_type': shipment.truck_type,
            'delivery_due_at': shipment.delivery_due_at.isoformat() if shipment.delivery_due_at else None,
            'distance_to_pickup_km': round(distance, 1) if distance is not None else None,
            'backhaul': shipment.origin.strip().casefold() in previous_destinations,
        })
    loads.sort(key=lambda item: (
        item['distance_to_pickup_km'] is None,
        item['distance_to_pickup_km'] if item['distance_to_pickup_km'] is not None else math.inf,
        item['pickup_at'] or '',
        item['tracking_number'],
    ))
    return jsonify({
        'status': 'success',
        'eligible': True,
        'vehicle_registration': vehicle.registration,
        'location_updated_at': fresh_location.updated_at.isoformat() if fresh_location else None,
        'message': (
            'Loads are sorted by distance from your recently shared GPS location.'
            if fresh_location
            else 'Share a fresh GPS location to sort these loads by pickup proximity.'
        ),
        'loads': loads,
    }), 200


@shipments_bp.post('/driver-load-board/<tracking_number>/accept')
@jwt_required()
def accept_driver_load(tracking_number):
    user = get_request_user()
    if not user or user.role != 'driver' or user.account_status != 'active':
        return jsonify({'status': 'error', 'message': 'An active driver account is required to accept a load.'}), 403
    if user.employment_status != 'ACTIVE':
        return jsonify({'status': 'error', 'message': 'Your driver status does not allow load acceptance.'}), 403

    shipment = db.session.get(Shipment, tracking_number.strip().upper())
    if not shipment:
        return jsonify({'status': 'error', 'message': 'Load not found.'}), 404
    from backend.routes.fleet import FleetVehicle, vehicle_dispatch_block_reason

    vehicle = FleetVehicle.query.filter_by(assigned_driver_id=user.id).first()
    if not vehicle:
        return jsonify({'status': 'error', 'message': 'A fleet vehicle must be assigned before you can accept loads.'}), 409
    block_reason = vehicle_dispatch_block_reason(user)
    if block_reason or vehicle.status in {'MAINTENANCE', 'BREAKDOWN'}:
        return jsonify({
            'status': 'error',
            'message': block_reason or f'{vehicle.registration} is unavailable for dispatch.',
        }), 409
    if (
        shipment.truck_type != vehicle.truck_type
        or shipment.tonnage > vehicle.capacity_tonnes
    ):
        return jsonify({'status': 'error', 'message': 'This load is not compatible with your assigned vehicle.'}), 409
    if Shipment.query.filter(
        Shipment.assigned_driver_id == user.id,
        Shipment.status.in_({'IN_TRANSIT', 'BREAKDOWN'}),
    ).first():
        return jsonify({'status': 'error', 'message': 'Finish or resolve your active trip before accepting another load.'}), 409

    updated = Shipment.query.filter(
        Shipment.tracking_number == shipment.tracking_number,
        Shipment.assigned_driver_id.is_(None),
        Shipment.status.in_({'REQUESTED', 'PLANNED', 'ASSIGNED', 'AWAITING_DISPATCH'}),
    ).update({
        Shipment.assigned_driver_id: user.id,
        Shipment.status: 'AWAITING_DISPATCH',
    }, synchronize_session=False)
    if updated != 1:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': 'Another dispatcher or driver has already claimed this load.'}), 409
    db.session.commit()
    db.session.refresh(shipment)
    return jsonify({
        'status': 'success',
        'message': f'Load {shipment.tracking_number} accepted. Review the trip BOL before departure.',
        'shipment': shipment.to_dict(),
    }), 200


@shipments_bp.post('/<tracking_number>/auto-assignment')
@jwt_required()
def auto_assign_nearest_driver(tracking_number):
    manager = get_request_user()
    if not manager or manager.role not in ADMIN_ROLES:
        return jsonify({'status': 'error', 'message': 'Admin access is required.'}), 403
    shipment = db.session.get(Shipment, tracking_number.strip().upper())
    if not shipment:
        return jsonify({'status': 'error', 'message': 'Shipment not found.'}), 404
    if shipment.assigned_driver_id is not None or shipment.status not in {
        'REQUESTED', 'PLANNED', 'ASSIGNED', 'AWAITING_DISPATCH',
    }:
        return jsonify({'status': 'error', 'message': 'This shipment is no longer available for automatic assignment.'}), 409
    if shipment.truck_type not in TRUCK_TYPES or shipment.origin not in FREIGHT_HUBS:
        return jsonify({'status': 'error', 'message': 'A supported equipment type and pickup hub are required for auto-matching.'}), 400

    from backend.routes.fleet import FleetVehicle, vehicle_dispatch_block_reason

    now = datetime.now(timezone.utc)
    candidates = []
    for vehicle in FleetVehicle.query.filter(
        FleetVehicle.truck_type == shipment.truck_type,
        FleetVehicle.capacity_tonnes >= shipment.tonnage,
        FleetVehicle.status.notin_({'MAINTENANCE', 'BREAKDOWN'}),
    ).all():
        driver = vehicle.assigned_driver
        if (
            not driver
            or driver.role != 'driver'
            or driver.account_status != 'active'
            or driver.employment_status != 'ACTIVE'
            or vehicle_dispatch_block_reason(driver)
            or Shipment.query.filter(
                Shipment.assigned_driver_id == driver.id,
                Shipment.status.in_({'IN_TRANSIT', 'BREAKDOWN'}),
            ).first()
        ):
            continue
        location = db.session.get(DriverLocation, driver.id)
        if not location:
            continue
        location_time = location.updated_at
        if location_time.tzinfo is None:
            location_time = location_time.replace(tzinfo=timezone.utc)
        if now - location_time > timedelta(minutes=30):
            continue
        pickup_hub = FREIGHT_HUBS[shipment.origin]
        distance = distance_between_coordinates_km(
            location.latitude,
            location.longitude,
            pickup_hub[0],
            pickup_hub[1],
        )
        candidates.append((distance, driver.id, driver, location))
    if not candidates:
        return jsonify({
            'status': 'error',
            'message': 'No compatible, dispatch-eligible driver has shared a fresh GPS location in the last 30 minutes.',
        }), 409
    candidates.sort(key=lambda candidate: (candidate[0], candidate[1]))
    distance, driver_id, driver, _location = candidates[0]
    updated = Shipment.query.filter(
        Shipment.tracking_number == shipment.tracking_number,
        Shipment.assigned_driver_id.is_(None),
        Shipment.status.in_({'REQUESTED', 'PLANNED', 'ASSIGNED', 'AWAITING_DISPATCH'}),
    ).update({
        Shipment.assigned_driver_id: driver_id,
        Shipment.status: 'AWAITING_DISPATCH',
    }, synchronize_session=False)
    if updated != 1:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': 'This shipment was assigned by another dispatcher.'}), 409
    db.session.commit()
    db.session.refresh(shipment)
    driver_notification = send_driver_assignment_email(shipment)
    return jsonify({
        'status': 'success',
        'shipment': shipment.to_dict(),
        'driver': {
            'id': driver.id,
            'name': driver.display_name or driver.driver_name or driver.email,
        },
        'distance_to_pickup_km': round(distance, 1),
        'driver_notification': driver_notification,
    }), 200


@shipments_bp.post('/<tracking_number>/tracking-link')
@jwt_required()
def create_shipment_tracking_link(tracking_number):
    user = get_request_user()
    shipment = db.session.get(Shipment, tracking_number.strip().upper())
    if (
        not user
        or user.role not in ({'client', 'driver'} | ADMIN_ROLES)
        or not shipment
        or not shipment_visible_to(shipment, user)
    ):
        return jsonify({'status': 'error', 'message': 'Shipment tracking is not available to this account.'}), 404

    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return jsonify({'status': 'error', 'message': 'A JSON tracking-link request is required.'}), 400
    send_email = data.get('send_email', False)
    if not isinstance(send_email, bool):
        return jsonify({'status': 'error', 'message': 'The send_email option must be true or false.'}), 400
    if send_email and not shipment.end_customer_email:
        return jsonify({
            'status': 'error',
            'message': 'Add an end-customer email to the shipment before sending a tracking link.',
        }), 400
    if send_email and (
        not current_app.config.get('SENDGRID_API_KEY')
        or not current_app.config.get('MAIL_FROM_EMAIL')
    ):
        return jsonify({
            'status': 'error',
            'message': 'Tracking email delivery is not configured. Set SENDGRID_API_KEY and MAIL_FROM_EMAIL.',
        }), 503

    tracking_url = create_public_tracking_link(shipment)
    db.session.commit()
    notification = send_customer_tracking_email(shipment, tracking_url) if send_email else None
    return jsonify({
        'status': 'success',
        'tracking_url': tracking_url,
        'expires_at': shipment.public_tracking_expires_at.isoformat(),
        'notification': notification,
        'message': notification['message'] if notification else 'Secure tracking link created.',
    }), 200


@shipments_bp.get('/<tracking_number>/bill-of-lading')
@jwt_required()
def download_bill_of_lading(tracking_number):
    user = get_request_user()
    shipment = db.session.get(Shipment, tracking_number.strip().upper())
    if (
        not user
        or user.role not in ({'client', 'driver'} | ADMIN_ROLES)
        or not shipment
        or not shipment_visible_to(shipment, user)
    ):
        return jsonify({'status': 'error', 'message': 'Bill of lading is not available to this account.'}), 404

    tracking_url = create_public_tracking_link(shipment)
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_text((48, 56), 'DIFAN LOGISTICS - BILL OF LADING', fontsize=17, fontname='helv')
    detail_lines = [
        f'Shipment reference: {shipment.tracking_number}',
        f'Shipper: {shipment.company_name or "Not specified"}',
        f'Pickup: {shipment.origin}',
        f'Pickup address: {shipment.pickup_address or "Not specified"}',
        f'Pickup schedule: {shipment.pickup_at.isoformat() if shipment.pickup_at else "Not specified"}',
        f'Delivery hub: {shipment.destination}',
        f'Delivery address: {shipment.end_customer_address or "Not specified"}',
        f'Receiver: {shipment.end_customer_name or "Not specified"}',
        f'Receiver phone: {shipment.end_customer_phone or "Not specified"}',
        f'Receiver email: {shipment.end_customer_email or "Not specified"}',
        f'Cargo: {shipment.cargo_type} ({shipment.tonnage:g} tonnes)',
        f'Truck type: {shipment.truck_type or "Not specified"}',
        f'Required delivery deadline: {shipment.delivery_due_at.isoformat() if shipment.delivery_due_at else "Not specified"}',
        f'Freight amount (KES, including VAT): {shipment.quoted_amount_kes:,.2f}' if shipment.quoted_amount_kes is not None else 'Freight amount: Not specified',
        f'Shipment status: {shipment.status.replace("_", " ")}',
    ]
    details = '\n'.join(' '.join(line.split()) for line in detail_lines)
    details = details.encode('latin-1', 'replace').decode('latin-1')
    page.insert_textbox(fitz.Rect(48, 82, 390, 510), details, fontsize=10, fontname='helv', lineheight=1.6)
    page.insert_text((48, 575), 'Carrier / driver signature', fontsize=10, fontname='helv')
    page.draw_line((48, 610), (370, 610), color=(0.2, 0.2, 0.2), width=0.8)
    page.insert_text((48, 655), 'Receiver signature', fontsize=10, fontname='helv')
    page.draw_line((48, 690), (370, 690), color=(0.2, 0.2, 0.2), width=0.8)
    qr_image = io.BytesIO()
    qrcode.make(tracking_url).save(qr_image, format='PNG')
    page.insert_text((425, 565), 'Secure tracking', fontsize=10, fontname='helv')
    page.insert_image(fitz.Rect(420, 585, 540, 705), stream=qr_image.getvalue())
    page.insert_textbox(
        fitz.Rect(48, 745, 540, 790),
        'The QR code opens the current shipment status. The customer link is private to the recipient and expires after the delivery window.',
        fontsize=8,
        fontname='helv',
    )
    filename = f'{shipment.tracking_number}-bill-of-lading.pdf'
    try:
        _document, path, previous_path = persist_generated_pdf(
            shipment, user, 'trip_bol', filename, pdf.tobytes(),
        )
        db.session.commit()
    except OSError:
        db.session.rollback()
        if 'path' in locals() and os.path.exists(path):
            os.remove(path)
        current_app.logger.exception('Unable to store the shipment bill of lading.')
        return jsonify({'status': 'error', 'message': 'The bill of lading could not be saved to the shipment record.'}), 500
    except Exception:
        db.session.rollback()
        if 'path' in locals() and os.path.exists(path):
            os.remove(path)
        current_app.logger.exception('Unable to save the shipment bill of lading record.')
        return jsonify({'status': 'error', 'message': 'The bill of lading could not be saved to the shipment record.'}), 500
    if previous_path and previous_path != path and os.path.exists(previous_path):
        os.remove(previous_path)
    with open(path, 'rb') as document_file:
        contents = document_file.read()
    response = send_file(
        io.BytesIO(contents),
        mimetype='application/pdf',
        as_attachment=request.args.get('preview') != '1',
        download_name=filename,
        conditional=False,
        max_age=0,
    )
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


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
    if shipment.status in {'IN_TRANSIT', 'BREAKDOWN', 'DELIVERED'}:
        return jsonify({'status': 'error', 'message': 'Dispatch terms cannot be changed after the trip starts.'}), 409

    data = request.get_json(silent=True) or {}
    if 'company_name' not in data or 'driver_user_id' not in data or 'destination' not in data:
        return jsonify({
            'status': 'error',
            'message': "'company_name', 'driver_user_id', and 'destination' are required.",
        }), 400

    client_user_id = data.get('client_user_id')
    if client_user_id is not None:
        if isinstance(client_user_id, bool) or not isinstance(client_user_id, int):
            return jsonify({'status': 'error', 'message': 'Select a client account.'}), 400
        client_account = db.session.get(UserAccount, client_user_id)
        if (
            not client_account
            or client_account.role != 'client'
            or client_account.account_status != 'active'
            or not client_account.company_name
            or not client_account.company_name.strip()
        ):
            return jsonify({'status': 'error', 'message': 'Select an active client account.'}), 400
        company_name = client_account.company_name
        if isinstance(data.get('company_name'), str) and data['company_name'].strip().casefold() != company_name.strip().casefold():
            return jsonify({'status': 'error', 'message': 'The selected company does not match the client account.'}), 400
    else:
        company_name = data['company_name']
        if not isinstance(company_name, str) or not company_name.strip():
            return jsonify({'status': 'error', 'message': 'Select a client company.'}), 400
        company_name = company_name.strip()
        client_account = UserAccount.query.filter(
            db.func.lower(UserAccount.company_name) == company_name.lower(),
            UserAccount.role == 'client',
            UserAccount.account_status == 'active',
        ).first()
        if not client_account:
            return jsonify({'status': 'error', 'message': 'No active client account exists for that company.'}), 400
    destination = data['destination']
    if not isinstance(destination, str) or not destination.strip():
        return jsonify({'status': 'error', 'message': 'A shipment destination is required.'}), 400
    destination = destination.strip()
    if len(destination) > 160:
        return jsonify({'status': 'error', 'message': 'Shipment destination cannot exceed 160 characters.'}), 400
    rate_value = data.get('detention_rate_kes_per_hour', 0)
    if isinstance(rate_value, bool):
        return jsonify({'status': 'error', 'message': 'Detention rate must be a non-negative hourly amount.'}), 400
    try:
        detention_rate = float(rate_value)
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Detention rate must be a non-negative hourly amount.'}), 400
    if not math.isfinite(detention_rate) or detention_rate < 0 or detention_rate > 1_000_000:
        return jsonify({'status': 'error', 'message': 'Detention rate must be between KES 0 and KES 1,000,000 per hour.'}), 400

    driver_user_id = data['driver_user_id']
    if isinstance(driver_user_id, bool) or not isinstance(driver_user_id, int):
        return jsonify({'status': 'error', 'message': 'Select an assigned driver.'}), 400
    driver = db.session.get(UserAccount, driver_user_id)
    if (
        not driver or driver.role != 'driver' or driver.account_status != 'active'
        or driver.employment_status != 'ACTIVE'
    ):
        return jsonify({
            'status': 'error',
            'message': 'The selected driver is not active and available for dispatch.',
        }), 400
    from backend.routes.fleet import vehicle_dispatch_block_reason

    certificate_block = vehicle_dispatch_block_reason(driver)
    if certificate_block:
        return jsonify({'status': 'error', 'message': certificate_block}), 400

    shipment.company_name = company_name
    shipment.client_user_id = client_account.id
    shipment.assigned_driver_id = driver.id
    shipment.destination = destination
    shipment.detention_rate_kes_per_hour = detention_rate
    if shipment.status in {'REQUESTED', 'PLANNED', 'ASSIGNED'}:
        shipment.status = 'AWAITING_DISPATCH'
    db.session.commit()
    driver_notification = send_driver_assignment_email(shipment)
    return jsonify({
        'status': 'success',
        'shipment': shipment.to_dict(),
        'driver_notification': driver_notification,
    }), 200


@shipments_bp.route('/<tracking_number>/status', methods=['PATCH'])
@jwt_required()
def update_shipment_status(tracking_number):
    user = get_request_user()
    if not user or user.role not in (ADMIN_ROLES | {'driver'}):
        return jsonify({'status': 'error', 'message': 'Only the assigned driver or an Admin can update shipment status.'}), 403

    shipment = db.session.get(Shipment, tracking_number.strip().upper())
    if not shipment or (user.role == 'driver' and shipment.assigned_driver_id != user.id):
        return jsonify({'status': 'error', 'message': 'Shipment was not found or is not assigned to this driver.'}), 404

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'status': 'error', 'message': 'A JSON shipment status update is required.'}), 400
    new_status = data.get('status')
    allowed_transitions = {
        'ASSIGNED': {'IN_TRANSIT', 'BREAKDOWN'},
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
    if (
        user.role == 'driver'
        and new_status == 'IN_TRANSIT'
        and user.employment_status != 'ACTIVE'
    ):
        return jsonify({
            'status': 'error',
            'message': 'Your driver status does not allow starting or resuming a dispatch. Safety reports remain available.',
        }), 403
    if new_status == 'IN_TRANSIT' and shipment.assigned_driver:
        from backend.routes.fleet import vehicle_dispatch_block_reason

        certificate_block = vehicle_dispatch_block_reason(shipment.assigned_driver)
        if certificate_block:
            return jsonify({'status': 'error', 'message': certificate_block}), 409
    if user.role == 'driver' and new_status == 'IN_TRANSIT':
        client_user_id = data.get('client_user_id')
        if client_user_id is not None and (
            isinstance(client_user_id, bool) or not isinstance(client_user_id, int)
        ):
            return jsonify({'status': 'error', 'message': 'Select the client company loaded for this shipment.'}), 400
        if shipment.client_user_id is not None:
            if client_user_id is not None and client_user_id != shipment.client_user_id:
                return jsonify({'status': 'error', 'message': 'This shipment is already assigned to a different client account.'}), 409
            client_account = shipment.client_account
        elif client_user_id is not None:
            client_account = db.session.get(UserAccount, client_user_id)
            if not client_account or client_account.role != 'client' or client_account.account_status != 'active':
                return jsonify({'status': 'error', 'message': 'Select an active client account for this load.'}), 400
        else:
            matching_clients = UserAccount.query.filter(
                db.func.lower(UserAccount.company_name) == (shipment.company_name or '').strip().lower(),
                UserAccount.role == 'client',
                UserAccount.account_status == 'active',
            ).all() if shipment.company_name else []
            client_account = matching_clients[0] if len(matching_clients) == 1 else None
        if (
            not client_account
            or client_account.role != 'client'
            or client_account.account_status != 'active'
            or not client_account.company_name
            or not client_account.company_name.strip()
            or (
                shipment.company_name
                and shipment.company_name.strip().casefold() != client_account.company_name.strip().casefold()
            )
        ):
            return jsonify({
                'status': 'error',
                'message': 'Select the active client company for this load before starting the trip.',
            }), 400
        shipment.client_user_id = client_account.id
        shipment.company_name = client_account.company_name

    documents = ShipmentDocument.query.filter_by(shipment_tracking_number=shipment.tracking_number).all()
    if new_status == 'IN_TRANSIT':
        shipment.departed_at = datetime.now(timezone.utc)
        for document in documents:
            if document.destination_validated:
                document.security_stamped_at = shipment.departed_at
    elif new_status == 'DELIVERED':
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
    automated_warnings = []
    if new_status == 'DELIVERED' and shipment.assigned_driver:
        from backend.routes.workforce import create_automated_driver_warning

        warning_rules = []
        pod_photo = ShipmentOperationalEvidence.query.filter_by(
            shipment_tracking_number=shipment.tracking_number,
            evidence_type='POD_PHOTO',
            uploaded_by_id=shipment.assigned_driver_id,
        ).first()
        if not pod_photo:
            warning_rules.append((
                'MISSING_POD_PHOTO',
                'POD_DOCUMENTATION',
                (
                    f'Shipment {shipment.tracking_number} was marked delivered without a driver-uploaded '
                    'proof-of-delivery photo. This automated warning is open to rebuttal for 72 hours.'
                ),
            ))

        due_at = shipment.delivery_due_at
        if due_at and due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=timezone.utc)
        traffic_proof = ShipmentOperationalEvidence.query.filter_by(
            shipment_tracking_number=shipment.tracking_number,
            evidence_type='TRAFFIC_PROOF',
            uploaded_by_id=shipment.assigned_driver_id,
        ).first()
        if due_at and shipment.arrived_at > due_at and not traffic_proof:
            warning_rules.append((
                'LATE_WITHOUT_TRAFFIC_PROOF',
                'MINOR_LATE_ARRIVAL',
                (
                    f'Shipment {shipment.tracking_number} arrived at {shipment.arrived_at.isoformat()}, '
                    f'after the due time {due_at.isoformat()}, with no traffic-proof evidence on file. '
                    'This automated warning is open to rebuttal for 72 hours.'
                ),
            ))
        for source_code, severity, details in warning_rules:
            case = create_automated_driver_warning(
                shipment.assigned_driver,
                source_code,
                f'{shipment.tracking_number}:{source_code}',
                severity,
                details,
                shipment.arrived_at,
            )
            if case:
                automated_warnings.append(case.to_dict())
    db.session.commit()
    customer_notification = None
    if new_status == 'IN_TRANSIT':
        if shipment.end_customer_email:
            tracking_url = create_public_tracking_link(shipment)
            db.session.commit()
            customer_notification = send_customer_tracking_email(shipment, tracking_url)
        else:
            customer_notification = {
                'status': 'not_sent',
                'message': 'No end-customer email address is on file; create a tracking link from shipment tracking to share it.',
            }
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
    return jsonify({
        'status': 'success',
        'shipment': shipment.to_dict(),
        'automated_warnings': automated_warnings,
        'customer_notification': customer_notification,
    }), 200


@shipments_bp.post('/<tracking_number>/proof-of-delivery/sign')
@jwt_required()
def sign_proof_of_delivery(tracking_number):
    user = get_request_user()
    shipment = db.session.get(Shipment, tracking_number.strip().upper())
    if not user or user.role != 'client' or not shipment or not shipment_visible_to(shipment, user):
        return jsonify({'status': 'error', 'message': 'This delivery is not available to your client account.'}), 404
    if shipment.status != 'DELIVERED':
        return jsonify({'status': 'error', 'message': 'You can sign proof of delivery after the driver marks the delivery arrived.'}), 409
    if ShipmentProofOfDelivery.query.filter_by(
        shipment_tracking_number=shipment.tracking_number,
    ).first():
        return jsonify({'status': 'error', 'message': 'This delivery has already been signed.'}), 409

    data = request.get_json(silent=True)
    signer_name = data.get('signer_name') if isinstance(data, dict) else None
    signature_data = data.get('signature_png') if isinstance(data, dict) else None
    if not isinstance(signer_name, str) or not signer_name.strip() or len(signer_name.strip()) > 120:
        return jsonify({'status': 'error', 'message': 'Enter the receiving customer’s name.'}), 400
    if not isinstance(signature_data, str) or not signature_data.startswith('data:image/png;base64,'):
        return jsonify({'status': 'error', 'message': 'Provide a valid PNG signature.'}), 400

    try:
        signature_bytes = base64.b64decode(signature_data.split(',', 1)[1], validate=True)
        if not signature_bytes or len(signature_bytes) > 512 * 1024:
            raise ValueError
        with Image.open(io.BytesIO(signature_bytes)) as signature_image:
            if signature_image.format != 'PNG' or signature_image.width > 1200 or signature_image.height > 600:
                raise ValueError
            signature_image.load()
            grayscale = signature_image.convert('L')
            ink = grayscale.point(lambda pixel: 255 if pixel < 245 else 0)
            if not ink.getbbox():
                raise ValueError
            sanitized_signature = io.BytesIO()
            signature_image.convert('RGB').save(sanitized_signature, format='PNG', optimize=True)
            signature_bytes = sanitized_signature.getvalue()
    except (
        binascii.Error,
        Image.DecompressionBombError,
        OSError,
        UnidentifiedImageError,
        ValueError,
    ):
        return jsonify({'status': 'error', 'message': 'The signature is blank or is not a supported PNG image.'}), 400

    signed_at = datetime.now(timezone.utc)
    proof = ShipmentProofOfDelivery(
        shipment_tracking_number=shipment.tracking_number,
        signer_user_id=user.id,
        signer_name=signer_name.strip(),
        signature_png=signature_bytes,
        signed_at=signed_at,
    )
    signed_pdf = build_signed_pod_pdf(shipment, proof)
    db.session.add(proof)
    pod_filename = f'{shipment.tracking_number}-signed-proof-of-delivery.pdf'
    try:
        _document, pod_path, previous_pod_path = persist_generated_pdf(
            shipment, user, 'signed_pod', pod_filename, signed_pdf,
        )
    except OSError:
        db.session.rollback()
        current_app.logger.exception('Unable to store the signed proof of delivery PDF.')
        return jsonify({'status': 'error', 'message': 'The signed proof of delivery could not be saved.'}), 500
    invoice_created = False
    try:
        if shipment.quoted_amount_kes is not None:
            from backend.routes.portal import ShipmentFinance

            finance = db.session.get(ShipmentFinance, shipment.tracking_number)
            if finance is None:
                finance = ShipmentFinance(
                    tracking_number=shipment.tracking_number,
                    invoice_amount_kes=detention_invoice_amount(shipment)[0],
                    paid_amount_kes=0,
                    updated_by_id=user.id,
                    updated_at=signed_at,
                )
                db.session.add(finance)
                invoice_created = True
            elif finance.invoice_amount_kes is None:
                finance.invoice_amount_kes = detention_invoice_amount(shipment)[0]
                finance.updated_by_id = user.id
                finance.updated_at = signed_at
                invoice_created = True
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        cleanup_generated_pdf(pod_path)
        return jsonify({'status': 'error', 'message': 'This delivery has already been signed.'}), 409
    except Exception:
        db.session.rollback()
        cleanup_generated_pdf(pod_path)
        current_app.logger.exception('Unable to store the signed proof of delivery.')
        return jsonify({'status': 'error', 'message': 'The signed proof of delivery could not be saved.'}), 500
    if previous_pod_path and previous_pod_path != pod_path and os.path.exists(previous_pod_path):
        os.remove(previous_pod_path)

    client_email = shipment.client_account.email if shipment.client_account else None
    email_delivery = send_shipment_email(
        [client_email],
        f'Signed proof of delivery — {shipment.tracking_number}',
        (
            f'The delivery for shipment {shipment.tracking_number} was signed by {proof.signer_name} '
            f'on {proof.signed_at.isoformat()}. The signed proof of delivery is attached.'
        ),
        attachment=signed_pdf,
        attachment_name=f'{shipment.tracking_number}-signed-proof-of-delivery.pdf',
    )
    if email_delivery['status'] == 'not_sent':
        email_delivery['message'] = f"Signed POD was saved, but {email_delivery['message'].lower()}"
    elif email_delivery['status'] == 'failed':
        email_delivery['message'] = f"Signed POD was saved, but {email_delivery['message'].lower()}"

    return jsonify({
        'status': 'success',
        'message': 'Delivery signed successfully.',
        'invoice_created': invoice_created,
        'shipment': shipment.to_dict(),
        'email_delivery': email_delivery,
    }), 201


@shipments_bp.get('/<tracking_number>/proof-of-delivery')
@jwt_required()
def download_proof_of_delivery(tracking_number):
    user = get_request_user()
    shipment = db.session.get(Shipment, tracking_number.strip().upper())
    if (
        not user
        or user.role not in ({'client'} | ADMIN_ROLES)
        or not shipment
        or not shipment_visible_to(shipment, user)
    ):
        return jsonify({'status': 'error', 'message': 'Signed proof of delivery was not found for this account.'}), 404

    proof = ShipmentProofOfDelivery.query.filter_by(
        shipment_tracking_number=shipment.tracking_number,
    ).first()
    if not proof:
        return jsonify({'status': 'error', 'message': 'This delivery has not been signed yet.'}), 404

    document = ShipmentDocument.query.filter_by(
        shipment_tracking_number=shipment.tracking_number,
        document_type='signed_pod',
    ).first()
    if not document or not os.path.isfile(os.path.join(
        current_app.config['SHIPMENT_DOCUMENTS_DIR'], document.storage_filename,
    )):
        try:
            contents = build_signed_pod_pdf(shipment, proof)
            _document, path, previous_path = persist_generated_pdf(
                shipment,
                user,
                'signed_pod',
                f'{shipment.tracking_number}-signed-proof-of-delivery.pdf',
                contents,
            )
            db.session.commit()
        except OSError:
            db.session.rollback()
            if 'path' in locals() and os.path.exists(path):
                os.remove(path)
            current_app.logger.exception('Unable to restore the signed proof of delivery PDF.')
            return jsonify({'status': 'error', 'message': 'The stored proof of delivery is unavailable.'}), 500
        except Exception:
            db.session.rollback()
            if 'path' in locals() and os.path.exists(path):
                os.remove(path)
            current_app.logger.exception('Unable to save the signed proof of delivery PDF.')
            return jsonify({'status': 'error', 'message': 'The signed proof of delivery could not be saved.'}), 500
        if previous_path and previous_path != path and os.path.exists(previous_path):
            os.remove(previous_path)
    else:
        path = os.path.join(current_app.config['SHIPMENT_DOCUMENTS_DIR'], document.storage_filename)

    with open(path, 'rb') as document_file:
        contents = document_file.read()
    response = send_file(
        io.BytesIO(contents),
        mimetype='application/pdf',
        as_attachment=request.args.get('preview') != '1',
        download_name=f'{shipment.tracking_number}-signed-proof-of-delivery.pdf',
        conditional=False,
        max_age=0,
    )
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


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


@shipments_bp.route('/<tracking_number>/operational-evidence', methods=['POST'])
@jwt_required()
def upload_operational_evidence(tracking_number):
    user = get_request_user()
    if not user or user.role != 'driver':
        return jsonify({'status': 'error', 'message': 'Only the assigned driver may submit trip evidence.'}), 403
    shipment = db.session.get(Shipment, tracking_number.strip().upper())
    if not shipment or shipment.assigned_driver_id != user.id:
        return jsonify({'status': 'error', 'message': 'Shipment was not found or is not assigned to your account.'}), 404
    if shipment.status not in {'IN_TRANSIT', 'BREAKDOWN', 'DELIVERED'}:
        return jsonify({'status': 'error', 'message': 'Trip evidence can only be attached to an active or completed shipment.'}), 409

    evidence_type = request.form.get('evidence_type')
    if evidence_type not in {'POD_PHOTO', 'TRAFFIC_PROOF'}:
        return jsonify({'status': 'error', 'message': 'Choose a POD photo or traffic-delay proof.'}), 400
    upload = request.files.get('image')
    if not upload or not upload.filename:
        return jsonify({'status': 'error', 'message': 'Choose an image to upload.'}), 400
    contents = upload.read(MAX_DOCUMENT_BYTES + 1)
    if not contents or len(contents) > MAX_DOCUMENT_BYTES:
        return jsonify({'status': 'error', 'message': 'Evidence images must be between 1 byte and 12 MB.'}), 400
    note = request.form.get('note', '').strip()
    if not isinstance(note, str) or len(note) > 1000:
        return jsonify({'status': 'error', 'message': 'Evidence notes must be at most 1,000 characters.'}), 400
    if evidence_type == 'TRAFFIC_PROOF' and not note:
        return jsonify({'status': 'error', 'message': 'Describe the traffic delay shown in the evidence.'}), 400

    try:
        with Image.open(io.BytesIO(contents)) as image:
            image.verify()
        with Image.open(io.BytesIO(contents)) as image:
            image.load()
            normalized = io.BytesIO()
            image.convert('RGB').save(normalized, format='JPEG', quality=88, optimize=True)
            safe_image = normalized.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        return jsonify({'status': 'error', 'message': 'Upload a valid JPEG, PNG, or WebP image.'}), 422

    record = ShipmentOperationalEvidence(
        shipment_tracking_number=shipment.tracking_number,
        evidence_type=evidence_type,
        filename=(secure_filename(upload.filename) or 'trip-evidence.jpg')[:255],
        contents=safe_image,
        sha256=hashlib.sha256(safe_image).hexdigest(),
        note=note or None,
        uploaded_by_id=user.id,
    )
    db.session.add(record)
    db.session.commit()
    return jsonify({
        'status': 'success',
        'message': 'Trip evidence uploaded and integrity-checked.',
        'evidence': record.to_dict(),
    }), 201


@shipments_bp.route('/<tracking_number>/operational-evidence', methods=['GET'])
@jwt_required()
def list_operational_evidence(tracking_number):
    user = get_request_user()
    shipment = db.session.get(Shipment, tracking_number.strip().upper())
    if not user or not shipment or not shipment_visible_to(shipment, user):
        return jsonify({'status': 'error', 'message': 'Shipment evidence was not found for this account.'}), 404
    evidence = ShipmentOperationalEvidence.query.filter_by(
        shipment_tracking_number=shipment.tracking_number,
    ).order_by(ShipmentOperationalEvidence.uploaded_at.desc()).all()
    return jsonify({
        'status': 'success',
        'evidence': [record.to_dict() for record in evidence],
    }), 200


@shipments_bp.route('/<tracking_number>/operational-evidence/<evidence_id>', methods=['GET'])
@jwt_required()
def download_operational_evidence(tracking_number, evidence_id):
    user = get_request_user()
    shipment = db.session.get(Shipment, tracking_number.strip().upper())
    if not user or not shipment or not shipment_visible_to(shipment, user):
        return jsonify({'status': 'error', 'message': 'Shipment evidence was not found for this account.'}), 404
    record = db.session.get(ShipmentOperationalEvidence, evidence_id)
    if not record or record.shipment_tracking_number != shipment.tracking_number:
        return jsonify({'status': 'error', 'message': 'Trip evidence was not found.'}), 404
    if not hmac.compare_digest(hashlib.sha256(record.contents).hexdigest(), record.sha256):
        current_app.logger.error('SHA-256 validation failed for shipment evidence %s', record.id)
        return jsonify({'status': 'error', 'message': 'Trip evidence failed integrity verification.'}), 500
    response = send_file(
        io.BytesIO(record.contents),
        mimetype='image/jpeg',
        as_attachment=True,
        download_name=record.filename,
        max_age=0,
    )
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Content-Security-Policy'] = "sandbox; default-src 'none'"
    return response


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
