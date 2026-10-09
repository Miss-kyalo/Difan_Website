import os
import secrets
from sqlalchemy import inspect, text
from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from backend.models.payroll import db
from backend.routes.auth import auth_bp, bcrypt, ensure_main_accounts, jwt
from backend.routes.hr import hr_bp
from backend.routes.portal import portal_bp
from backend.routes.shipments import shipments_bp, seed_demo_shipment
from backend.routes.fleet import fleet_bp
from backend.routes.telematics import telematics_bp
from backend.routes.workforce import install_workforce_lockout, workforce_bp


def create_app(test_config=None):
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(os.path.join(project_root, '.env'))
    instance_path = os.path.join(project_root, 'instance')
    app = Flask(
        __name__,
        instance_path=instance_path,
        instance_relative_config=True,
    )

    CORS(app)

    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY') or os.getenv('FLASK_SECRET_KEY') or secrets.token_urlsafe(48)
    app.config['JWT_SECRET_KEY'] = app.config['SECRET_KEY']
    app.config['SENDGRID_API_KEY'] = os.getenv('SENDGRID_API_KEY')
    app.config['MAIL_FROM_EMAIL'] = os.getenv('MAIL_FROM_EMAIL')
    app.config['PUBLIC_APP_URL'] = os.getenv('PUBLIC_APP_URL')
    app.config['ELD_WEBHOOK_SECRET'] = os.getenv('ELD_WEBHOOK_SECRET')
    app.config['MAIN_ACCOUNT_EMAIL'] = os.getenv(
        'MAIN_ACCOUNT_EMAIL', 'info@difan-logistics.com'
    )
    app.config['PAYROLL_DOCUMENTS_BUCKET'] = os.getenv('PAYROLL_DOCUMENTS_BUCKET')
    app.config['PAYROLL_DOCUMENT_KMS_KEY_ID'] = os.getenv('PAYROLL_DOCUMENT_KMS_KEY_ID')
    app.config['PAYROLL_DOCUMENT_RETENTION_DAYS'] = os.getenv('PAYROLL_DOCUMENT_RETENTION_DAYS')
    app.config['AWS_REGION'] = os.getenv('AWS_REGION')

    db_path = os.path.join(app.instance_path, 'database.db')
    os.makedirs(app.instance_path, exist_ok=True)

    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['MAX_CONTENT_LENGTH'] = 128 * 1024 * 1024
    app.config['SHIPMENT_DOCUMENTS_DIR'] = os.path.join(app.instance_path, 'shipment_documents')
    app.config['ANONYMOUS_REPORTS_DIR'] = os.path.join(app.instance_path, 'anonymous_reports')
    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    bcrypt.init_app(app)
    jwt.init_app(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(hr_bp)
    app.register_blueprint(portal_bp)
    app.register_blueprint(shipments_bp)
    app.register_blueprint(telematics_bp)
    app.register_blueprint(fleet_bp)
    app.register_blueprint(workforce_bp)
    install_workforce_lockout(app)

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
            if 'account_status' not in user_columns:
                connection.execute(text(
                    "ALTER TABLE user_accounts ADD COLUMN account_status VARCHAR(20) NOT NULL DEFAULT 'active'"
                ))
            if 'approved_by_id' not in user_columns:
                connection.execute(text(
                    "ALTER TABLE user_accounts ADD COLUMN approved_by_id INTEGER REFERENCES user_accounts(id)"
                ))
            if 'approved_at' not in user_columns:
                connection.execute(text(
                    "ALTER TABLE user_accounts ADD COLUMN approved_at DATETIME"
                ))
            if 'username' not in user_columns:
                connection.execute(text(
                    "ALTER TABLE user_accounts ADD COLUMN username VARCHAR(80)"
                ))
            if 'must_change_password' not in user_columns:
                connection.execute(text(
                    "ALTER TABLE user_accounts ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT 0"
                ))
            if 'notification_email' not in user_columns:
                connection.execute(text(
                    "ALTER TABLE user_accounts ADD COLUMN notification_email VARCHAR(120)"
                ))
            for column, definition in (
                ('driver_code', 'VARCHAR(20)'),
                ('employment_status', "VARCHAR(24) NOT NULL DEFAULT 'ACTIVE'"),
                ('leave_type', 'VARCHAR(16)'),
                ('employment_status_note', 'VARCHAR(500)'),
                ('employment_status_updated_at', 'DATETIME'),
                ('employment_status_updated_by_id', 'INTEGER REFERENCES user_accounts(id)'),
                ('leaderboard_opt_in', 'BOOLEAN NOT NULL DEFAULT 0'),
                ('leaderboard_handle', 'VARCHAR(40)'),
                ('ui_preferences', 'TEXT'),
                ('phone', 'VARCHAR(40)'),
                ('kra_pin', 'VARCHAR(11)'),
                ('nssf_number', 'VARCHAR(20)'),
                ('shif_number', 'VARCHAR(20)'),
            ):
                if column not in user_columns:
                    connection.execute(text(
                        f'ALTER TABLE user_accounts ADD COLUMN {column} {definition}'
                    ))
            connection.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_user_accounts_driver_code "
                "ON user_accounts (driver_code)"
            ))
            connection.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_user_accounts_username "
                "ON user_accounts (username)"
            ))
            connection.execute(text(
                "UPDATE user_accounts SET role = 'admin' "
                "WHERE lower(email) = 'admin@difanlogistics.com'"
            ))
            if inspect(db.engine).has_table('anonymous_reports'):
                report_columns = {
                    column['name'] for column in inspect(db.engine).get_columns('anonymous_reports')
                }
                if 'status' not in report_columns:
                    connection.execute(text(
                        "ALTER TABLE anonymous_reports ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'RECEIVED'"
                    ))
                if 'status_updated_at' not in report_columns:
                    connection.execute(text(
                        "ALTER TABLE anonymous_reports ADD COLUMN status_updated_at DATETIME"
                    ))
            if inspect(db.engine).has_table('vehicle_mileage_records'):
                mileage_columns = {
                    column['name'] for column in inspect(db.engine).get_columns('vehicle_mileage_records')
                }
                if 'shipment_tracking_number' not in mileage_columns:
                    connection.execute(text(
                        "ALTER TABLE vehicle_mileage_records ADD COLUMN shipment_tracking_number VARCHAR(40)"
                    ))
                if 'mileage_amount_issued_kes' not in mileage_columns:
                    connection.execute(text(
                        "ALTER TABLE vehicle_mileage_records ADD COLUMN mileage_amount_issued_kes FLOAT NOT NULL DEFAULT 0"
                    ))
            if inspect(db.engine).has_table('payroll_slips'):
                payroll_columns = {
                    column['name'] for column in inspect(db.engine).get_columns('payroll_slips')
                }
                for column_name in ('housing_allowance', 'off_duty_days', 'off_duty_pay'):
                    if column_name not in payroll_columns:
                        connection.execute(text(
                            f"ALTER TABLE payroll_slips ADD COLUMN {column_name} FLOAT NOT NULL DEFAULT 0"
                        ))
            shipment_columns = {
                column['name'] for column in inspect(db.engine).get_columns('shipments')
            } if inspect(db.engine).has_table('shipments') else set()
            if 'departed_at' not in shipment_columns:
                connection.execute(text("ALTER TABLE shipments ADD COLUMN departed_at DATETIME"))
            if 'arrived_at' not in shipment_columns:
                connection.execute(text("ALTER TABLE shipments ADD COLUMN arrived_at DATETIME"))
            if 'delivery_due_at' not in shipment_columns:
                connection.execute(text("ALTER TABLE shipments ADD COLUMN delivery_due_at DATETIME"))
            for column, definition in (
                ('truck_type', 'VARCHAR(20)'),
                ('pickup_address', 'VARCHAR(300)'),
                ('pickup_at', 'DATETIME'),
                ('end_customer_name', 'VARCHAR(200)'),
                ('end_customer_address', 'VARCHAR(300)'),
                ('end_customer_phone', 'VARCHAR(40)'),
                ('end_customer_email', 'VARCHAR(254)'),
                ('public_tracking_token_hash', 'VARCHAR(64)'),
                ('public_tracking_token_ciphertext', 'VARCHAR(255)'),
                ('public_tracking_expires_at', 'DATETIME'),
                ('quoted_amount_kes', 'FLOAT'),
                ('detention_rate_kes_per_hour', 'FLOAT NOT NULL DEFAULT 0'),
                ('destination_change_request', 'TEXT'),
                ('client_user_id', 'INTEGER REFERENCES user_accounts(id)'),
            ):
                if column not in shipment_columns:
                    connection.execute(text(
                        f'ALTER TABLE shipments ADD COLUMN {column} {definition}'
                    ))
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_shipments_client_user_id ON shipments (client_user_id)"
            ))
            connection.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_shipments_public_tracking_token_hash "
                "ON shipments (public_tracking_token_hash)"
            ))
            spare_columns = {
                column['name'] for column in inspect(db.engine).get_columns('fleet_spare_parts')
            } if inspect(db.engine).has_table('fleet_spare_parts') else set()
            for column, definition in (
                ('stock_quantity', 'INTEGER NOT NULL DEFAULT 0'),
                ('reorder_level', 'INTEGER NOT NULL DEFAULT 0'),
            ):
                if column not in spare_columns:
                    connection.execute(text(
                        f'ALTER TABLE fleet_spare_parts ADD COLUMN {column} {definition}'
                    ))
            breakdown_columns = {
                column['name'] for column in inspect(db.engine).get_columns('fleet_breakdowns')
            } if inspect(db.engine).has_table('fleet_breakdowns') else set()
            for column, definition in (
                ('incident_date', 'VARCHAR(10)'),
                ('symptoms', 'VARCHAR(1000)'),
                ('findings', 'VARCHAR(2000)'),
                ('action_taken', 'VARCHAR(2000)'),
                ('parts_used', 'VARCHAR(1000)'),
                ('replacement_driver', 'VARCHAR(120)'),
                ('mechanic_in_charge', 'VARCHAR(120)'),
            ):
                if column not in breakdown_columns:
                    connection.execute(text(
                        f'ALTER TABLE fleet_breakdowns ADD COLUMN {column} {definition}'
                    ))
            payroll_columns = {
                column['name'] for column in inspect(db.engine).get_columns('payroll_slips')
            } if inspect(db.engine).has_table('payroll_slips') else set()
            for column, definition in (
                ('salary_advance', 'FLOAT NOT NULL DEFAULT 0'),
                ('advance_signed_at', 'DATETIME'),
                ('signed_pdf_object_key', 'VARCHAR(512)'),
                ('signed_pdf_version_id', 'VARCHAR(256)'),
                ('signed_pdf_sha256', 'VARCHAR(64)'),
                ('signature_device_id', 'VARCHAR(120)'),
                ('signature_ip_address', 'VARCHAR(64)'),
                ('signature_latitude', 'FLOAT'),
                ('signature_longitude', 'FLOAT'),
                ('nssf_deduction', 'FLOAT'),
                ('shif_deduction', 'FLOAT'),
                ('housing_levy_deduction', 'FLOAT'),
                ('taxable_pay', 'FLOAT'),
                ('tax_charged', 'FLOAT'),
                ('personal_relief', 'FLOAT'),
                ('other_reliefs', 'FLOAT'),
                ('paye_tax', 'FLOAT'),
                ('dispute_message', 'VARCHAR(2000)'),
                ('dispute_submitted_at', 'DATETIME'),
                ('dispute_status', 'VARCHAR(24)'),
            ):
                if column not in payroll_columns:
                    connection.execute(text(
                        f'ALTER TABLE payroll_slips ADD COLUMN {column} {definition}'
                    ))
            driver_rating_columns = {
                column['name'] for column in inspect(db.engine).get_columns('driver_ratings')
            } if inspect(db.engine).has_table('driver_ratings') else set()
            for column in ('punctuality_stars', 'cargo_care_stars'):
                if column not in driver_rating_columns:
                    connection.execute(text(
                        f'ALTER TABLE driver_ratings ADD COLUMN {column} INTEGER'
                    ))
            workforce_case_columns = {
                column['name'] for column in inspect(db.engine).get_columns('workforce_cases')
            } if inspect(db.engine).has_table('workforce_cases') else set()
            for column, definition in (
                ('source_code', 'VARCHAR(40)'),
                ('source_reference', 'VARCHAR(120)'),
            ):
                if column not in workforce_case_columns:
                    connection.execute(text(
                        f'ALTER TABLE workforce_cases ADD COLUMN {column} {definition}'
                    ))
            connection.execute(text(
                'CREATE UNIQUE INDEX IF NOT EXISTS uq_workforce_case_automated_source '
                'ON workforce_cases (source_code, source_reference)'
            ))
            emergency_columns = {
                column['name'] for column in inspect(db.engine).get_columns('safety_emergency_reports')
            } if inspect(db.engine).has_table('safety_emergency_reports') else set()
            for column, definition in (
                ('resolved_at', 'DATETIME'),
                ('resolved_by_id', 'INTEGER REFERENCES user_accounts(id)'),
            ):
                if column not in emergency_columns:
                    connection.execute(text(
                        f'ALTER TABLE safety_emergency_reports ADD COLUMN {column} {definition}'
                    ))
        seed_demo_shipment()
        if not app.config.get('TESTING'):
            ensure_main_accounts()

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