from pathlib import Path

from flask import Flask
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy


# ---------------------------------------------------------
# Extensions
# ---------------------------------------------------------

db = SQLAlchemy()

login_manager = LoginManager()

login_manager.login_view = "auth.login"
login_manager.login_message = "Please log in to access this page."
login_manager.login_message_category = "warning"


# ---------------------------------------------------------
# Application Factory
# ---------------------------------------------------------

def create_app():
    app = Flask(__name__)

    # -----------------------------------------------------
    # Application configuration
    # -----------------------------------------------------

    app.config["SECRET_KEY"] = "change-this-secret-key"

    # SQLite database location
    base_dir = Path(__file__).resolve().parent.parent
    instance_dir = base_dir / "instance"

    instance_dir.mkdir(exist_ok=True)

    database_path = instance_dir / "shopping.db"

    app.config["SQLALCHEMY_DATABASE_URI"] = (
        "sqlite:///" + str(database_path)
    )

    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # -----------------------------------------------------
    # Initialize extensions
    # -----------------------------------------------------

    db.init_app(app)
    login_manager.init_app(app)

    # -----------------------------------------------------
    # Register application routes
    # -----------------------------------------------------

    from app.routes.main import main_bp
    from app.routes.auth import auth_bp
    from app.routes.products import products_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(products_bp)

    # -----------------------------------------------------
    # Create database tables
    # -----------------------------------------------------

    with app.app_context():
        from app.models import User, Product, Preference
        from app.models import Favourite, Purchase

        db.create_all()

    return app


# ---------------------------------------------------------
# Flask-Login user loader
# ---------------------------------------------------------

@login_manager.user_loader
def load_user(user_id):
    from app.models import User

    return db.session.get(User, int(user_id))