import json
import re
import secrets
from datetime import datetime, timezone

import httpx
from flask import Blueprint, current_app, jsonify, request
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager, create_access_token, get_jwt_identity, jwt_required
from sqlalchemy import func, or_
from backend.models.payroll import db

bcrypt = Bcrypt()
jwt = JWTManager()

auth_bp = Blueprint('auth', __name__, url_prefix='/api')
ADMIN_ROLES = {'admin', 'boss', 'hr'}
HR_ROLES = {'hr', 'boss'}
EMPLOYEE_ROLES = {'driver', 'mechanic', 'accountant', 'admin', 'hr', 'boss'}


class MailDeliveryError(Exception):
    pass


STATUTORY_FIELDS = {
    'kra_pin': ('KRA PIN', re.compile(r'[A-Z][0-9]{9}[A-Z]')),
    'nssf_number': ('NSSF number', re.compile(r'[A-Z0-9-]{4,20}')),
    'shif_number': ('SHIF number', re.compile(r'[A-Z0-9-]{4,20}')),
}


def statutory_dict(account):
    return {field: getattr(account, field) for field in STATUTORY_FIELDS}


def apply_statutory_details(account, data):
    cleaned = {}
    for field, (label, pattern) in STATUTORY_FIELDS.items():
        if field not in data:
            continue
        value = data[field]
        if value is None or (isinstance(value, str) and not value.strip()):
            cleaned[field] = None
            continue
        if not isinstance(value, str) or not pattern.fullmatch(value.strip().upper()):
            raise ValueError(f'Enter a valid {label}.')
        cleaned[field] = value.strip().upper()
    for field, value in cleaned.items():
        setattr(account, field, value)


PHONE_PATTERN = re.compile(r'[+0-9() .-]{7,40}')


def normalize_phone(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str) or not PHONE_PATTERN.fullmatch(value.strip()):
        raise ValueError('Enter a valid phone number.')
    return value.strip()


def request_data():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


class UserAccount(db.Model):
    __tablename__ = 'user_accounts'

    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='client')
    driver_name = db.Column(db.String(120), nullable=True)
    display_name = db.Column(db.String(120), nullable=True)
    account_status = db.Column(db.String(20), nullable=False, default='active')
    approved_by_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=True)
    approved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    username = db.Column(db.String(80), unique=True, nullable=True)
    must_change_password = db.Column(db.Boolean, nullable=False, default=False)
    notification_email = db.Column(db.String(120), nullable=True)
    driver_code = db.Column(db.String(20), unique=True, nullable=True)
    employment_status = db.Column(db.String(24), nullable=False, default='ACTIVE')
    leave_type = db.Column(db.String(16), nullable=True)
    employment_status_note = db.Column(db.String(500), nullable=True)
    employment_status_updated_at = db.Column(db.DateTime(timezone=True), nullable=True)
    employment_status_updated_by_id = db.Column(db.Integer, db.ForeignKey('user_accounts.id'), nullable=True)
    leaderboard_opt_in = db.Column(db.Boolean, nullable=False, default=False)
    leaderboard_handle = db.Column(db.String(40), nullable=True)
    ui_preferences = db.Column(db.Text, nullable=True)
    phone = db.Column(db.String(40), nullable=True)
    kra_pin = db.Column(db.String(11), nullable=True)
    nssf_number = db.Column(db.String(20), nullable=True)
    shif_number = db.Column(db.String(20), nullable=True)

    def get_preferences(self):
        try:
            value = json.loads(self.ui_preferences or '{}')
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            'id': self.id,
            'company_name': self.company_name,
            'email': self.email,
            'notification_email': self.notification_email,
            'role': self.role or 'client',
            'driver_name': self.driver_name,
            'display_name': self.display_name or self.driver_name,
            'account_status': self.account_status,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'username': self.username,
            'must_change_password': self.must_change_password,
            'employment_status': self.employment_status,
            'leave_type': self.leave_type,
            'driver_code': self.driver_code,
            'leaderboard_opt_in': self.leaderboard_opt_in,
            'leaderboard_handle': self.leaderboard_handle,
            'preferences': self.get_preferences(),
            'phone': self.phone,
        }


