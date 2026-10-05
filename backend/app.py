import os
import secrets
from sqlalchemy import inspect, text
from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from backend.models.payroll import db
from backend.routes.auth import auth_bp, bcrypt, jwt
from backend.routes.hr import hr_bp
from backend.routes.shipments import shipments_bp, seed_demo_shipment
from backend.routes.telematics import telematics_bp


def create_app():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(os.path.join(project_root, '.env'))
    instance_path = os.path.join(project_root, 'instance')
    app = Flask(
        __name__,
        instance_path=instance_path,
        instance_relative_config=True,
    )

    CORS(app)

    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY') or secrets.token_urlsafe(48)
    app.config['JWT_SECRET_KEY'] = app.config['SECRET_KEY']

    db_path = os.path.join(app.instance_path, 'database.db')
    os.makedirs(app.instance_path, exist_ok=True)

    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['MAX_CONTENT_LENGTH'] = 128 * 1024 * 1024
    app.config['SHIPMENT_DOCUMENTS_DIR'] = os.path.join(app.instance_path, 'shipment_documents')

    db.init_app(app)
    bcrypt.init_app(app)
    jwt.init_app(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(hr_bp)
    app.register_blueprint(shipments_bp)
    app.register_blueprint(telematics_bp)

    with app.app_context():
        db.create_all()
        user_columns = {column['name'] for column in inspect(db.engine).get_columns('user_accounts')}
        with db.engine.begin() as connection:
            if 'role' not in user_columns:
                connection.execute(text(
                    "ALTER TABLE user_accounts ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'client'"
                ))
            if 'driver_name' not in user_columns:
                connection.execute(text(
                    "ALTER TABLE user_accounts ADD COLUMN driver_name VARCHAR(120)"
                ))
            if 'display_name' not in user_columns:
                connection.execute(text(
                    "ALTER TABLE user_accounts ADD COLUMN display_name VARCHAR(120)"
                ))
            connection.execute(text(
                "UPDATE user_accounts SET role = 'admin' "
                "WHERE lower(email) = 'admin@difanlogistics.com'"
            ))
            shipment_columns = {
                column['name'] for column in inspect(db.engine).get_columns('shipments')
            } if inspect(db.engine).has_table('shipments') else set()
            if 'departed_at' not in shipment_columns:
                connection.execute(text("ALTER TABLE shipments ADD COLUMN departed_at DATETIME"))
            if 'arrived_at' not in shipment_columns:
                connection.execute(text("ALTER TABLE shipments ADD COLUMN arrived_at DATETIME"))
        seed_demo_shipment()

    @app.errorhandler(413)
    def file_too_large(error):
        _ = error
        return jsonify({'status': 'error', 'message': 'Upload request exceeds the 128 MB total limit.'}), 413

    @app.route('/')
    def index():
        return {"status": "success", "message": "DIFAN LOGISTICS (K) LTD Fleet & Telematics API is running."}

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=True)