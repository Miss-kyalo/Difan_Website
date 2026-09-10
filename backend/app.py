import os
from flask import Flask
from flask_cors import CORS
from backend.models.payroll import db
from backend.routes.telematics import telematics_bp

def create_app():
    # Initialize Flask app pointing to root path
    app = Flask(__name__, instance_relative_config=True)
    
    # Enable CORS to allow frontend communication across different ports (e.g., Live Server / Port 5000)
    CORS(app)

    # Configuration setup
    app.config['SECRET_KEY'] = 'difan-logistics-secret-key-2026'
    
    # Ensure instance folder exists for SQLite database
    db_path = os.path.join(app.instance_path, 'database.db')
    os.makedirs(app.instance_path, exist_ok=True)
    
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Initialize SQLAlchemy with the app
    db.init_app(app)

    # Register Blueprints
    app.register_blueprint(telematics_bp)

    # Automatically create database tables if they don't exist yet
    with app.app_context():
        db.create_all()

    @app.route('/')
    def index():
        return {"status": "success", "message": "DIFAN LOGISTICS (K) LTD Fleet & Telematics API is running."}

    return app

if __name__ == '__main__':
    app = create_app()
    # Runs the Flask development server on port 5000
    app.run(host='0.0.0.0', port=5000, debug=True)