def send_onboarding_email(account_email, recipient_email, username, temporary_password, role):
    api_key = current_app.config.get('SENDGRID_API_KEY')
    sender = current_app.config.get('MAIL_FROM_EMAIL')
    if not api_key or not sender:
        raise MailDeliveryError(
            'Account email delivery is not configured. Set SENDGRID_API_KEY and MAIL_FROM_EMAIL.'
        )

    login_name = username or account_email
    message = (
        f'Your Difan Logistics {role} account is ready.\n\n'
        f'Username: {login_name}\n'
        f'Temporary password: {temporary_password}\n\n'
        'Sign in using these credentials. You will be required to change your password '
        'before accessing the portal.'
    )
    try:
        response = httpx.post(
            'https://api.sendgrid.com/v3/mail/send',
            headers={'Authorization': f'Bearer {api_key}'},
            json={
                'personalizations': [{'to': [{'email': recipient_email}]}],
                'from': {'email': sender},
                'subject': 'Your Difan Logistics account',
                'content': [{'type': 'text/plain', 'value': message}],
            },
            timeout=10,
        )
    except httpx.HTTPError as error:
        raise MailDeliveryError('The account email could not be sent. Please try again.') from error
    if response.status_code != 202:
        raise MailDeliveryError(
            'The email provider rejected the account email. Check the sender and API configuration.'
        )


def ensure_main_accounts():
    shared_email = current_app.config.get('MAIN_ACCOUNT_EMAIL')
    if (
        not shared_email
        or not current_app.config.get('SENDGRID_API_KEY')
        or not current_app.config.get('MAIL_FROM_EMAIL')
    ):
        current_app.logger.warning(
            'Main Boss and HR accounts were not provisioned because SendGrid is not configured.'
        )
        return

    for username, role, display_name in (
        ('DifanMain', 'boss', 'Difan Boss'),
        ('DifanSecond', 'hr', 'Difan HR'),
    ):
        account = UserAccount.query.filter_by(username=username).first()
        if account:
            continue

        temporary_password = secrets.token_urlsafe(18)
        account_email = f'{username.lower()}@difan.local'
        account = UserAccount(
            company_name='Difan Logistics',
            email=account_email,
            notification_email=shared_email,
            username=username,
            role=role,
            display_name=display_name,
            account_status='active',
            must_change_password=True,
        )
        account.set_password(temporary_password)
        db.session.add(account)
        try:
            db.session.flush()
            send_onboarding_email(account_email, shared_email, username, temporary_password, role)
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Unable to provision the %s main account.', role)
            raise


@auth_bp.route('/auth/register', methods=['POST'])
def register():
    return jsonify({
        'status': 'error',
        'message': 'Client accounts are created by Difan HR. Please contact Difan Logistics.',
    }), 403


@auth_bp.route('/auth/register/employee', methods=['POST'])
def register_employee():
    return jsonify({
        'status': 'error',
        'message': 'Employee accounts are created by Difan HR. Please contact Difan Logistics.',
    }), 403


@auth_bp.route('/auth/login', methods=['POST'])
def login():
    data = request_data()
    identifier = data.get('username', data.get('email', ''))
    password = data.get('password', '')
    selected_role = data.get('role')

    if not isinstance(identifier, str) or not isinstance(password, str) or not identifier.strip() or not password:
        return jsonify({'status': 'error', 'message': 'Username or email and password are required.'}), 400

    normalized_identifier = identifier.strip()
    user = UserAccount.query.filter(
        or_(
            func.lower(UserAccount.email) == normalized_identifier.lower(),
            func.lower(UserAccount.username) == normalized_identifier.lower(),
        )
    ).first()
    if not user or not user.check_password(password):
        return jsonify({'status': 'error', 'message': 'Invalid email or password.'}), 401
    if user.account_status != 'active':
        message = (
            'Your employee registration is awaiting HR approval.'
            if user.account_status == 'pending'
            else 'This account is not active. Contact Difan HR.'
        )
        return jsonify({'status': 'error', 'message': message}), 403
    if selected_role and selected_role != user.role:
        return jsonify({
            'status': 'error',
            'message': 'The selected portal does not match the role assigned to this account.',
        }), 403

    token = create_access_token(
        identity=str(user.id),
        additional_claims={'must_change_password': user.must_change_password},
    )

    return jsonify({
        'status': 'success',
        'token': token,
        'user': user.to_dict(),
    }), 200


