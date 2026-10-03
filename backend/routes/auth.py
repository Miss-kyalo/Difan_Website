import os

from flask import Flask, jsonify, request
from flask_bcrypt import Bcrypt
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, get_jwt_identity, jwt_required
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()
bcrypt = Bcrypt()


class UserAccount(db.Model):
    __tablename__ = 'user_accounts'

    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(40), default='client')

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            'id': self.id,
            'company_name': self.company_name,
            'email': self.email,
            'role': self.role,
        }


class Shipment(db.Model):
    __tablename__ = 'shipments'

    id = db.Column(db.Integer, primary_key=True)
    tracking_number = db.Column(db.String(40), unique=True, nullable=False)
    cargo_type = db.Column(db.String(80), nullable=False)
    tonnage = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(80), default='Pending')
    origin = db.Column(db.String(120), nullable=False)
    destination = db.Column(db.String(120), nullable=False)
    total_cost = db.Column(db.Float, default=0.0)
    breakdown_alert = db.Column(db.Boolean, default=False)

    def to_dict(self):
        return {
            'id': self.id,
            'tracking_number': self.tracking_number,
            'cargo_type': self.cargo_type,
            'tonnage': self.tonnage,
            'status': self.status,
            'origin': self.origin,
            'destination': self.destination,
            'total_cost': self.total_cost,
            'breakdown_alert': self.breakdown_alert,
        }


def create_app():
    app = Flask(__name__)
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    instance_dir = os.path.join(base_dir, 'instance')
    os.makedirs(instance_dir, exist_ok=True)

    app.config['SECRET_KEY'] = os.environ.get(
        'SECRET_KEY',
        'difan-logistics-secret-key-2026-strong-32bytes!'
    )
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
        'DATABASE_URL',
        f"sqlite:///{os.path.join(instance_dir, 'auth.db')}"
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    CORS(app, resources={r"/api/*": {"origins": "*"}})
    db.init_app(app)
    JWTManager(app)

    @app.before_request
    def initialize_database():
        if app.config.get('DB_INITIALIZED'):
            return

        with app.app_context():
            db.create_all()

            if not UserAccount.query.filter_by(email='admin@difanlogistics.com').first():
                admin = UserAccount()
                admin.company_name = 'Difan HQ'
                admin.email = 'admin@difanlogistics.com'
                admin.role = 'admin'
                admin.set_password('AdminSecurePassword123!')
                db.session.add(admin)

            if not Shipment.query.filter_by(tracking_number='DL-8801').first():
                sample_shipment = Shipment()
                sample_shipment.tracking_number = 'DL-8801'
                sample_shipment.cargo_type = 'Cement'
                sample_shipment.tonnage = 28.0
                sample_shipment.status = 'In Transit - Mechanical Delay'
                sample_shipment.origin = 'Athi River Industrial Zone'
                sample_shipment.destination = 'Kisumu Warehouse'
                sample_shipment.total_cost = 1850.00
                sample_shipment.breakdown_alert = True
                db.session.add(sample_shipment)

            db.session.commit()

        app.config['DB_INITIALIZED'] = True

    @app.route('/api/auth/login', methods=['POST'])
    def login():
        data = request.get_json() or {}
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')

        if not email or not password:
            return jsonify({'status': 'error', 'message': 'Email and password are required.'}), 400

        user = UserAccount.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            return jsonify({'status': 'error', 'message': 'Invalid email or password.'}), 401

        token = create_access_token(identity={
            'id': user.id,
            'email': user.email,
            'role': user.role,
            'company_name': user.company_name,
        })

        return jsonify({
            'status': 'success',
            'token': token,
            'user': user.to_dict(),
        }), 200

    @app.route('/api/auth/register', methods=['POST'])
    def register():
        data = request.get_json() or {}
        company_name = data.get('company_name', '').strip()
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')

        if not company_name or not email or not password:
            return jsonify({'status': 'error', 'message': 'All fields are required.'}), 400

        if len(password) < 6:
            return jsonify({'status': 'error', 'message': 'Password must be at least 6 characters long.'}), 400

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

    @app.route('/api/auth/me', methods=['GET'])
    @jwt_required()
    def get_current_user():
        current_user = get_jwt_identity()
        return jsonify({'status': 'success', 'user': current_user}), 200

    @app.route('/api/accounts/create', methods=['POST'])
    @jwt_required()
    def create_account():
        current_user = get_jwt_identity()
        if current_user.get('role') != 'admin':
            return jsonify({'status': 'error', 'message': 'Forbidden: Admin access required.'}), 403

        data = request.get_json() or {}
        company_name = data.get('company_name', '').strip()
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        role = data.get('role', 'client')

        if not company_name or not email or not password:
            return jsonify({'status': 'error', 'message': 'Company name, email, and password required.'}), 400

        if UserAccount.query.filter_by(email=email).first():
            return jsonify({'status': 'error', 'message': 'Email address already exists.'}), 400

        account = UserAccount()
        account.company_name = company_name
        account.email = email
        account.role = role
        account.set_password(password)
        db.session.add(account)
        db.session.commit()

        return jsonify({
            'status': 'success',
            'message': f"Account provisioned for {company_name} ({role.upper()})"
        }), 201

    @app.route('/api/shipments/track/<tracking_number>', methods=['GET'])
    def track_shipment(tracking_number):
        shipment = Shipment.query.filter_by(tracking_number=tracking_number).first()
        if not shipment:
            return jsonify({'status': 'error', 'message': 'Shipment reference not found.'}), 404

        return jsonify({'status': 'success', 'shipment': shipment.to_dict()}), 200

    @app.route('/api/shipments/quote', methods=['POST'])
    def create_quote():
        data = request.get_json() or {}
        try:
            tonnage = float(data.get('tonnage', 15))
        except (TypeError, ValueError):
            tonnage = 15.0

        urgency = data.get('urgency', 'standard')
        base_rate = tonnage * 60.0
        multiplier = 1.15 if urgency == 'express' else (1.30 if urgency == 'critical' else 1.0)
        total_cost = round(base_rate * multiplier, 2)
        deposit = round(total_cost / 2.0, 2)

        return jsonify({
            'status': 'success',
            'total_cost': total_cost,
            'deposit_due': deposit,
            'balance_due': deposit,
        }), 200

    return app


app = create_app()


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)