from flask import Blueprint, jsonify, request
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager, create_access_token, get_jwt_identity, jwt_required
from backend.models.payroll import db

bcrypt = Bcrypt()
jwt = JWTManager()

auth_bp = Blueprint('auth', __name__, url_prefix='/api')


class UserAccount(db.Model):
    __tablename__ = 'user_accounts'

    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='client')
    driver_name = db.Column(db.String(120), nullable=True)
    display_name = db.Column(db.String(120), nullable=True)

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
        }


@auth_bp.route('/auth/register', methods=['POST'])
def register():
    data = request.get_json() or {}
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


@auth_bp.route('/auth/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    selected_role = data.get('role')

    if not email or not password:
        return jsonify({'status': 'error', 'message': 'Email and password are required.'}), 400

    user = UserAccount.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return jsonify({'status': 'error', 'message': 'Invalid email or password.'}), 401
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

    return jsonify({'status': 'success', 'user': user.to_dict()}), 200


@auth_bp.route('/auth/users', methods=['GET'])
@jwt_required()
def list_users():
    user = db.session.get(UserAccount, int(get_jwt_identity()))
    if not user or user.role != 'admin':
        return jsonify({'status': 'error', 'message': 'Admin access is required.'}), 403

    users = UserAccount.query.order_by(UserAccount.company_name, UserAccount.email).all()
    return jsonify({'status': 'success', 'users': [account.to_dict() for account in users]}), 200


@auth_bp.route('/auth/users/<int:user_id>/role', methods=['PATCH'])
@jwt_required()
def update_user_role(user_id):
    admin = db.session.get(UserAccount, int(get_jwt_identity()))
    if not admin or admin.role != 'admin':
        return jsonify({'status': 'error', 'message': 'Admin access is required.'}), 403

    data = request.get_json(silent=True) or {}
    role = data.get('role')
    driver_name = data.get('driver_name', '')
    display_name = data.get('display_name', '')
    if role not in {'client', 'driver', 'admin', 'mechanic'}:
        return jsonify({'status': 'error', 'message': "Role must be 'client', 'driver', 'admin', or 'mechanic'."}), 400
    if user_id == admin.id:
        return jsonify({'status': 'error', 'message': 'You cannot change your own account role.'}), 400
    if role in {'driver', 'mechanic'} and (
        not isinstance(display_name, str) or not display_name.strip()
    ):
        return jsonify({'status': 'error', 'message': 'An employee display name is required for this role.'}), 400

    account = db.session.get(UserAccount, user_id)
    if not account:
        return jsonify({'status': 'error', 'message': 'User not found.'}), 404

    account.role = role
    account.driver_name = display_name.strip() if role == 'driver' else None
    account.display_name = display_name.strip() if role in {'driver', 'mechanic', 'admin'} else None
    db.session.commit()
    return jsonify({'status': 'success', 'user': account.to_dict()}), 200


@auth_bp.route('/auth/users', methods=['POST'])
@jwt_required()
def create_user():
    admin = db.session.get(UserAccount, int(get_jwt_identity()))
    if not admin or admin.role != 'admin':
        return jsonify({'status': 'error', 'message': 'Admin access is required.'}), 403

    data = request.get_json(silent=True) or {}
    company_name = data.get('company_name', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    role = data.get('role')
    display_name = data.get('display_name', '').strip()
    if not company_name or not email or not password:
        return jsonify({
            'status': 'error',
            'message': 'Company or department, email, and an initial password are required.',
        }), 400
    if len(password) < 12:
        return jsonify({'status': 'error', 'message': 'The initial password must be at least 12 characters.'}), 400
    if role not in {'client', 'driver', 'admin', 'mechanic'}:
        return jsonify({'status': 'error', 'message': 'Choose a supported account role.'}), 400
    if role in {'driver', 'mechanic', 'admin'} and not display_name:
        return jsonify({'status': 'error', 'message': 'An employee display name is required for this role.'}), 400
    if UserAccount.query.filter_by(email=email).first():
        return jsonify({'status': 'error', 'message': 'An account with this email already exists.'}), 409

    account = UserAccount()
    account.company_name = company_name
    account.email = email
    account.role = role
    account.driver_name = display_name if role == 'driver' else None
    account.display_name = display_name or None
    account.set_password(password)
    db.session.add(account)
    db.session.commit()
    return jsonify({'status': 'success', 'user': account.to_dict()}), 201