@auth_bp.route('/auth/me', methods=['GET'])
@jwt_required()
def get_current_user():
    user_id = get_jwt_identity()
    user = db.session.get(UserAccount, int(user_id))
    if not user:
        return jsonify({'status': 'error', 'message': 'User not found.'}), 404
    if user.account_status != 'active':
        return jsonify({'status': 'error', 'message': 'This account is not active.'}), 403

    return jsonify({'status': 'success', 'user': user.to_dict()}), 200


PREFERENCE_STRING_KEYS = ('active_tab', 'theme', 'language')
MAX_PREFERENCE_VALUE_LENGTH = 80


def clean_preferences(payload):
    cleaned = {}
    for key in PREFERENCE_STRING_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            cleaned[key] = value.strip()[:MAX_PREFERENCE_VALUE_LENGTH]
    sub_tabs = payload.get('sub_tabs')
    if isinstance(sub_tabs, dict):
        cleaned['sub_tabs'] = {
            str(group)[:MAX_PREFERENCE_VALUE_LENGTH]: str(tab)[:MAX_PREFERENCE_VALUE_LENGTH]
            for group, tab in list(sub_tabs.items())[:20]
            if isinstance(tab, str) and tab.strip()
        }
    return cleaned


@auth_bp.route('/auth/preferences', methods=['GET', 'PUT'])
@jwt_required()
def user_preferences():
    user = db.session.get(UserAccount, int(get_jwt_identity()))
    if not user or user.account_status != 'active':
        return jsonify({'status': 'error', 'message': 'This account is not active.'}), 403
    if request.method == 'PUT':
        merged = {**user.get_preferences(), **clean_preferences(request_data())}
        user.ui_preferences = json.dumps(merged)
        db.session.commit()
    return jsonify({'status': 'success', 'preferences': user.get_preferences()}), 200


@jwt.token_verification_loader
def allow_forced_password_change_only(header, payload):
    if not payload.get('must_change_password'):
        return True
    return request.endpoint == 'auth.change_password'


@jwt.token_verification_failed_loader
def reject_forced_password_change(header, payload):
    return jsonify({
        'status': 'error',
        'message': 'Change your temporary password before accessing the portal.',
        'must_change_password': True,
    }), 403


@auth_bp.route('/auth/profile', methods=['PATCH'])
@jwt_required()
def update_profile():
    user = db.session.get(UserAccount, int(get_jwt_identity()))
    if not user or user.account_status != 'active':
        return jsonify({'status': 'error', 'message': 'This account is not active.'}), 403
    try:
        user.phone = normalize_phone(request_data().get('phone'))
    except ValueError as error:
        return jsonify({'status': 'error', 'message': str(error)}), 400
    db.session.commit()
    return jsonify({'status': 'success', 'user': user.to_dict()}), 200


def statutory_response(account, data=None):
    if data is not None:
        try:
            apply_statutory_details(account, data)
        except ValueError as error:
            return jsonify({'status': 'error', 'message': str(error)}), 400
        db.session.commit()
    return jsonify({
        'status': 'success',
        'employee': {
            'id': account.id,
            'name': account.display_name or account.driver_name or account.email,
            **statutory_dict(account),
        },
    }), 200


@auth_bp.route('/auth/employee-details', methods=['GET', 'PATCH'])
@jwt_required()
def own_employee_details():
    user = db.session.get(UserAccount, int(get_jwt_identity()))
    if not user or user.account_status != 'active' or user.role not in EMPLOYEE_ROLES:
        return jsonify({'status': 'error', 'message': 'Employee details are not available for this account.'}), 403
    return statutory_response(user, request_data() if request.method == 'PATCH' else None)


