from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager, create_access_token, get_jwt_identity, jwt_required
from backend.models.payroll import db

bcrypt = Bcrypt()
jwt = JWTManager()

auth_bp = Blueprint('auth', __name__, url_prefix='/api')
ADMIN_ROLES = {'admin', 'boss'}
HR_ROLES = {'hr', 'boss'}
PUBLIC_EMPLOYEE_ROLES = {'driver', 'mechanic', 'accountant', 'admin', 'hr'}
EMPLOYEE_ROLES = PUBLIC_EMPLOYEE_ROLES | {'boss'}


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

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            'id': self.id,
            'company_name': self.company_name,
            'email': self.email,
            'role': self.role or 'client',
            'driver_name': self.driver_name,
            'display_name': self.display_name or self.driver_name,
            'account_status': self.account_status,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
        }


@auth_bp.route('/auth/register', methods=['POST'])
def register():
    data = request_data()
    company_name = data.get('company_name', '')
    email = data.get('email', '')
    password = data.get('password', '')

    if not all(isinstance(value, str) for value in (company_name, email, password)):
        return jsonify({'status': 'error', 'message': 'Company name, email, and password must be text values.'}), 400
    company_name = company_name.strip()
    email = email.strip().lower()
    if not company_name or not email or not password:
        return jsonify({'status': 'error', 'message': 'Company name, email, and password are required.'}), 400

    if len(password) < 12:
        return jsonify({'status': 'error', 'message': 'Password must be at least 12 characters long.'}), 400

    if UserAccount.query.filter_by(email=email).first():
        return jsonify({'status': 'error', 'message': 'An account with this email already exists.'}), 400

    user = UserAccount()
    user.company_name = company_name
    user.email = email
    user.role = 'client'
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    return jsonify({
        'status': 'success',
        'message': 'Account created successfully! You can now log in.'
    }), 201


@auth_bp.route('/auth/register/employee', methods=['POST'])
def register_employee():
    data = request_data()
    display_name = data.get('display_name', '')
    email = data.get('email', '')
    password = data.get('password', '')
    role = data.get('role')

    if not all(isinstance(value, str) for value in (display_name, email, password, role)):
        return jsonify({'status': 'error', 'message': 'Name, email, password, and employee role are required.'}), 400
    display_name = display_name.strip()
    email = email.strip().lower()
    if not display_name or not email or not password:
        return jsonify({'status': 'error', 'message': 'Name, email, and password are required.'}), 400
    if role not in PUBLIC_EMPLOYEE_ROLES:
        return jsonify({'status': 'error', 'message': 'Choose a supported employee role.'}), 400
    if len(display_name) > 120 or len(email) > 120:
        return jsonify({'status': 'error', 'message': 'Name and email must be 120 characters or fewer.'}), 400
    if len(password) < 12:
        return jsonify({'status': 'error', 'message': 'Password must be at least 12 characters long.'}), 400
    if UserAccount.query.filter_by(email=email).first():
        return jsonify({'status': 'error', 'message': 'An account with this email already exists.'}), 409

    user = UserAccount()
    user.company_name = 'Difan Logistics'
    user.email = email
    user.role = role
    user.driver_name = display_name if role == 'driver' else None
    user.display_name = display_name
    user.account_status = 'pending'
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify({
        'status': 'success',
        'message': 'Registration submitted. HR must approve your account before you can sign in.',
    }), 201


@auth_bp.route('/auth/login', methods=['POST'])
def login():
    data = request_data()
    email = data.get('email', '')
    password = data.get('password', '')
    selected_role = data.get('role')

    if not isinstance(email, str) or not isinstance(password, str) or not email.strip() or not password:
        return jsonify({'status': 'error', 'message': 'Email and password are required.'}), 400

    user = UserAccount.query.filter_by(email=email.strip().lower()).first()
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

    token = create_access_token(identity=str(user.id))

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
    db.session.commit()
    return jsonify({'status': 'success', 'user': account.to_dict()}), 200


@auth_bp.route('/auth/users', methods=['POST'])
@jwt_required()
def create_user():
    admin = require_admin_or_hr()
    if not admin or admin.role not in ADMIN_ROLES:
        return jsonify({'status': 'error', 'message': 'Admin access is required.'}), 403

    data = request_data()
    company_name = data.get('company_name', '')
    email = data.get('email', '')
    password = data.get('password', '')
    role = data.get('role')
    display_name = data.get('display_name', '')
    if not all(isinstance(value, str) for value in (company_name, email, password, display_name)):
        return jsonify({'status': 'error', 'message': 'Account fields must be text values.'}), 400
    company_name = company_name.strip()
    email = email.strip().lower()
    display_name = display_name.strip()
    if not company_name or not email or not password:
        return jsonify({
            'status': 'error',
            'message': 'Company or department, email, and an initial password are required.',
        }), 400
    if len(password) < 12:
        return jsonify({'status': 'error', 'message': 'The initial password must be at least 12 characters.'}), 400
    if not isinstance(role, str) or role not in {'client', *EMPLOYEE_ROLES}:
        return jsonify({'status': 'error', 'message': 'Choose a supported account role.'}), 400
    active_boss = UserAccount.query.filter_by(role='boss', account_status='active').first()
    if role == 'boss' and admin.role != 'boss' and active_boss:
        return jsonify({'status': 'error', 'message': 'Only the Boss can create a Boss account.'}), 403
    if role in EMPLOYEE_ROLES and not display_name:
        return jsonify({'status': 'error', 'message': 'An employee display name is required for this role.'}), 400
    if UserAccount.query.filter_by(email=email).first():
        return jsonify({'status': 'error', 'message': 'An account with this email already exists.'}), 409

    account = UserAccount()
    account.company_name = company_name
    account.email = email
    account.role = role
    account.driver_name = display_name if role == 'driver' else None
    account.display_name = display_name or None
    account.account_status = 'active'
    account.set_password(password)
    db.session.add(account)
    db.session.commit()
    return jsonify({'status': 'success', 'user': account.to_dict()}), 201