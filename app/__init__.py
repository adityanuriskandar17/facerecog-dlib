from flask import Flask
from .config import FLASK_SECRET_KEY
from .blueprints.auth import auth_bp
from .blueprints.main import main_bp
from .blueprints.recognition import recognition_bp
from .blueprints.admin import admin_bp

def create_app():
    """Create and configure Flask application"""
    app = Flask(__name__, template_folder='templates', static_folder='static')
    app.secret_key = FLASK_SECRET_KEY
    
    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(recognition_bp)
    app.register_blueprint(admin_bp)
    
    return app