@auth_bp.route('/auth/users/<int:user_id>/employee-details', methods=['GET', 'PATCH'])
@jwt_required()
def employee_details_for_admin(user_id):
    admin = require_admin_or_hr()
    if not admin or admin.role not in ADMIN_ROLES:
        return jsonify({'status': 'error', 'message': 'Admin access is required.'}), 403
    account = db.session.get(UserAccount, user_id)
    if not account or account.role not in EMPLOYEE_ROLES:
        return jsonify({'status': 'error', 'message': 'Employee was not found.'}), 404
    return statutory_response(account, request_data() if request.method == 'PATCH' else None)


@auth_bp.route('/auth/change-password', methods=['POST'])
@jwt_required()
def change_password():
    user = db.session.get(UserAccount, int(get_jwt_identity()))
    if not user or user.account_status != 'active':
        return jsonify({'status': 'error', 'message': 'This account is not active.'}), 403

    data = request_data()
    password = data.get('password', '')
    if not isinstance(password, str) or len(password) < 12:
        return jsonify({'status': 'error', 'message': 'Password must be at least 12 characters long.'}), 400
    if user.check_password(password):
        return jsonify({'status': 'error', 'message': 'Choose a password different from your temporary password.'}), 400

    user.set_password(password)
    user.must_change_password = False
    db.session.commit()
    return jsonify({
        'status': 'success',
        'message': 'Password changed successfully.',
        'token': create_access_token(identity=str(user.id)),
        'user': user.to_dict(),
    }), 200


def require_admin_or_hr():
    user = db.session.get(UserAccount, int(get_jwt_identity()))
    if not user or user.account_status != 'active' or user.role not in (ADMIN_ROLES | {'hr'}):
        return None
    return user


@auth_bp.route('/auth/users', methods=['GET'])
@jwt_required()
def list_users():
    user = require_admin_or_hr()
    if not user or user.role not in ADMIN_ROLES:
        return jsonify({'status': 'error', 'message': 'Admin access is required.'}), 403

    users = UserAccount.query.order_by(UserAccount.company_name, UserAccount.email).all()
    return jsonify({'status': 'success', 'users': [account.to_dict() for account in users]}), 200


@auth_bp.route('/auth/employee-registrations', methods=['GET'])
@jwt_required()
def list_employee_registrations():
    user = require_admin_or_hr()
    if not user or user.role not in HR_ROLES:
        return jsonify({'status': 'error', 'message': 'HR or Admin access is required.'}), 403

    pending = UserAccount.query.filter(
        UserAccount.role.in_(EMPLOYEE_ROLES),
        UserAccount.account_status == 'pending',
    ).order_by(UserAccount.id).all()
    return jsonify({
        'status': 'success',
        'registrations': [account.to_dict() for account in pending],
    }), 200


@auth_bp.route('/auth/employee-registrations/<int:user_id>/approve', methods=['PATCH'])
@jwt_required()
def approve_employee_registration(user_id):
    approver = require_admin_or_hr()
    if not approver or approver.role not in HR_ROLES:
        return jsonify({'status': 'error', 'message': 'HR or Admin access is required.'}), 403

    account = db.session.get(UserAccount, user_id)
    if not account or account.role not in EMPLOYEE_ROLES:
        return jsonify({'status': 'error', 'message': 'Employee registration was not found.'}), 404
    if account.account_status != 'pending':
        return jsonify({'status': 'error', 'message': 'This employee registration is no longer pending.'}), 409

    account.account_status = 'active'
    if account.role == 'driver' and not account.driver_code:
        account.driver_code = f'DRV-{account.id:04d}'
    account.approved_by_id = approver.id
    account.approved_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({
        'status': 'success',
        'message': 'Employee registration approved. The employee can now sign in.',
        'user': account.to_dict(),
    }), 200


@auth_bp.route('/auth/users/<int:user_id>/role', methods=['PATCH'])
@jwt_required()
def update_user_role(user_id):
    admin = require_admin_or_hr()
    if not admin:
        return jsonify({'status': 'error', 'message': 'Admin access is required.'}), 403

    data = request_data()
    role = data.get('role')
    display_name = data.get('display_name', '')
    if not isinstance(role, str) or role not in {'client', *EMPLOYEE_ROLES}:
        return jsonify({'status': 'error', 'message': 'Choose a supported account role.'}), 400
    if user_id == admin.id:
        return jsonify({'status': 'error', 'message': 'You cannot change your own account role.'}), 400
    if role in EMPLOYEE_ROLES and (
        not isinstance(display_name, str) or not display_name.strip()
    ):
        return jsonify({'status': 'error', 'message': 'An employee display name is required for this role.'}), 400

    account = db.session.get(UserAccount, user_id)
    if not account:
        return jsonify({'status': 'error', 'message': 'User not found.'}), 404
    if admin.role != 'boss' and account.role == 'boss':
        return jsonify({'status': 'error', 'message': 'Only the Boss can change the Boss account.'}), 403
    active_boss = UserAccount.query.filter_by(role='boss', account_status='active').first()
    if role == 'boss' and admin.role != 'boss' and active_boss:
        return jsonify({'status': 'error', 'message': 'Only the Boss can assign the Boss role.'}), 403

    account.role = role
    account.driver_name = display_name.strip() if role == 'driver' else None
    account.display_name = display_name.strip() if role in EMPLOYEE_ROLES else None
    if role == 'driver' and not account.driver_code:
        account.driver_code = f'DRV-{account.id:04d}'
    db.session.commit()
    return jsonify({'status': 'success', 'user': account.to_dict()}), 200


@auth_bp.route('/auth/users', methods=['POST'])
@jwt_required()
def create_user():
    admin = require_admin_or_hr()
    if not admin or admin.role not in HR_ROLES:
        return jsonify({'status': 'error', 'message': 'HR or Boss access is required.'}), 403

    data = request_data()
    company_name = data.get('company_name', '')
    email = data.get('email', '')
    role = data.get('role')
    display_name = data.get('display_name', '')
    if not all(isinstance(value, str) for value in (company_name, email, display_name)):
        return jsonify({'status': 'error', 'message': 'Account fields must be text values.'}), 400
    company_name = company_name.strip()
    email = email.strip().lower()
    display_name = display_name.strip()
    if not company_name or not email:
        return jsonify({
            'status': 'error',
            'message': 'Company or department and email are required.',
        }), 400
    if not isinstance(role, str) or role not in {'client', *EMPLOYEE_ROLES}:
        return jsonify({'status': 'error', 'message': 'Choose a supported account role.'}), 400
    active_boss = UserAccount.query.filter_by(role='boss', account_status='active').first()
    if role == 'boss' and admin.role != 'boss' and active_boss:
        return jsonify({'status': 'error', 'message': 'Only the Boss can create a Boss account.'}), 403
    if role in EMPLOYEE_ROLES and not display_name:
        return jsonify({'status': 'error', 'message': 'An employee display name is required for this role.'}), 400
    try:
        phone = normalize_phone(data.get('phone'))
    except ValueError as error:
        return jsonify({'status': 'error', 'message': str(error)}), 400
    if UserAccount.query.filter_by(email=email).first():
        return jsonify({'status': 'error', 'message': 'An account with this email already exists.'}), 409

    temporary_password = secrets.token_urlsafe(18)
    account = UserAccount()
    account.company_name = company_name
    account.email = email
    account.role = role
    account.driver_name = display_name if role == 'driver' else None
    account.display_name = display_name or None
    account.phone = phone
    account.account_status = 'active'
    account.approved_by_id = admin.id
    account.approved_at = datetime.now(timezone.utc)
    account.must_change_password = True
    account.set_password(temporary_password)
    db.session.add(account)
    try:
        db.session.flush()
        if role == 'driver':
            account.driver_code = f'DRV-{account.id:04d}'
        send_onboarding_email(email, email, account.username, temporary_password, role)
        db.session.commit()
    except MailDeliveryError as error:
        db.session.rollback()
        status_code = 503 if 'not configured' in str(error) else 502
        return jsonify({'status': 'error', 'message': str(error)}), status_code
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Unable to create and email an onboarding account.')
        return jsonify({
            'status': 'error',
            'message': 'The account could not be created or its onboarding email could not be sent.',
        }), 500
    return jsonify({
        'status': 'success',
        'message': f'{role.title()} account created and temporary credentials emailed to {email}.',
        'user': account.to_dict(),
    }), 201